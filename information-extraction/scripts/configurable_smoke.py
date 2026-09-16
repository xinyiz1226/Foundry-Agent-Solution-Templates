"""Fixture-only offline rehearsal: predetermined responses, never a real extractor."""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

from information_extraction import Execution, SQLiteStore
from information_extraction.abcd import import_abcd
from information_extraction.contracts import (
    Action, Chunk, ConfiguredPlan, Conflict, DialogueBlock, ExecutionError, FailureCode,
    ModelFailure, ModelRequest, ModelResponse, NotFound, ReviewStatus, Status, TokenUsage,
)
from information_extraction.profiles import FINANCIAL_PROFILE, SUPPORT_PROFILE
from information_extraction.sample import synthetic_plan


MODEL_BINDING = "offline-configurable-fixture-v1"
NAMESPACE = "configurable-fixture-v1"
DATABASE_NAME = "configurable-fixture-v1.sqlite3"
FINANCIAL_JOB = f"{NAMESPACE}:financial"
SUPPORT_JOBS = tuple(f"{NAMESPACE}:support:{number}" for number in (900001, 900002))
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "samples" / "abcd-format-synthetic.json"
FINANCIAL_SOURCE_DIGEST = "84cff48e73daeba8c094ef05c33045cb643449541fe66b115c7dd884fc1ff858"
ABCD_SOURCE_DIGEST = "9667393b5d544c9aad4cc049ce27063d9af82b7f074d9b152c029365f4f8e6d7"


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ExecutionError(code)


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fixture_plans() -> dict[str, ConfiguredPlan]:
    """Only these pinned repository-owned sources can enter the fixture model."""
    financial = synthetic_plan()
    _require(_digest(asdict(financial)) == FINANCIAL_SOURCE_DIGEST,
             "financial_fixture_source_changed")
    payload = FIXTURE_PATH.read_bytes()
    _require(_digest(json.loads(payload)) == ABCD_SOURCE_DIGEST, "abcd_fixture_source_changed")
    sources = import_abcd(payload, split="train")
    _require(tuple(source.conversation_id for source in sources) == (900001, 900002),
             "abcd_fixture_conversations_changed")
    plans = {
        FINANCIAL_JOB: ConfiguredPlan(
            document_id=financial.document_id, chunks=financial.chunks,
            profile_version=FINANCIAL_PROFILE.version,
            schema_version=FINANCIAL_PROFILE.schema.version,
            parser_version=financial.parser_version, model_binding=MODEL_BINDING,
            profile=FINANCIAL_PROFILE,
        ),
    }
    for job, source in zip(SUPPORT_JOBS, sources, strict=True):
        blocks = tuple(
            DialogueBlock(
                id=turn.block.id, text=turn.block.text, location=turn.block.location,
                speaker=turn.speaker,
            )
            for turn in source.turns
        )
        plans[job] = ConfiguredPlan(
            document_id=source.document_id,
            chunks=(Chunk("conversation", blocks),),
            profile_version=SUPPORT_PROFILE.version, schema_version=SUPPORT_PROFILE.schema.version,
            parser_version=source.parser_version, model_binding=MODEL_BINDING,
            profile=SUPPORT_PROFILE,
        )
    return plans


def _financial_record(metric: str, value: int, block: str) -> dict:
    return {
        "fields": {"metric": metric, "value": value, "unit": "USD_millions"},
        "evidence": {field: [block] for field in ("metric", "value", "unit")},
    }


def _support_records() -> tuple[dict, dict]:
    return (
        {
            "fields": {
                "customer_issue_or_request": "The desk lamp does not switch on; a replacement is requested.",
                "product_or_service": "desk lamp",
                "attempted_action": "Tried another wall socket.",
                "stated_outcome": "The replacement request was recorded but has not been approved yet.",
                "outcome_status": "pending",
            },
            "evidence": {
                "customer_issue_or_request": ["turn-1"],
                "product_or_service": ["turn-1"],
                "attempted_action": ["turn-3"],
                "stated_outcome": ["turn-5"],
                "outcome_status": ["turn-5"],
            },
        },
        {
            "fields": {
                "customer_issue_or_request": "How to find the care instructions for the chair.",
                "product_or_service": "chair",
                "attempted_action": None,
                "stated_outcome": "The customer found the guide and reports no problem with the chair.",
                "outcome_status": "resolved",
            },
            "evidence": {
                "customer_issue_or_request": ["turn-1"],
                "product_or_service": ["turn-1"],
                "attempted_action": [],
                "stated_outcome": ["turn-3"],
                "outcome_status": ["turn-2", "turn-3"],
            },
        },
    )


@dataclass(frozen=True)
class _Step:
    job: str
    revision: int
    request_id: str
    chunk_id: str
    action: Action
    record: dict | None


def _steps() -> tuple[_Step, ...]:
    support = _support_records()
    return (
        _Step(FINANCIAL_JOB, 0, f"{FINANCIAL_JOB}:advance:1", "chunk-1", Action.ADVANCE,
              _financial_record("revenue", 120, "block-1")),
        _Step(FINANCIAL_JOB, 1, f"{FINANCIAL_JOB}:timeout:2", "chunk-2", Action.ADVANCE, None),
        _Step(FINANCIAL_JOB, 2, f"{FINANCIAL_JOB}:resume:3", "chunk-2", Action.RESUME,
              _financial_record("operating_income", 18, "block-3")),
        *(
            _Step(job, 0, f"{job}:advance:1", "conversation", Action.ADVANCE, record)
            for job, record in zip(SUPPORT_JOBS, support, strict=True)
        ),
    )


class ScriptedFixtureModel:
    """A strict response script, not a heuristic or model-accuracy demonstration."""

    binding = MODEL_BINDING

    def __init__(self, *, forbid_calls: bool = False):
        self.calls = 0
        self._forbid_calls = forbid_calls
        self._plans = fixture_plans()
        self._steps = {step.request_id: step for step in _steps()}
        self._seen: set[str] = set()

    def complete(self, request: ModelRequest) -> ModelResponse:
        _require(not self._forbid_calls, "replay_attempted_fixture_call")
        step = self._steps.get(request.request_id)
        _require(step is not None, "unsupported_fixture_request")
        plan = self._plans[step.job]
        chunk = next(chunk for chunk in plan.chunks if chunk.id == step.chunk_id)
        _require(request == ModelRequest(step.job, step.request_id, step.revision, chunk, plan),
                 "unsupported_fixture_plan_or_request")
        _require(request.request_id not in self._seen, "duplicate_fixture_call")
        self._seen.add(request.request_id)
        self.calls += 1
        if step.record is None:
            raise ModelFailure(FailureCode.MODEL_TIMEOUT)
        # Return a fresh object so callers cannot modify the frozen response script.
        payload = json.loads(json.dumps({"records": [step.record]}))
        return ModelResponse(payload, TokenUsage(10, 5))


def _verify_candidates(snapshot, expected: tuple[dict, ...]) -> None:
    _require(len(snapshot.candidates) == len(expected), "fixture_record_count_mismatch")
    blocks = {
        block.id: (chunk.id, block)
        for chunk in snapshot.plan.chunks for block in chunk.blocks
    }
    for candidate, record in zip(snapshot.candidates, expected, strict=True):
        _require(candidate.record.to_dict() == record["fields"], "fixture_fields_mismatch")
        _require(candidate.review_status == ReviewStatus.PENDING
                 and candidate.semantic_validation_performed is False,
                 "fixture_review_state_mismatch")
        actual = {item.name: list(item.block_ids) for item in candidate.field_evidence}
        _require(actual == record["evidence"], "fixture_field_evidence_mismatch")
        expected_ids = {block_id for ids in actual.values() for block_id in ids}
        _require({item.block_id for item in candidate.evidence} == expected_ids
                 and len(candidate.evidence) == len(expected_ids),
                 "fixture_source_evidence_mismatch")
        for evidence in candidate.evidence:
            chunk_id, block = blocks[evidence.block_id]
            _require(
                evidence.document_id == snapshot.plan.document_id
                and evidence.chunk_id == chunk_id
                and evidence.text == block.text and evidence.location == block.location,
                "fixture_original_evidence_mismatch",
            )


def run_smoke(state_dir: str | Path) -> dict:
    """Persist/replay the exact same script; never delete or reset an existing ledger."""
    plans = fixture_plans()
    directory = Path(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    database = directory / DATABASE_NAME
    store = SQLiteStore(database)
    for job, plan in plans.items():
        try:
            existing = store.read(job)
        except NotFound:
            continue
        if existing.plan != plan:
            raise Conflict("incompatible_existing_fixture_configuration")
        job_steps = tuple(step for step in _steps() if step.job == job)
        if (
            existing.claim is not None
            or existing.revision != len(existing.attempts)
            or existing.revision > len(job_steps)
        ):
            raise Conflict("incompatible_existing_fixture_history")
        for attempt, step in zip(existing.attempts, job_steps):
            expected_failure = FailureCode.MODEL_TIMEOUT if step.record is None else None
            if (
                attempt.request_id != step.request_id
                or attempt.revision != step.revision + 1
                or attempt.chunk_id != step.chunk_id
                or attempt.failure_code != expected_failure
            ):
                raise Conflict("incompatible_existing_fixture_history")
    model = ScriptedFixtureModel()
    execution = Execution(store, model)
    created = {
        job: execution.create(job, plan, f"{job}:create")
        for job, plan in plans.items()
    }
    _require(all(snapshot.revision == 0 for snapshot in created.values()),
             "incompatible_existing_fixture_history")
    history = []
    for step in _steps():
        result = execution.advance(
            step.job, step.revision, step.request_id, action=step.action,
        )
        _require(result.revision == step.revision + 1, "fixture_revision_mismatch")
        if step.record is None:
            _require(
                result.status == Status.FAILED
                and result.attempts[-1].failure_code == FailureCode.MODEL_TIMEOUT
                and result.completed_chunk_ids == ("chunk-1",),
                "fixture_handled_failure_mismatch",
            )
            _verify_candidates(result, (_steps()[0].record,))
            if execution.read(step.job) == result:
                try:
                    execution.advance(step.job, result.revision, f"{step.job}:advance-without-resume")
                except Conflict as error:
                    _require(str(error) == "explicit_resume_required_or_not_applicable",
                             "fixture_resume_guard_mismatch")
                else:
                    raise ExecutionError("fixture_missing_explicit_resume_guard")
        history.append(result)
    expected = {
        FINANCIAL_JOB: (_steps()[0].record, _steps()[2].record),
        SUPPORT_JOBS[0]: (_support_records()[0],),
        SUPPORT_JOBS[1]: (_support_records()[1],),
    }
    final = {}
    for job in plans:
        snapshot = execution.read(job)
        _require(snapshot.status == Status.COMPLETED, "fixture_incomplete")
        _verify_candidates(snapshot, expected[job])
        final[job] = snapshot
    calls_before_replay = model.calls
    for step, historical in zip(_steps(), history, strict=True):
        _require(
            execution.advance(step.job, step.revision, step.request_id, action=step.action)
            == historical, "fixture_historical_replay_mismatch",
        )
    _require(model.calls == calls_before_replay, "fixture_replay_added_calls")
    reopened_model = ScriptedFixtureModel(forbid_calls=True)
    reopened = Execution(SQLiteStore(database), reopened_model)
    for job, plan in plans.items():
        _require(reopened.read(job) == final[job], "fixture_durable_reopen_mismatch")
        _require(reopened.create(job, plan, f"{job}:create") == created[job],
                 "fixture_create_replay_mismatch")
    for step, historical in zip(_steps(), history, strict=True):
        _require(
            reopened.advance(step.job, step.revision, step.request_id, action=step.action)
            == historical, "fixture_reopened_replay_mismatch",
        )
    return {
        "mode": "offline-scripted-fixture-only",
        "model_binding": MODEL_BINDING,
        "synthetic_model_calls": model.calls,
        "real_model_calls": 0,
        "semantic_validation_performed": False,
        "review_status": "pending",
        "handled_failure": "model_timeout",
        "explicit_resume_verified": True,
        "historical_replay_verified": True,
        "durable_reopen_verified": True,
        "replay_model_calls": model.calls - calls_before_replay + reopened_model.calls,
        "domains": {
            "financial": {
                "documents": 1, "records": len(final[FINANCIAL_JOB].candidates),
                "revisions": [final[FINANCIAL_JOB].revision],
            },
            "support": {
                "documents": len(SUPPORT_JOBS),
                "records": sum(len(final[job].candidates) for job in SUPPORT_JOBS),
                "revisions": [final[job].revision for job in SUPPORT_JOBS],
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path(".local-data") / "configurable-smoke")
    args = parser.parse_args(argv)
    try:
        result = run_smoke(args.state_dir)
    except ExecutionError as error:
        print(json.dumps({"error": str(error), "mode": "offline-scripted-fixture-only"}))
        return 1
    except (OSError, sqlite3.Error, ValueError):
        print(json.dumps({"error": "fixture_source_or_storage_unavailable",
                          "mode": "offline-scripted-fixture-only"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
