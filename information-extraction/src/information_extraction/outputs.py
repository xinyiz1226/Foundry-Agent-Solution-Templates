"""Select the frozen wire format, never a business domain, for output validation."""

from .contracts import (
    Candidate, Chunk, ConfiguredCandidate, ConfiguredPlan, Conflict, Snapshot, ValidationFailure,
)
from .legacy_financial import resolve as resolve_legacy, valid_record as valid_legacy_record
from .schema import configured_candidates


def resolve_candidates(claimed: Snapshot, chunk: Chunk, payload: object) -> tuple[Candidate, ...]:
    if isinstance(claimed.plan, ConfiguredPlan):
        return configured_candidates(claimed, chunk, payload)
    return resolve_legacy(claimed, chunk, payload)


def validate_published_records(claimed: Snapshot, chunk: Chunk, candidates: tuple[Candidate, ...]) -> None:
    if not isinstance(claimed.plan, ConfiguredPlan):
        if any(not valid_legacy_record(candidate.record) for candidate in candidates):
            raise Conflict("publication_candidate_conflict")
        return
    if any(not isinstance(candidate, ConfiguredCandidate) for candidate in candidates):
        raise Conflict("publication_candidate_conflict")
    records = []
    for candidate in candidates:
        if not isinstance(candidate, ConfiguredCandidate):
            raise Conflict("publication_candidate_conflict")
        records.append({
            "fields": candidate.record.to_dict(),
            "evidence": {item.name: list(item.block_ids) for item in candidate.field_evidence},
        })
    payload = {"records": records}
    try:
        expected = configured_candidates(claimed, chunk, payload)
    except ValidationFailure:
        raise Conflict("publication_candidate_conflict") from None
    if expected != candidates:
        raise Conflict("publication_candidate_conflict")
