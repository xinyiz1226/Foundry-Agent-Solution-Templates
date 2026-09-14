from threading import Lock
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from dataclasses import asdict, replace
import hashlib
import json
import unittest

from information_extraction import Action, Blocked, Conflict, Execution, IntegrityError, Status
from information_extraction.contracts import InvalidInput, NotFound
from information_extraction.sample import synthetic_plan
from tests import test_execution as contract

SyntheticModel = contract.SyntheticModel

try:
    from azure.core.exceptions import (
        ResourceExistsError, ResourceModifiedError, ResourceNotFoundError, ServiceResponseError,
    )
    from azure.storage.blob import ContainerClient
except ImportError:
    AZURE_AVAILABLE = False
else:
    AZURE_AVAILABLE = True


class Backend:
    """SDK-boundary fake: independent clients share only immutable remote bytes."""

    def __init__(self):
        self.blobs = {}
        self.lock = Lock()
        self.writes = []
        self.before_write = lambda name, data: None
        self.after_write = lambda name, data: None
        self.size_override = {}
        self.download_override = {}
        self.downloads = []
        self.before_download = lambda name: None

    def rewrite(self, name, change):
        envelope = json.loads(self.blobs[name])
        value = json.loads(envelope["payload"])
        change(value)
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
        envelope.update(payload=payload, length=len(payload.encode()),
                        sha256=hashlib.sha256(payload.encode()).hexdigest())
        self.blobs[name] = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()


class FakeBlobClient:
    def __init__(self, backend, name):
        self.backend, self.name = backend, name

    def upload_blob(self, data, blob_type="BlockBlob", length=None, **kwargs):
        assert kwargs["overwrite"] is False
        assert kwargs["retry_total"] == 0
        assert blob_type == "BlockBlob"
        self.backend.before_write(self.name, data)
        with self.backend.lock:
            if self.name in self.backend.blobs:
                raise ResourceExistsError("already_exists")
            self.backend.blobs[self.name] = bytes(data)
            self.backend.writes.append(self.name)
        self.backend.after_write(self.name, data)
        return {"etag": '"fixture-etag"'}

    def get_blob_properties(self, **kwargs):
        with self.backend.lock:
            if self.name not in self.backend.blobs:
                raise ResourceNotFoundError("missing")
            size = self.backend.size_override.get(self.name, len(self.backend.blobs[self.name]))
            return SimpleNamespace(size=size, etag='"fixture-etag"')

    def download_blob(self, offset=None, length=None, **kwargs):
        self.backend.before_download(self.name)
        with self.backend.lock:
            if self.name not in self.backend.blobs:
                raise ResourceNotFoundError("missing")
            data = self.backend.download_override.get(self.name, self.backend.blobs[self.name])
            self.backend.downloads.append(self.name)
        assert offset == 0
        assert length is not None
        assert kwargs["etag"] == '"fixture-etag"'
        return SimpleNamespace(readall=lambda: data)


class FakeContainerClient:
    def __init__(self, backend):
        self.backend = backend

    def get_blob_client(self, blob, **kwargs):
        return FakeBlobClient(self.backend, blob)

    def list_blobs(self, name_starts_with=None, include=None, **kwargs):
        with self.backend.lock:
            return iter(SimpleNamespace(name=name) for name in sorted(self.backend.blobs)
                        if name.startswith(name_starts_with or ""))


@unittest.skipUnless(AZURE_AVAILABLE, "optional Azure dependencies not installed")
class BlobExecutionTests(unittest.TestCase):
    def setUp(self):
        from information_extraction.blob_store import BlobStore
        self.backend = Backend()
        self.make_store = lambda: BlobStore(FakeContainerClient(self.backend), prefix="fixture-v1")
        self.model = SyntheticModel()
        self.execution = Execution(self.make_store(), self.model)

    test_two_chunks_commit_once_with_original_evidence_and_pending_review = (
        contract.ExecutionTests.test_two_chunks_commit_once_with_original_evidence_and_pending_review
    )

    def test_restored_adapter_reads_and_replays_without_local_files(self):
        initial = self.execution.create("job", synthetic_plan(), "create")
        first = self.execution.advance("job", 0, "advance-1")
        other_model = SyntheticModel()
        restored = Execution(self.make_store(), other_model)
        self.assertEqual(restored.read("job"), first)
        self.assertEqual(restored.advance("job", 0, "advance-1"), first)
        self.assertEqual(restored.create("job", synthetic_plan(), "create"), initial)
        self.assertEqual(other_model.calls, [])
        completed = restored.advance("job", 1, "advance-2")
        self.assertEqual(completed.status, Status.COMPLETED)
        self.assertEqual(completed.candidates[0], first.candidates[0])
        self.assertEqual([request.chunk.id for request in other_model.calls], ["chunk-2"])

    def test_create_interrupted_at_each_write_can_finish_without_model(self):
        for suffix in ("/requests/", "/manifest.json", "/snapshots/", "/checkpoints/"):
            for after in (False, True):
                with self.subTest(suffix=suffix, after=after):
                    self.setUp()

                    def interrupt(name, data):
                        if suffix in name:
                            raise ServiceResponseError("unknown_write_outcome")

                    setattr(self.backend, "after_write" if after else "before_write", interrupt)
                    with self.assertRaises(ServiceResponseError):
                        self.execution.create("job", synthetic_plan(), "create")
                    self.backend.before_write = self.backend.after_write = lambda name, data: None
                    restored = Execution(self.make_store(), self.model)
                    result = restored.create("job", synthetic_plan(), "create")
                    self.assertEqual((result.revision, result.status), (0, Status.READY))
                    self.assertEqual(restored.read("job"), result)
                    self.assertEqual(self.model.calls, [])

    def test_claim_timeout_never_authorizes_matching_request_inference(self):
        for after in (False, True):
            with self.subTest(after=after):
                self.setUp()
                self.execution.create("job", synthetic_plan(), "create")

                def interrupt(name, data):
                    if "/claims/" in name:
                        raise ServiceResponseError("unknown_write_outcome")

                setattr(self.backend, "after_write" if after else "before_write", interrupt)
                with self.assertRaises(ServiceResponseError):
                    self.execution.advance("job", 0, "advance")
                self.backend.before_write = self.backend.after_write = lambda name, data: None
                restored = Execution(self.make_store(), self.model)
                self.assertEqual(restored.read("job").status, Status.IN_PROGRESS if after else Status.READY)
                with self.assertRaises(Blocked):
                    restored.advance("job", 0, "advance")
                self.assertEqual(self.model.calls, [])
                if after:
                    with self.assertRaises(Blocked):
                        restored.advance("job", 0, "other-request")

    def test_publication_crash_before_marker_blocks_but_committed_timeout_replays(self):
        for suffix, after in (("/snapshots/", False), ("/snapshots/", True),
                              ("/checkpoints/", False), ("/checkpoints/", True)):
            with self.subTest(suffix=suffix, after=after):
                self.setUp()
                self.execution.create("job", synthetic_plan(), "create")

                def interrupt(name, data):
                    if suffix in name:
                        raise ServiceResponseError("unknown_write_outcome")

                setattr(self.backend, "after_write" if after else "before_write", interrupt)
                with self.assertRaises(ServiceResponseError):
                    self.execution.advance("job", 0, "advance")
                self.backend.before_write = self.backend.after_write = lambda name, data: None
                restored = Execution(self.make_store(), self.model)
                committed = suffix == "/checkpoints/" and after
                result = restored.read("job")
                self.assertEqual((result.revision, result.status),
                                 (1, Status.READY) if committed else (0, Status.IN_PROGRESS))
                if committed:
                    self.assertEqual(restored.advance("job", 0, "advance"), result)
                else:
                    with self.assertRaises(Blocked):
                        restored.advance("job", 0, "advance")
                self.assertEqual(len(self.model.calls), 1)

    def test_missing_committed_reference_or_checkpoint_gap_is_integrity_failure(self):
        for target in ("manifest", "snapshots", "claims", "requests", "checkpoint-gap"):
            with self.subTest(target=target):
                self.setUp()
                self.execution.create("job", synthetic_plan(), "create")
                self.execution.advance("job", 0, "advance-1")
                self.execution.advance("job", 1, "advance-2")
                if target == "checkpoint-gap":
                    name = next(name for name in self.backend.blobs
                                if "/checkpoints/" in name and name.endswith("00001.json"))
                elif target == "requests":
                    name = next(name for name, raw in self.backend.blobs.items()
                                if "/requests/" in name and "advance-1" in raw.decode())
                else:
                    name = next(name for name in self.backend.blobs if f"/{target}" in name)
                del self.backend.blobs[name]
                with self.assertRaises(IntegrityError):
                    self.execution.read("job")
                with self.assertRaises(IntegrityError):
                    self.execution.advance("job", 2, "new")
                self.assertEqual(len(self.model.calls), 2)

    def test_payload_digest_reference_length_and_oversized_download_are_checked(self):
        from information_extraction.blob_store import MAX_BLOB_BYTES
        for damage in ("payload", "digest", "short", "long", "oversized", "reference", "wrong-name"):
            with self.subTest(damage=damage):
                self.setUp()
                self.execution.create("job", synthetic_plan(), "create")
                name = next(name for name in self.backend.blobs if "/snapshots/" in name)
                envelope = json.loads(self.backend.blobs[name])
                if damage == "payload":
                    envelope["payload"] += " "
                elif damage == "digest":
                    envelope["sha256"] = "0" * 64
                elif damage == "wrong-name":
                    envelope["name"] = "unrelated"
                elif damage == "reference":
                    envelope["payload"] = envelope["payload"].replace('"revision":0', '"revision":9')
                    envelope["sha256"] = hashlib.sha256(envelope["payload"].encode()).hexdigest()
                elif damage == "oversized":
                    self.backend.size_override[name] = MAX_BLOB_BYTES + 1
                else:
                    raw = self.backend.blobs[name]
                    self.backend.download_override[name] = raw[:-1] if damage == "short" else raw + b" "
                self.backend.blobs[name] = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
                self.backend.downloads.clear()
                with self.assertRaises(IntegrityError):
                    self.execution.read("job")
                if damage == "oversized":
                    self.assertNotIn(name, self.backend.downloads)
                self.assertEqual(self.model.calls, [])

    def test_absent_job_and_prefix_validation(self):
        from information_extraction.blob_store import BlobStore
        with self.assertRaises(NotFound):
            self.execution.read("absent")
        for prefix in ("", "../unsafe", "x/y", "x?credential", "x" * 129):
            with self.assertRaises(InvalidInput):
                BlobStore(FakeContainerClient(self.backend), prefix=prefix)

    def test_oversized_plan_is_rejected_before_any_write(self):
        from information_extraction.blob_store import MAX_BLOB_BYTES
        plan = synthetic_plan()
        block = replace(plan.chunks[0].blocks[0], text="x" * MAX_BLOB_BYTES)
        plan = replace(plan, chunks=(replace(plan.chunks[0], blocks=(block,)),))
        with self.assertRaises(InvalidInput):
            self.execution.create("job", plan, "create")
        self.assertEqual(self.backend.writes, [])
        self.assertEqual(self.model.calls, [])

    def test_publication_rejects_forged_candidate_evidence_and_usage(self):
        store = self.make_store()
        self.execution.create("job", synthetic_plan(), "create")
        saved = {}

        class CapturePublication:
            read = store.read
            claim = store.claim

            def publish(self, claimed, result):
                saved.update(claimed=claimed, result=result)
                raise RuntimeError("interrupted_before_publication")

        with self.assertRaises(RuntimeError):
            Execution(CapturePublication(), self.model).advance("job", 0, "advance")
        claimed, result = saved["claimed"], saved["result"]
        candidate = result.candidates[0]
        changes = (
            replace(result, candidates=(replace(candidate, job_id="other"),)),
            replace(result, candidates=(replace(candidate, revision=7),)),
            replace(result, candidates=(replace(candidate, id="forged"),)),
            replace(result, candidates=(replace(candidate, plan_fingerprint="0" * 64),)),
            replace(result, candidates=(replace(candidate, semantic_validation_performed=True),)),
            replace(result, candidates=(replace(candidate, evidence=()),)),
            replace(result, candidates=(replace(candidate, evidence=(
                replace(candidate.evidence[0], text="fabricated evidence"),
            )),)),
            replace(result, candidates=(replace(candidate, record=replace(candidate.record, value=True)),)),
            replace(result, attempts=(replace(result.attempts[0], usage=contract.TokenUsage(-1, 0)),)),
            replace(result, revision=True),
        )
        for index, changed in enumerate(changes):
            with self.subTest(index=index):
                with self.assertRaises(Conflict):
                    store.publish(claimed, changed)
                self.assertEqual(self.execution.read("job"), claimed)
        self.assertEqual(store.publish(claimed, result), result)
        self.assertEqual(store.publish(claimed, result), result)
        different_bytes = replace(result, candidates=(
            replace(candidate, record=replace(candidate.record, value=120.0)),
        ))
        with self.assertRaises(Conflict):
            store.publish(claimed, different_bytes)
        self.assertEqual(len(self.model.calls), 1)

    def test_historical_active_create_and_publish_replay_keep_exact_saved_bytes(self):
        store = self.make_store()
        self.execution.create("job", synthetic_plan(), "create")
        snapshots = {}
        complete = self.model.complete

        def observe(request):
            snapshots["claimed"] = self.execution.create("job", synthetic_plan(), "create-active")
            return complete(request)

        self.model.complete = observe
        first = self.execution.advance("job", 0, "advance-1")
        self.model.complete = complete
        self.execution.advance("job", 1, "advance-2")
        self.assertEqual(
            self.execution.create("job", synthetic_plan(), "create-active"), snapshots["claimed"],
        )
        self.assertEqual(store.publish(snapshots["claimed"], first), first)
        self.assertEqual(len(self.model.calls), 2)

    def test_publication_cannot_change_bytes_of_an_earlier_successful_record(self):
        self.execution.create("job", synthetic_plan(), "create")
        first = self.execution.advance("job", 0, "advance-1")
        store = self.make_store()
        saved = {}

        class CapturePublication:
            read = store.read
            claim = store.claim

            def publish(self, claimed, result):
                saved.update(claimed=claimed, result=result)
                raise RuntimeError("interrupted_before_publication")

        with self.assertRaises(RuntimeError):
            Execution(CapturePublication(), self.model).advance("job", 1, "advance-2")
        candidate = first.candidates[0]
        result = saved["result"]
        changed = replace(result, candidates=(
            replace(candidate, record=replace(candidate.record, value=120.0)), result.candidates[1],
        ))
        with self.assertRaises(Conflict):
            store.publish(saved["claimed"], changed)

    def test_malformed_receipt_fails_safely_instead_of_python_error(self):
        self.execution.create("job", synthetic_plan(), "create")
        name = next(name for name in self.backend.blobs if "/requests/" in name)
        envelope = json.loads(self.backend.blobs[name])
        for payload in ('{}', '{"result_revision":-1}', '[]', 'null'):
            with self.subTest(payload=payload):
                envelope["payload"] = payload
                envelope["length"] = len(payload.encode())
                envelope["sha256"] = hashlib.sha256(payload.encode()).hexdigest()
                self.backend.blobs[name] = json.dumps(
                    envelope, sort_keys=True, separators=(",", ":"),
                ).encode()
                with self.assertRaises(IntegrityError):
                    self.execution.create("job", synthetic_plan(), "create")

    def test_missing_manifest_cannot_be_healed_by_create_replay(self):
        self.execution.create("job", synthetic_plan(), "create")
        name = next(name for name in self.backend.blobs if name.endswith("/manifest.json"))
        del self.backend.blobs[name]
        with self.assertRaises(IntegrityError):
            self.execution.create("job", synthetic_plan(), "create")

    def test_concurrent_create_conflicts_do_not_corrupt_winning_job(self):
        barrier = Barrier(2)

        def compete(name, data):
            if name.endswith("/manifest.json"):
                barrier.wait(timeout=10)

        self.backend.before_write = compete
        plans = (synthetic_plan(), replace(synthetic_plan(), profile_version="other-profile"))
        workers = [Execution(self.make_store(), self.model) for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(workers[i].create, "job", plans[i], f"create-{i}") for i in range(2)]
            results = []
            for future in futures:
                try:
                    results.append(future.result(timeout=10))
                except Conflict:
                    pass
        self.backend.before_write = lambda name, data: None
        self.assertEqual(len(results), 1)
        self.assertEqual(self.execution.read("job"), results[0])
        for i, plan in enumerate(plans):
            if plan != results[0].plan:
                with self.assertRaises(Conflict):
                    workers[i].create("job", plan, f"create-{i}")
        self.assertEqual(self.model.calls, [])

    def test_ledger_wide_request_reservation_arbitrates_different_jobs(self):
        barrier = Barrier(2)

        def compete(name, data):
            if "/requests/" in name:
                barrier.wait(timeout=10)

        self.backend.before_write = compete
        workers = [Execution(self.make_store(), self.model) for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(workers[i].create, f"job-{i}", synthetic_plan(), "create") for i in range(2)]
            results = []
            for future in futures:
                try:
                    results.append(future.result(timeout=10))
                except Conflict:
                    pass
        self.assertEqual(len(results), 1)
        winner = results[0]
        self.assertEqual(self.execution.read(winner.job_id), winner)
        loser_id = "job-1" if winner.job_id == "job-0" else "job-0"
        with self.assertRaises(NotFound):
            self.execution.read(loser_id)

    def test_corrupt_checkpoint_reference_shape_is_a_safe_integrity_error(self):
        for reference in (None, [], {"name": "incorrect"}, 1):
            with self.subTest(reference=reference):
                self.setUp()
                self.execution.create("job", synthetic_plan(), "create")
                name = next(name for name in self.backend.blobs if "/checkpoints/" in name)
                self.backend.rewrite(name, lambda marker: marker.update(snapshot=reference))
                with self.assertRaises(IntegrityError):
                    self.execution.read("job")
                self.assertEqual(self.model.calls, [])

    def test_oversized_result_retains_claim_and_cannot_repeat_model(self):
        from information_extraction.blob_store import MAX_BLOB_BYTES
        plan = synthetic_plan()
        block = replace(plan.chunks[0].blocks[0], text="x" * (MAX_BLOB_BYTES // 2))
        plan = replace(plan, chunks=(replace(plan.chunks[0], blocks=(block,)),))
        self.execution.create("job", plan, "create")
        with self.assertRaises(InvalidInput):
            self.execution.advance("job", 0, "advance")
        restored = Execution(self.make_store(), self.model)
        self.assertEqual(restored.read("job").status, Status.IN_PROGRESS)
        with self.assertRaises(Blocked):
            restored.advance("job", 0, "advance")
        self.assertEqual(len(self.model.calls), 1)

    def test_blob_changed_or_removed_between_properties_and_download_is_integrity_failure(self):
        self.execution.create("job", synthetic_plan(), "create")
        for error in (ResourceModifiedError("changed"), ResourceNotFoundError("removed")):
            with self.subTest(error=type(error).__name__):
                def fail_download(name):
                    raise error

                self.backend.before_download = fail_download
                with self.assertRaises(IntegrityError):
                    self.execution.read("job")
                self.assertEqual(self.model.calls, [])


for _name in (
    "test_handled_failure_requires_explicit_resume_preserves_progress_and_replays",
    "test_malformed_outputs_commit_safe_failure_with_known_usage",
    "test_invalid_inputs_reject_before_persistence_or_inference",
    "test_identity_conflicts_stale_revisions_and_binding_mismatch_do_not_call_model",
    "test_token_usage_keeps_unknown_distinct_from_zero_and_rejects_sdk_shapes",
    "test_invalid_provider_usage_is_handled_without_persisting_raw_values",
    "test_zero_candidates_still_commits_chunk_coverage_without_claiming_review",
    "test_malformed_response_envelope_and_later_record_do_not_publish_partial_candidates",
    "test_handled_provider_failure_does_not_assume_unknown_usage_is_zero",
    "test_two_workers_own_one_revision_without_holding_lock_during_inference",
    "test_unknown_exception_or_cancellation_propagates_and_retains_claim",
):
    setattr(BlobExecutionTests, _name, getattr(contract.ExecutionTests, _name))
