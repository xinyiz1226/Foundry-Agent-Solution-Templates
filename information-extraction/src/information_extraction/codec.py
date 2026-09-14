"""Standard-library canonical serialization shared by persistent stores."""

import hashlib
import json

from .contracts import (
    Action, Attempt, Block, Candidate, Chunk, Claim, Evidence, FailureCode,
    IntegrityError, Metric, Plan, Record, ReviewStatus, Snapshot, Status, TokenUsage,
)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _plan(value: dict) -> Plan:
    return Plan(
        **{key: item for key, item in value.items() if key != "chunks"},
        chunks=tuple(
            Chunk(chunk["id"], tuple(Block(**block) for block in chunk["blocks"]))
            for chunk in value["chunks"]
        ),
    )


def _snapshot(payload: str, digest: str) -> Snapshot:
    if _hash(payload) != digest:
        raise IntegrityError("checkpoint_digest_mismatch")
    data = json.loads(payload)
    return Snapshot(
        **{key: item for key, item in data.items()
           if key not in {"plan", "status", "completed_chunk_ids", "attempts", "candidates", "claim"}},
        plan=_plan(data["plan"]),
        status=Status(data["status"]),
        completed_chunk_ids=tuple(data["completed_chunk_ids"]),
        attempts=tuple(Attempt(
            **{key: item for key, item in attempt.items()
               if key not in {"failure_code", "usage", "covered_block_ids"}},
            failure_code=FailureCode(attempt["failure_code"]) if attempt["failure_code"] else None,
            usage=TokenUsage(**attempt["usage"]) if attempt["usage"] is not None else None,
            covered_block_ids=tuple(attempt["covered_block_ids"]),
        ) for attempt in data["attempts"]),
        candidates=tuple(Candidate(
            **{key: item for key, item in candidate.items()
               if key not in {"record", "evidence", "review_status"}},
            record=Record(**{**candidate["record"], "metric": Metric(candidate["record"]["metric"])}),
            evidence=tuple(Evidence(**evidence) for evidence in candidate["evidence"]),
            review_status=ReviewStatus(candidate["review_status"]),
        ) for candidate in data["candidates"]),
        claim=Claim(**{**data["claim"], "action": Action(data["claim"]["action"])})
        if data["claim"] is not None else None,
    )
