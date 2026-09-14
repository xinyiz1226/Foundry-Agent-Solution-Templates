"""Opt-in storage smoke using fictional data and a model that never uses a network."""

import argparse
from contextlib import ExitStack
from dataclasses import asdict
import json
import logging
import os
import re
from urllib.parse import urlsplit

from information_extraction import (
    Action, Execution, FailureCode, ModelFailure, ModelResponse, Status, TokenUsage,
)
from information_extraction.codec import _hash, _json
from information_extraction.contracts import ExecutionError, IntegrityError, InvalidInput
from information_extraction.sample import synthetic_plan


JOB_ID = "blob-smoke-job"
CREATE_REQUEST = "blob-smoke-create"


class SyntheticModel:
    binding = "synthetic-model-v1"

    def __init__(self):
        self.calls = 0
        self.inject_failure = False

    def complete(self, request):
        self.calls += 1
        if self.inject_failure:
            raise ModelFailure(FailureCode.MODEL_TIMEOUT)
        metric, value = (
            ("revenue", 120) if request.chunk.id == "chunk-1" else ("operating_income", 18)
        )
        return ModelResponse({"records": [{
            "metric": metric, "value": value, "unit": "USD_millions",
            "block_ids": [request.chunk.blocks[0].id],
        }]}, TokenUsage(0, 0))


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise InvalidInput("invalid_arguments")


def _arguments(argv):
    parser = SafeParser(description=__doc__)
    parser.add_argument("action", choices=("create", "advance", "inspect", "resume", "run"))
    parser.add_argument("--account-url", default=os.environ.get("BLOB_SMOKE_ACCOUNT_URL"))
    parser.add_argument("--container", default=os.environ.get("BLOB_SMOKE_CONTAINER"))
    parser.add_argument("--prefix", default=os.environ.get("BLOB_SMOKE_PREFIX"))
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--inject-failure", action="store_true")
    args = parser.parse_args(argv)
    if (
        not args.prefix or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", args.prefix) is None
        or (args.action in ("advance", "resume") and (
            args.expected_revision is None or args.expected_revision < 0
        ))
        or (args.action not in ("advance", "resume") and args.expected_revision is not None)
        or (args.inject_failure and (args.action != "advance" or args.expected_revision != 1))
    ):
        raise InvalidInput("invalid_arguments")
    return args


def _verify(snapshot):
    if snapshot.plan != synthetic_plan() or snapshot.job_id != JOB_ID:
        raise IntegrityError("non_synthetic_plan")
    for candidate in snapshot.candidates:
        metric, value, chunk = (
            ("revenue", 120, snapshot.plan.chunks[0])
            if candidate.record.metric == "revenue"
            else ("operating_income", 18, snapshot.plan.chunks[1])
        )
        block = chunk.blocks[0]
        if (
            candidate.record.metric != metric or candidate.record.value != value
            or candidate.record.unit != "USD_millions"
            or candidate.review_status != "pending" or candidate.semantic_validation_performed
            or len(candidate.evidence) != 1 or candidate.evidence[0].block_id != block.id
            or candidate.evidence[0].text != block.text or candidate.evidence[0].location != block.location
        ):
            raise IntegrityError("synthetic_evidence_mismatch")
    if snapshot.status == Status.COMPLETED and (
        snapshot.completed_chunk_ids != ("chunk-1", "chunk-2")
        or [candidate.record.value for candidate in snapshot.candidates] != [120, 18]
    ):
        raise IntegrityError("synthetic_completion_mismatch")


def _advance(execution, revision, *, resume=False):
    action = Action.RESUME if resume else Action.ADVANCE
    return execution.advance(
        JOB_ID, revision, f"blob-smoke-{action}-{revision}", action=action,
    )


def _execute(args, client):
    from information_extraction.blob_store import BlobStore

    model = SyntheticModel()
    execution = Execution(BlobStore(client, prefix=args.prefix), model)
    if args.action == "create":
        result = execution.create(JOB_ID, synthetic_plan(), CREATE_REQUEST)
    elif args.action == "inspect":
        result = execution.read(JOB_ID)
    elif args.action in ("advance", "resume"):
        _verify(execution.read(JOB_ID))
        model.inject_failure = args.inject_failure
        result = _advance(execution, args.expected_revision, resume=args.action == "resume")
    else:
        initial = execution.create(JOB_ID, synthetic_plan(), CREATE_REQUEST)
        _verify(execution.read(JOB_ID))
        first = _advance(execution, 0)
        model.inject_failure = True
        failed = _advance(execution, 1)
        if failed.status != Status.FAILED or failed.candidates != first.candidates:
            raise IntegrityError("expected_synthetic_failure_missing")
        model.inject_failure = False
        result = _advance(execution, 2, resume=True)
        for snapshot in (initial, first, failed, result):
            _verify(snapshot)
        calls = model.calls
        if (
            initial.revision != 0 or first.revision != 1 or failed.revision != 2
            or result.revision != 3 or result.status != Status.COMPLETED
            or result.candidates[0] != first.candidates[0]
            or execution.read(JOB_ID) != result
            or execution.create(JOB_ID, synthetic_plan(), CREATE_REQUEST) != initial
            or _advance(execution, 0) != first or _advance(execution, 1) != failed
            or _advance(execution, 2, resume=True) != result or calls != model.calls
        ):
            raise IntegrityError("synthetic_replay_mismatch")
    _verify(result)
    output = {
        "evidence": "synthetic-storage-only",
        "action": args.action,
        "status": result.status,
        "revision": result.revision,
        "attempt_count": len(result.attempts),
        "completed_chunk_count": len(result.completed_chunk_ids),
        "model_calls": model.calls,
        "plan_sha256": result.plan_fingerprint,
        "snapshot_sha256": _hash(_json(asdict(result))),
        "candidates": [{
            "metric": candidate.record.metric, "value": candidate.record.value,
            "unit": candidate.record.unit, "review_status": candidate.review_status,
            "evidence_text": candidate.evidence[0].text,
            "evidence_location": candidate.evidence[0].location,
        } for candidate in result.candidates],
    }
    unsafe = result.status in (Status.FAILED, Status.IN_PROGRESS)
    partial_inspection = args.action in ("inspect", "run") and result.status != Status.COMPLETED
    return output, 1 if unsafe or partial_inspection else 0


def main(argv=None, *, credential=None, container_client=None):
    """Caller-injected credentials/clients stay caller-owned; default is Azure CLI only."""
    try:
        args = _arguments(argv)
        if container_client is None:
            try:
                url = urlsplit(args.account_url or "")
            except ValueError as error:
                raise InvalidInput("invalid_account_url") from error
            if (
                url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path not in ("", "/")
                or not args.container
                or re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", args.container) is None
                or "--" in args.container
            ):
                raise InvalidInput("invalid_storage_arguments")
        try:
            from azure.core.exceptions import AzureError
            from azure.identity import AzureCliCredential
            from azure.storage.blob import ContainerClient
        except ImportError:
            print(json.dumps({"error": "optional_azure_dependencies_required"}))
            return 2
        # SDK diagnostics can include endpoints. This command emits only its safe projection.
        logging.getLogger("azure").setLevel(logging.CRITICAL)
        try:
            with ExitStack() as stack:
                if container_client is None:
                    if credential is None:
                        credential = stack.enter_context(AzureCliCredential())
                    container_client = stack.enter_context(ContainerClient(
                        args.account_url, args.container, credential=credential,
                        retry_total=0, logging_enable=False,
                    ))
                output, code = _execute(args, container_client)
        except AzureError:
            print(json.dumps({"error": "storage_request_failed"}))
            return 2
        print(json.dumps(output, sort_keys=True))
        return code
    except ExecutionError:
        print(json.dumps({"error": "validation_or_execution_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
