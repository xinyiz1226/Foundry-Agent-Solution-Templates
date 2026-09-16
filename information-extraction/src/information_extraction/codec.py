"""Standard-library canonical serialization shared by persistent stores."""

import hashlib
import json

from .contracts import (
    Action, Attempt, Block, Candidate, Chunk, Claim, ConfiguredCandidate, ConfiguredPlan,
    DialogueBlock, Evidence, FailureCode, FieldEvidence, FieldValue, FlatRecord,
    IntegrityError, Metric, Plan, Record, ReviewStatus, Snapshot, Status, TokenUsage,
)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _plan(value: dict) -> Plan:
    chunks = tuple(
        Chunk(chunk["id"], tuple(
            DialogueBlock(**block) if "speaker" in block else Block(**block) for block in chunk["blocks"]
        ))
        for chunk in value["chunks"]
    )
    if "profile" in value:
        from .schema import profile_from_dict

        return ConfiguredPlan(
            **{key: item for key, item in value.items() if key not in {"chunks", "profile"}},
            chunks=chunks, profile=profile_from_dict(value["profile"]),
        )
    return Plan(**{key: item for key, item in value.items() if key != "chunks"}, chunks=chunks)


def _candidate(value: dict, plan: Plan) -> Candidate:
    common = {
        **{key: item for key, item in value.items() if key not in {
            "record", "evidence", "review_status", "field_evidence",
        }},
        "evidence": tuple(Evidence(**item) for item in value["evidence"]),
        "review_status": ReviewStatus(value["review_status"]),
    }
    if isinstance(plan, ConfiguredPlan):
        return ConfiguredCandidate(
            **common, record=FlatRecord(**{
                **value["record"], "fields": tuple(FieldValue(**item) for item in value["record"]["fields"]),
            }),
            field_evidence=tuple(
                FieldEvidence(**{**item, "block_ids": tuple(item["block_ids"])}) for item in value["field_evidence"]
            ),
        )
    if "field_evidence" in value:
        raise IntegrityError("legacy_candidate_format_mismatch")
    return Candidate(**common, record=Record(**{**value["record"], "metric": Metric(value["record"]["metric"])}))


def _snapshot(payload: str, digest: str) -> Snapshot:
    if _hash(payload) != digest:
        raise IntegrityError("checkpoint_digest_mismatch")
    data = json.loads(payload)
    plan = _plan(data["plan"])
    return Snapshot(
        **{key: item for key, item in data.items()
           if key not in {"plan", "status", "completed_chunk_ids", "attempts", "candidates", "claim"}},
        plan=plan,
        status=Status(data["status"]),
        completed_chunk_ids=tuple(data["completed_chunk_ids"]),
        attempts=tuple(Attempt(
            **{key: item for key, item in attempt.items()
               if key not in {"failure_code", "usage", "covered_block_ids"}},
            failure_code=FailureCode(attempt["failure_code"]) if attempt["failure_code"] else None,
            usage=TokenUsage(**attempt["usage"]) if attempt["usage"] is not None else None,
            covered_block_ids=tuple(attempt["covered_block_ids"]),
        ) for attempt in data["attempts"]),
        candidates=tuple(_candidate(candidate, plan) for candidate in data["candidates"]),
        claim=Claim(**{**data["claim"], "action": Action(data["claim"]["action"])})
        if data["claim"] is not None else None,
    )
