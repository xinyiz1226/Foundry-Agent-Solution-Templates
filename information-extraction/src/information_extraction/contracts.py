"""Frozen extraction contracts, including the unchanged legacy G0 wire shape."""

from dataclasses import asdict, dataclass
from enum import StrEnum
import json
import math
import re
from typing import Protocol


SCHEMA_VERSION = "financial-metrics-v1"


class ExecutionError(Exception):
    """Safe domain error; messages never include model responses or credentials."""


class InvalidInput(ExecutionError):
    pass


class Conflict(ExecutionError):
    pass


class StaleRevision(Conflict):
    pass


class Blocked(Conflict):
    pass


class NotFound(ExecutionError):
    pass


class IntegrityError(ExecutionError):
    pass


def validate_identifier(value: object) -> None:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is None:
        raise InvalidInput("invalid_identifier")


class Status(StrEnum):
    READY = "ready"
    IN_PROGRESS = "in_progress_or_interrupted"
    FAILED = "failed"
    COMPLETED = "completed"


class Action(StrEnum):
    ADVANCE = "advance"
    RESUME = "resume"


class ReviewStatus(StrEnum):
    PENDING = "pending"


class Metric(StrEnum):
    REVENUE = "revenue"
    OPERATING_INCOME = "operating_income"


class FailureCode(StrEnum):
    MODEL_TIMEOUT = "model_timeout"
    MODEL_REJECTED = "model_rejected"
    MALFORMED_OUTPUT = "malformed_output"
    INVALID_EVIDENCE = "invalid_evidence"
    INVALID_USAGE = "invalid_usage"


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int


class ModelFailure(ExecutionError):
    """Declared, safely resumable provider outcome; never pass raw exception text."""

    def __init__(self, code: FailureCode, usage: TokenUsage | None = None):
        if not isinstance(code, FailureCode) or code not in (
            FailureCode.MODEL_TIMEOUT, FailureCode.MODEL_REJECTED,
        ):
            raise InvalidInput("invalid_model_failure_code")
        super().__init__(code.value)
        self.code = code
        self.usage = usage


class ValidationFailure(ExecutionError):
    """A structurally invalid model response, not an arbitrary Python failure."""

    def __init__(self, code: FailureCode):
        if not isinstance(code, FailureCode) or code not in (
            FailureCode.MALFORMED_OUTPUT, FailureCode.INVALID_EVIDENCE, FailureCode.INVALID_USAGE,
        ):
            raise InvalidInput("invalid_validation_failure_code")
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True)
class Block:
    id: str
    text: str
    location: str

    def __post_init__(self):
        validate_identifier(self.id)
        if type(self.text) is not str or not self.text.strip():
            raise InvalidInput("empty_source_block")
        if type(self.location) is not str or not self.location.strip():
            raise InvalidInput("empty_source_location")


@dataclass(frozen=True)
class DialogueBlock(Block):
    speaker: str

    def __post_init__(self):
        super().__post_init__()
        validate_identifier(self.speaker)


class FieldType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ENUM = "enum"
    DATE = "date"


RESERVED_FIELDS = frozenset({
    "job_id", "document_id", "record_id", "candidate_id", "source_id", "chunk_id",
    "request_id", "revision", "plan_fingerprint", "review_status",
    "semantic_validation_performed", "evidence", "field_evidence", "block_ids",
    "configuration_version", "schema_version", "profile_version", "parser_version", "model_binding",
})
MAX_FIELDS = 32
MAX_TEXT_LENGTH = 4096
MIN_INTEGER = -(2**63)
MAX_INTEGER = 2**63 - 1
Scalar = str | int | float | bool | None


def _field_name(value: object) -> None:
    if (
        type(value) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) is None
        or value in RESERVED_FIELDS
    ):
        raise InvalidInput("invalid_or_reserved_field_name")


def _bounded_text(value: object, limit: int) -> bool:
    if type(value) is not str or not value.strip() or len(value) > limit:
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: FieldType
    description: str
    nullable: bool = False
    choices: tuple[str, ...] = ()
    date_format: str | None = None

    def __post_init__(self):
        _field_name(self.name)
        if (
            not isinstance(self.kind, FieldType) or type(self.nullable) is not bool
            or not _bounded_text(self.description, 512) or type(self.choices) is not tuple
        ):
            raise InvalidInput("invalid_field_specification")
        if self.kind == FieldType.ENUM:
            if (
                not 1 <= len(self.choices) <= 32
                or any(not _bounded_text(choice, 128) for choice in self.choices)
                or len(set(self.choices)) != len(self.choices)
            ):
                raise InvalidInput("invalid_enum_choices")
        elif self.choices:
            raise InvalidInput("choices_require_enum_field")
        if self.date_format != ("YYYY-MM-DD" if self.kind == FieldType.DATE else None):
            raise InvalidInput("unsupported_field_date_format")


@dataclass(frozen=True)
class RecordSchema:
    version: str
    fields: tuple[FieldSpec, ...]
    max_records: int = 50

    def __post_init__(self):
        validate_identifier(self.version)
        if (
            type(self.fields) is not tuple or not 1 <= len(self.fields) <= MAX_FIELDS
            or any(not isinstance(item, FieldSpec) for item in self.fields)
            or len({item.name for item in self.fields}) != len(self.fields)
        ):
            raise InvalidInput("invalid_schema_fields")
        if type(self.max_records) is not int or not 1 <= self.max_records <= 100:
            raise InvalidInput("invalid_schema_record_limit")


@dataclass(frozen=True)
class ExtractionProfile:
    version: str
    schema: RecordSchema
    instructions: str

    def __post_init__(self):
        validate_identifier(self.version)
        if not isinstance(self.schema, RecordSchema) or not _bounded_text(self.instructions, 8192):
            raise InvalidInput("invalid_extraction_profile")


@dataclass(frozen=True)
class Chunk:
    id: str
    blocks: tuple[Block, ...]

    def __post_init__(self):
        validate_identifier(self.id)
        if type(self.blocks) is not tuple or not self.blocks or any(
            not isinstance(block, Block) for block in self.blocks
        ):
            raise InvalidInput("invalid_chunk_blocks")
        if len({block.id for block in self.blocks}) != len(self.blocks):
            raise InvalidInput("duplicate_block_id")


@dataclass(frozen=True)
class Plan:
    document_id: str
    chunks: tuple[Chunk, ...]
    profile_version: str
    schema_version: str
    parser_version: str
    model_binding: str

    def __post_init__(self):
        self._validate_sources()
        if self.schema_version != SCHEMA_VERSION:
            raise InvalidInput("unsupported_schema_version")
        if any(isinstance(block, DialogueBlock) for chunk in self.chunks for block in chunk.blocks):
            raise InvalidInput("dialogue_blocks_require_configured_plan")

    def _validate_sources(self):
        for identifier in (
            self.document_id, self.profile_version, self.parser_version, self.model_binding,
        ):
            validate_identifier(identifier)
        if type(self.chunks) is not tuple or not self.chunks or any(
            not isinstance(chunk, Chunk) for chunk in self.chunks
        ):
            raise InvalidInput("invalid_plan_chunks")
        if len({chunk.id for chunk in self.chunks}) != len(self.chunks):
            raise InvalidInput("duplicate_chunk_id")
        block_ids = [block.id for chunk in self.chunks for block in chunk.blocks]
        if len(set(block_ids)) != len(block_ids):
            raise InvalidInput("duplicate_block_id")


@dataclass(frozen=True)
class ConfiguredPlan(Plan):
    profile: ExtractionProfile
    format_version: str = "configured-plan-v1"

    def __post_init__(self):
        self._validate_sources()
        if (
            type(self.format_version) is not str or self.format_version != "configured-plan-v1"
            or not isinstance(self.profile, ExtractionProfile)
            or self.profile_version != self.profile.version
            or self.schema_version != self.profile.schema.version
        ):
            raise InvalidInput("configured_plan_profile_mismatch")
        try:
            for chunk in self.chunks:
                for block in chunk.blocks:
                    block.text.encode("utf-8")
                    block.location.encode("utf-8")
        except UnicodeError:
            raise InvalidInput("invalid_source_unicode") from None
        if (
            len(self.chunks) > 16
            or len(json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False)) > 256 * 1024
        ):
            raise InvalidInput("configured_plan_size_limit_exceeded")


@dataclass(frozen=True)
class ModelRequest:
    job_id: str
    request_id: str
    revision: int
    chunk: Chunk
    plan: Plan


@dataclass(frozen=True)
class ModelResponse:
    payload: object
    usage: TokenUsage | None = None


class Model(Protocol):
    binding: str

    def complete(self, request: ModelRequest) -> ModelResponse: ...


@dataclass(frozen=True)
class Record:
    metric: Metric
    value: int | float
    unit: str


@dataclass(frozen=True)
class FieldValue:
    name: str
    value: Scalar

    def __post_init__(self):
        _field_name(self.name)
        valid = (
            self.value is None or type(self.value) is bool
            or (type(self.value) is str and _bounded_text(self.value, MAX_TEXT_LENGTH))
            or (type(self.value) is int and MIN_INTEGER <= self.value <= MAX_INTEGER)
            or (type(self.value) is float and math.isfinite(self.value))
        )
        if not valid:
            raise InvalidInput("invalid_flat_field_value")


@dataclass(frozen=True)
class FlatRecord:
    fields: tuple[FieldValue, ...]

    def __post_init__(self):
        if (
            type(self.fields) is not tuple or not 1 <= len(self.fields) <= MAX_FIELDS
            or any(not isinstance(item, FieldValue) for item in self.fields)
            or len({item.name for item in self.fields}) != len(self.fields)
        ):
            raise InvalidInput("invalid_flat_record")

    def to_dict(self) -> dict[str, Scalar]:
        return {item.name: item.value for item in self.fields}


@dataclass(frozen=True)
class FieldEvidence:
    name: str
    block_ids: tuple[str, ...]

    def __post_init__(self):
        _field_name(self.name)
        if (
            type(self.block_ids) is not tuple or any(type(item) is not str for item in self.block_ids)
            or len(set(self.block_ids)) != len(self.block_ids)
        ):
            raise InvalidInput("invalid_field_evidence")
        for block_id in self.block_ids:
            validate_identifier(block_id)


@dataclass(frozen=True)
class Evidence:
    document_id: str
    chunk_id: str
    block_id: str
    location: str
    text: str


@dataclass(frozen=True)
class Candidate:
    id: str
    job_id: str
    revision: int
    plan_fingerprint: str
    record: Record | FlatRecord
    evidence: tuple[Evidence, ...]
    review_status: ReviewStatus = ReviewStatus.PENDING
    semantic_validation_performed: bool = False


@dataclass(frozen=True)
class ConfiguredCandidate(Candidate):
    record: FlatRecord
    field_evidence: tuple[FieldEvidence, ...] = ()

    def __post_init__(self):
        if (
            not isinstance(self.record, FlatRecord) or type(self.field_evidence) is not tuple
            or any(not isinstance(item, FieldEvidence) for item in self.field_evidence)
            or tuple(item.name for item in self.field_evidence) != tuple(item.name for item in self.record.fields)
        ):
            raise InvalidInput("invalid_configured_candidate_fields")


@dataclass(frozen=True)
class Attempt:
    request_id: str
    revision: int
    chunk_id: str
    failure_code: FailureCode | None
    usage: TokenUsage | None
    covered_block_ids: tuple[str, ...]


@dataclass(frozen=True)
class Claim:
    request_id: str
    expected_revision: int
    action: Action
    chunk_id: str


@dataclass(frozen=True)
class Snapshot:
    job_id: str
    plan: Plan
    plan_fingerprint: str
    revision: int = 0
    status: Status = Status.READY
    completed_chunk_ids: tuple[str, ...] = ()
    attempts: tuple[Attempt, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    claim: Claim | None = None


class Store(Protocol):
    """Storage seam: claims precede inference; publication is all-or-nothing.

    Implementations must atomically arbitrate claims across workers, retain
    immutable claims/checkpoints and replay results, and never hold a lock
    while the caller invokes a model.
    """

    def create(self, job_id: str, plan: Plan, request_id: str) -> Snapshot: ...
    def read(self, job_id: str) -> Snapshot: ...
    def claim(
        self, job_id: str, expected_revision: int, request_id: str, action: Action
    ) -> Snapshot: ...
    def publish(self, claimed: Snapshot, result: Snapshot) -> Snapshot: ...


class ExecutionDriver(Protocol):
    """Shared batch seam for fixed-model and lazily selected profile models."""

    def read(self, job_id: str) -> Snapshot: ...
    def advance(
        self, job_id: str, expected_revision: int, request_id: str, *, action: Action = Action.ADVANCE,
    ) -> Snapshot: ...
