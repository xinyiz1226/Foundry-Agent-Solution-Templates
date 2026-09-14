"""Explicit one-step developer smoke path; never a background or batch driver."""

import argparse
from dataclasses import asdict, replace
import json
import logging
import os
from pathlib import Path
import sqlite3

from information_extraction import Action, Execution, SQLiteStore, Status
from information_extraction.contracts import ExecutionError, InvalidInput, Snapshot, validate_identifier
from information_extraction.sample import synthetic_plan


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise InvalidInput("invalid_arguments")


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--action", required=True, choices=("create", "inspect", "advance", "resume"))
    parser.add_argument("--project-endpoint", default=os.environ.get("FOUNDRY_PROJECT_ENDPOINT"))
    parser.add_argument("--deployment", default=os.environ.get("FOUNDRY_MODEL_DEPLOYMENT"))
    parser.add_argument("--ledger", type=Path, default=Path(".local-data") / "model-smoke.sqlite3")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--request-id")
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--reasoning-effort")
    args = parser.parse_args(argv)
    validate_identifier(args.job_id)
    if args.action != "inspect":
        validate_identifier(args.request_id)
    if args.action in ("advance", "resume") and (
        args.expected_revision is None or args.expected_revision < 0
    ):
        raise InvalidInput("expected_revision_required")
    return args


def _check_fixture(snapshot: Snapshot) -> None:
    if snapshot.plan != replace(synthetic_plan(), model_binding=snapshot.plan.model_binding):
        raise InvalidInput("non_synthetic_plan")


def _summary(snapshot: Snapshot) -> dict:
    _check_fixture(snapshot)
    known = [attempt.usage for attempt in snapshot.attempts if attempt.usage is not None]
    return {
        "status": snapshot.status.value,
        "revision": snapshot.revision,
        "failure_code": (
            snapshot.attempts[-1].failure_code.value
            if snapshot.attempts and snapshot.attempts[-1].failure_code else None
        ),
        "completed_chunk_count": len(snapshot.completed_chunk_ids),
        "chunk_count": len(snapshot.plan.chunks),
        "attempt_count": len(snapshot.attempts),
        "candidate_count": len(snapshot.candidates),
        "usage": {
            "known_input_tokens": sum(usage.input_tokens for usage in known),
            "known_output_tokens": sum(usage.output_tokens for usage in known),
            "unknown_attempts": len(snapshot.attempts) - len(known),
            "unresolved_attempts": int(snapshot.claim is not None),
        },
        "candidates": [{
            "record": asdict(candidate.record),
            "evidence": [asdict(evidence) for evidence in candidate.evidence],
            "review_status": candidate.review_status.value,
            "semantic_validation_performed": candidate.semantic_validation_performed,
        } for candidate in snapshot.candidates],
    }


def _run(args: argparse.Namespace) -> Snapshot:
    if args.action != "create" and not args.ledger.is_file():
        raise InvalidInput("ledger_not_found")
    if args.action == "inspect":
        return SQLiteStore(args.ledger).read(args.job_id)

    try:
        from information_extraction.foundry_model import FoundrySettings, open_foundry_model
        from azure.core.exceptions import ClientAuthenticationError
        from azure.identity import AzureCliCredential
    except ImportError:
        raise InvalidInput("azure_extra_required") from None

    settings = FoundrySettings(
        project_endpoint=args.project_endpoint, deployment=args.deployment,
        max_output_tokens=args.max_output_tokens, timeout=args.timeout,
        reasoning_effort=args.reasoning_effort,
    )
    if args.action == "create":
        args.ledger.parent.mkdir(parents=True, exist_ok=True)
        return SQLiteStore(args.ledger).create(
            args.job_id, replace(synthetic_plan(), model_binding=settings.binding), args.request_id,
        )

    store = SQLiteStore(args.ledger)
    _check_fixture(store.read(args.job_id))
    # Explicit CLI identity only; no default credential chain or key fallback.
    with AzureCliCredential() as credential:
        try:
            credential.get_token("https://ai.azure.com/.default")
        except ClientAuthenticationError:
            raise InvalidInput("azure_login_required_or_denied") from None
        with open_foundry_model(settings, credential) as model:
            return Execution(store, model).advance(
                args.job_id, args.expected_revision, args.request_id,
                action=Action.RESUME if args.action == "resume" else Action.ADVANCE,
            )


def main(argv: list[str] | None = None) -> int:
    # Provider SDK debug logs can contain private URLs, headers, and source text.
    logging.disable(logging.CRITICAL)
    try:
        snapshot = _run(_arguments(argv))
        print(json.dumps(_summary(snapshot), allow_nan=False))
        return 1 if snapshot.status in (Status.FAILED, Status.IN_PROGRESS) else 0
    except ExecutionError as error:
        print(json.dumps({"error": str(error)}))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"error": "interrupted_inspect_before_any_retry"}))
        return 130
    except (OSError, sqlite3.Error):
        print(json.dumps({"error": "local_storage_error_inspect_before_any_retry"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
