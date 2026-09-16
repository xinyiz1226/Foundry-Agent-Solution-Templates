"""Small G0 create-only Blob ledger; authenticated clients belong to the caller."""

from dataclasses import asdict, replace
import hashlib
import json
import math
import re

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.storage.blob import ContainerClient

from .codec import _hash, _json, _plan, _snapshot
from .contracts import (
    Action, Blocked, Claim, Conflict, Evidence, FailureCode, IntegrityError,
    InvalidInput, NotFound, Plan, ReviewStatus, Snapshot, StaleRevision,
    Status, TokenUsage, validate_identifier,
)
from .outputs import validate_published_records


MAX_BLOB_BYTES = 8 * 1024 * 1024


class BlobStore:
    """Immutable receipts, claims, snapshots and commit markers; no local state.

    The prefix is one ledger/request-ID namespace, not an authorization boundary.
    All writes disable SDK retries, including on caller-configured clients.
    """

    def __init__(self, container: ContainerClient, *, prefix: str = "extraction"):
        if type(prefix) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", prefix) is None:
            raise InvalidInput("invalid_blob_prefix")
        self.container = container
        self.prefix = f"{prefix}/g0-blob-v1"

    def _job(self, job_id):
        return f"{self.prefix}/jobs/{_hash(job_id)}"

    def read_batch_record(self, key: str) -> str | None:
        validate_identifier(key)
        saved = self._load(f"{self.prefix}/batch/{key}.json", "batch", optional=True)
        return None if saved is None else _json(saved[0])

    def create_batch_record(self, key: str, payload: str) -> str:
        validate_identifier(key)
        self._put(
            f"{self.prefix}/batch/{key}.json", "batch", json.loads(payload), exclusive=True,
        )
        saved = self.read_batch_record(key)
        if saved is None:
            raise IntegrityError("batch_record_missing")
        return saved

    def _name(self, job_id, kind, revision=None):
        base = self._job(job_id)
        return f"{base}/{kind}.json" if revision is None else f"{base}/{kind}/{revision:020d}.json"

    def _receipt_name(self, request_id):
        return f"{self.prefix}/requests/{_hash(request_id)}.json"

    def _encode(self, name, kind, value):
        payload = _json(value)
        raw = _json({
            "version": 1, "name": name, "kind": kind, "payload": payload,
            "length": len(payload.encode("utf-8")), "sha256": _hash(payload),
        }).encode("utf-8")
        if len(raw) > MAX_BLOB_BYTES:
            raise InvalidInput("blob_payload_too_large")
        return raw

    @staticmethod
    def _ref(name, raw):
        return {"name": name, "length": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    @staticmethod
    def _validate_ref(reference):
        if (
            type(reference) is not dict or set(reference) != {"name", "length", "sha256"}
            or type(reference["name"]) is not str
            or type(reference["length"]) is not int
            or not 0 < reference["length"] <= MAX_BLOB_BYTES
            or type(reference["sha256"]) is not str
            or re.fullmatch("[0-9a-f]{64}", reference["sha256"]) is None
        ):
            raise IntegrityError("blob_reference_invalid")

    def _load(self, name, kind, *, optional=False, reference=None):
        if reference is not None:
            self._validate_ref(reference)
        client = self.container.get_blob_client(name)
        try:
            properties = client.get_blob_properties(retry_total=0, retry_to_secondary=False)
            size = properties.size
            if type(size) is not int or not 0 < size <= MAX_BLOB_BYTES:
                raise IntegrityError("blob_length_invalid")
            if reference is not None and (
                reference.get("name") != name or reference.get("length") != size
            ):
                raise IntegrityError("blob_reference_mismatch")
        except ResourceNotFoundError as error:
            if optional:
                return None
            raise IntegrityError("referenced_blob_missing") from error
        try:
            raw = client.download_blob(
                offset=0, length=size, etag=properties.etag,
                match_condition=MatchConditions.IfNotModified,
                retry_total=0, retry_to_secondary=False,
            ).readall()
        except ResourceNotFoundError as error:
            raise IntegrityError("referenced_blob_missing") from error
        except ResourceModifiedError as error:
            raise IntegrityError("blob_changed_during_read") from error
        if len(raw) != size or len(raw) > MAX_BLOB_BYTES:
            raise IntegrityError("download_length_mismatch")
        ref = self._ref(name, raw)
        if reference is not None and ref != reference:
            raise IntegrityError("blob_reference_mismatch")
        try:
            envelope = json.loads(raw)
            if (
                raw != _json(envelope).encode("utf-8")
                or set(envelope) != {"version", "name", "kind", "payload", "length", "sha256"}
                or type(envelope["version"]) is not int or envelope["version"] != 1
                or envelope["name"] != name or envelope["kind"] != kind
                or type(envelope["length"]) is not int
                or len(envelope["payload"].encode("utf-8")) != envelope["length"]
                or _hash(envelope["payload"]) != envelope["sha256"]
            ):
                raise IntegrityError("blob_envelope_mismatch")
            value = json.loads(envelope["payload"])
            if type(value) is not dict or _json(value) != envelope["payload"]:
                raise IntegrityError("blob_payload_noncanonical")
            if kind == "receipt":
                self._validate_receipt(value, name)
            return value, ref
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise IntegrityError("blob_payload_invalid") from error

    def _put(self, name, kind, value, *, exclusive=False):
        raw = self._encode(name, kind, value)
        try:
            self.container.get_blob_client(name).upload_blob(
                raw, blob_type="BlockBlob", length=len(raw), overwrite=False,
                retry_total=0, retry_to_secondary=False,
            )
        except ResourceExistsError:
            if exclusive:
                return False
            existing = self._load(name, kind)
            if existing[1] != self._ref(name, raw):
                raise Conflict("immutable_blob_conflict")
        return self._ref(name, raw)

    def _checkpoint_names(self, job_id):
        prefix = f"{self._job(job_id)}/checkpoints/"
        return sorted(item.name for item in self.container.list_blobs(
            name_starts_with=prefix, retry_total=0, retry_to_secondary=False,
        ))

    def _manifest(self, job_id):
        value = self._load(self._name(job_id, "manifest"), "manifest", optional=True)
        if value is None:
            return None
        try:
            data, ref = value
            plan = _plan(data["plan"])
            if _json(data) != _json({
                "job_id": job_id, "plan": asdict(plan),
                "plan_fingerprint": _hash(_json(asdict(plan))),
            }):
                raise IntegrityError("manifest_binding_mismatch")
            return plan, data["plan_fingerprint"], ref
        except (KeyError, TypeError, ValueError, AttributeError, InvalidInput) as error:
            raise IntegrityError("manifest_invalid") from error

    def _claim_data(self, base, checkpoint_ref, request_id, action):
        chunk = base.plan.chunks[len(base.completed_chunk_ids)]
        return {
            "job_id": base.job_id, "plan_fingerprint": base.plan_fingerprint,
            "base": checkpoint_ref,
            "claim": asdict(Claim(request_id, base.revision, action, chunk.id)),
        }

    def _receipt(self, job_id, fingerprint, request_id, action, expected, revision, claim=None):
        return {
            "job_id": job_id, "plan_fingerprint": fingerprint, "request_id": request_id,
            "action": action, "expected_revision": expected,
            "result_revision": revision, "result_claim": asdict(claim) if claim else None,
        }

    def _validate_receipt(self, receipt, name):
        try:
            if set(receipt) != {
                "job_id", "plan_fingerprint", "request_id", "action",
                "expected_revision", "result_revision", "result_claim",
            }:
                raise IntegrityError("receipt_fields_invalid")
            validate_identifier(receipt["job_id"])
            validate_identifier(receipt["request_id"])
            revision = receipt["result_revision"]
            if (
                self._receipt_name(receipt["request_id"]) != name
                or type(revision) is not int or revision < 0
                or type(receipt["plan_fingerprint"]) is not str
                or re.fullmatch("[0-9a-f]{64}", receipt["plan_fingerprint"]) is None
            ):
                raise IntegrityError("receipt_binding_invalid")
            if receipt["action"] == "create":
                if receipt["expected_revision"] is not None:
                    raise IntegrityError("receipt_revision_invalid")
                data = receipt["result_claim"]
                if data is not None:
                    claim = Claim(**{**data, "action": Action(data["action"])})
                    validate_identifier(claim.request_id)
                    validate_identifier(claim.chunk_id)
                    if type(claim.expected_revision) is not int or claim.expected_revision != revision:
                        raise IntegrityError("receipt_claim_invalid")
            elif (
                receipt["action"] not in (Action.ADVANCE, Action.RESUME)
                or type(receipt["expected_revision"]) is not int
                or receipt["expected_revision"] < 0
                or revision != receipt["expected_revision"] + 1
                or receipt["result_claim"] is not None
            ):
                raise IntegrityError("receipt_action_invalid")
        except (KeyError, TypeError, ValueError, InvalidInput) as error:
            raise IntegrityError("receipt_invalid") from error

    def _claimed(self, base, checkpoint_ref):
        saved = self._load(self._name(base.job_id, "claims", base.revision), "claim", optional=True)
        if saved is None:
            return base
        try:
            data = saved[0]
            claim = Claim(**{**data["claim"], "action": Action(data["claim"]["action"])})
            if type(claim.expected_revision) is not int:
                raise IntegrityError("claim_revision_invalid")
            if base.status == Status.COMPLETED or (
                (base.status == Status.FAILED) != (claim.action == Action.RESUME)
            ):
                raise IntegrityError("claim_status_mismatch")
            expected = self._claim_data(base, checkpoint_ref, claim.request_id, claim.action)
            if _json(data) != _json(expected):
                raise IntegrityError("claim_binding_mismatch")
            receipt = self._load(self._receipt_name(claim.request_id), "receipt")[0]
            if receipt != self._receipt(
                base.job_id, base.plan_fingerprint, claim.request_id, claim.action,
                base.revision, base.revision + 1,
            ):
                raise IntegrityError("claim_receipt_mismatch")
            return replace(base, status=Status.IN_PROGRESS, claim=claim)
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
            raise IntegrityError("claim_invalid") from error

    def _history(self, job_id):
        manifest = self._manifest(job_id)
        if manifest is None:
            remaining = self.container.list_blobs(
                name_starts_with=f"{self._job(job_id)}/", retry_total=0, retry_to_secondary=False,
            )
            if next(iter(remaining), None) is not None:
                raise IntegrityError("manifest_missing")
            raise NotFound("job_not_found")
        plan, fingerprint, parent = manifest
        names = self._checkpoint_names(job_id)
        if not names or names != [
            self._name(job_id, "checkpoints", revision) for revision in range(len(names))
        ]:
            raise IntegrityError("checkpoint_gap")
        history = []
        try:
            for revision, name in enumerate(names):
                marker, ref = self._load(name, "checkpoint")
                if set(marker) != {"parent", "snapshot", "claim"} or marker["parent"] != parent:
                    raise IntegrityError("checkpoint_chain_mismatch")
                self._validate_ref(marker["parent"])
                self._validate_ref(marker["snapshot"])
                if revision:
                    self._validate_ref(marker["claim"])
                data, _ = self._load(
                    self._name(job_id, "snapshots", revision), "snapshot",
                    reference=marker["snapshot"],
                )
                payload = _json(data)
                result = _snapshot(payload, _hash(payload))
                if type(result.revision) is not int:
                    raise IntegrityError("checkpoint_revision_invalid")
                if revision == 0:
                    if result != Snapshot(job_id, plan, fingerprint) or marker["claim"] is not None:
                        raise IntegrityError("initial_checkpoint_mismatch")
                else:
                    claimed = self._claimed(history[-1][0], parent)
                    claim_ref = self._load(self._name(job_id, "claims", revision - 1), "claim")[1]
                    if marker["claim"] != claim_ref:
                        raise IntegrityError("checkpoint_claim_mismatch")
                    self._validate_result(claimed, result)
                history.append((result, ref))
                parent = ref
        except (KeyError, TypeError, ValueError, IndexError, AttributeError, InvalidInput, Conflict) as error:
            raise IntegrityError("checkpoint_invalid") from error
        return history

    def read(self, job_id: str) -> Snapshot:
        base, ref = self._history(job_id)[-1]
        return self._claimed(base, ref)

    def _initialize(self, job_id, plan, fingerprint):
        manifest = self._put(self._name(job_id, "manifest"), "manifest", {
            "job_id": job_id, "plan": asdict(plan), "plan_fingerprint": fingerprint,
        })
        initial = Snapshot(job_id, plan, fingerprint)
        snapshot = self._put(self._name(job_id, "snapshots", 0), "snapshot", asdict(initial))
        self._put(self._name(job_id, "checkpoints", 0), "checkpoint", {
            "parent": manifest, "snapshot": snapshot, "claim": None,
        })

    def _replay(self, receipt):
        history = self._history(receipt["job_id"])
        revision = receipt["result_revision"]
        if revision >= len(history):
            raise Blocked("unresolved_request")
        base, ref = history[revision]
        if receipt["action"] == "create":
            if receipt["result_claim"] is not None:
                base = self._claimed(base, ref)
                if base.claim is None or asdict(base.claim) != receipt["result_claim"]:
                    raise IntegrityError("create_replay_claim_mismatch")
        elif not base.attempts or base.attempts[-1].request_id != receipt["request_id"]:
            raise Blocked("request_did_not_commit")
        if base.plan_fingerprint != receipt["plan_fingerprint"]:
            raise Conflict("job_identity_conflict")
        return base

    def create(self, job_id: str, plan: Plan, request_id: str) -> Snapshot:
        fingerprint = _hash(_json(asdict(plan)))
        # Reject oversized input before reserving request identity.
        self._encode(self._name(job_id, "manifest"), "manifest", {
            "job_id": job_id, "plan": asdict(plan), "plan_fingerprint": fingerprint,
        })
        self._encode(self._name(job_id, "snapshots", 0), "snapshot",
                     asdict(Snapshot(job_id, plan, fingerprint)))
        manifest = self._manifest(job_id)
        if manifest is None:
            remaining = self.container.list_blobs(
                name_starts_with=f"{self._job(job_id)}/", retry_total=0, retry_to_secondary=False,
            )
            if next(iter(remaining), None) is not None:
                # Another initializer may just have written the manifest.
                manifest = self._manifest(job_id)
                if manifest is None:
                    raise IntegrityError("manifest_missing")
        if manifest is not None and manifest[1] != fingerprint:
            raise Conflict("job_identity_conflict")
        name = self._receipt_name(request_id)
        saved = self._load(name, "receipt", optional=True)
        if saved is not None:
            receipt = saved[0]
            if any(receipt[key] != value for key, value in (
                ("job_id", job_id), ("plan_fingerprint", fingerprint),
                ("request_id", request_id), ("action", "create"), ("expected_revision", None),
            )):
                raise Conflict("request_identity_conflict")
        else:
            if manifest is None or not self._checkpoint_names(job_id):
                result = Snapshot(job_id, plan, fingerprint)
            else:
                result = self.read(job_id)
            receipt = self._receipt(
                job_id, fingerprint, request_id, "create", None, result.revision, result.claim,
            )
            if not self._put(name, "receipt", receipt, exclusive=True):
                return self.create(job_id, plan, request_id)
        if receipt["result_revision"] == 0 and (
            manifest is None or not self._checkpoint_names(job_id)
        ):
            self._initialize(job_id, plan, fingerprint)
        return self._replay(receipt)

    def claim(self, job_id: str, expected_revision: int, request_id: str, action: Action) -> Snapshot:
        history = self._history(job_id)
        base, ref = history[-1]
        receipt = self._receipt(
            job_id, base.plan_fingerprint, request_id, action,
            expected_revision, expected_revision + 1,
        )
        name = self._receipt_name(request_id)
        saved = self._load(name, "receipt", optional=True)
        if saved is not None:
            if saved[0] != receipt:
                raise Conflict("request_identity_conflict")
            return self._replay(receipt)
        current = self._claimed(base, ref)
        if current.revision != expected_revision:
            raise StaleRevision("stale_revision")
        if current.claim is not None:
            raise Blocked("unresolved_claim")
        if current.status == Status.COMPLETED:
            raise Conflict("job_completed")
        if (current.status == Status.FAILED) != (action == Action.RESUME):
            raise Conflict("explicit_resume_required_or_not_applicable")
        if not self._put(name, "receipt", receipt, exclusive=True):
            saved = self._load(name, "receipt")[0]
            if saved != receipt:
                raise Conflict("request_identity_conflict")
            return self._replay(receipt)
        data = self._claim_data(base, ref, request_id, action)
        if not self._put(self._name(job_id, "claims", expected_revision), "claim", data, exclusive=True):
            raise Blocked("unresolved_claim")
        return replace(base, status=Status.IN_PROGRESS, claim=Claim(**data["claim"]))

    @staticmethod
    def _validate_result(claimed, result):
        before, after = asdict(claimed), asdict(result)
        if (
            claimed.claim is None or result.job_id != claimed.job_id
            or result.plan != claimed.plan or result.plan_fingerprint != claimed.plan_fingerprint
            or type(result.revision) is not int
            or result.revision != claimed.revision + 1 or result.claim is not None
            or type(result.attempts) is not tuple or type(result.candidates) is not tuple
            or type(result.completed_chunk_ids) is not tuple
            or not isinstance(result.status, Status)
            or len(result.attempts) != len(claimed.attempts) + 1
            or _json(after["attempts"][:-1]) != _json(before["attempts"])
            or _json(after["candidates"][:len(claimed.candidates)]) != _json(before["candidates"])
        ):
            raise Conflict("publication_binding_conflict")
        attempt = result.attempts[-1]
        chunk = claimed.plan.chunks[len(claimed.completed_chunk_ids)]
        if (
            type(attempt.revision) is not int
            or (attempt.request_id, attempt.revision, attempt.chunk_id) != (
                claimed.claim.request_id, result.revision, chunk.id,
            )
            or (attempt.failure_code is not None and not isinstance(attempt.failure_code, FailureCode))
            or (attempt.usage is not None and (
                not isinstance(attempt.usage, TokenUsage) or any(
                    type(count) is not int or count < 0
                    for count in (attempt.usage.input_tokens, attempt.usage.output_tokens)
                )
            ))
        ):
            raise Conflict("publication_attempt_conflict")
        success = attempt.failure_code is None
        completed = (*claimed.completed_chunk_ids, chunk.id) if success else claimed.completed_chunk_ids
        status = Status.FAILED if not success else (
            Status.COMPLETED if len(completed) == len(claimed.plan.chunks) else Status.READY
        )
        if (
            result.completed_chunk_ids != completed or result.status != status
            or attempt.covered_block_ids != (tuple(block.id for block in chunk.blocks) if success else ())
            or (not success and _json(after["candidates"]) != _json(before["candidates"]))
        ):
            raise Conflict("publication_progress_conflict")
        blocks = {block.id: block for block in chunk.blocks}
        for index, candidate in enumerate(result.candidates[len(claimed.candidates):]):
            if (
                candidate.id != f"{claimed.job_id}:{result.revision}:{index}"
                or candidate.job_id != claimed.job_id
                or type(candidate.revision) is not int or candidate.revision != result.revision
                or candidate.plan_fingerprint != claimed.plan_fingerprint
                or candidate.review_status != ReviewStatus.PENDING
                or candidate.semantic_validation_performed is not False
                or type(candidate.evidence) is not tuple or not candidate.evidence
                or len({evidence.block_id for evidence in candidate.evidence}) != len(candidate.evidence)
            ):
                raise Conflict("publication_candidate_conflict")
            for evidence in candidate.evidence:
                block = blocks.get(evidence.block_id)
                if block is None or evidence != Evidence(
                    claimed.plan.document_id, chunk.id, block.id, block.location, block.text,
                ):
                    raise Conflict("publication_evidence_conflict")
        validate_published_records(claimed, chunk, result.candidates[len(claimed.candidates):])

    def publish(self, claimed: Snapshot, result: Snapshot) -> Snapshot:
        self._validate_result(claimed, result)
        history = self._history(claimed.job_id)
        if claimed.revision >= len(history):
            raise Conflict("publication_owner_conflict")
        base, parent = history[claimed.revision]
        if _json(asdict(self._claimed(base, parent))) != _json(asdict(claimed)):
            raise Conflict("publication_owner_conflict")
        if result.revision < len(history):
            if _json(asdict(history[result.revision][0])) != _json(asdict(result)):
                raise Conflict("immutable_result_conflict")
            return history[result.revision][0]
        claim_ref = self._load(self._name(claimed.job_id, "claims", claimed.revision), "claim")[1]
        snapshot = self._put(
            self._name(result.job_id, "snapshots", result.revision), "snapshot", asdict(result),
        )
        self._put(self._name(result.job_id, "checkpoints", result.revision), "checkpoint", {
            "parent": parent, "snapshot": snapshot, "claim": claim_ref,
        })
        return result
