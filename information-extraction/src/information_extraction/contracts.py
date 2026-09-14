"""Frozen contracts for the fixed, pre-normalized G0 financial sample."""

from dataclasses import dataclass
from enum import StrEnum
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
        for identifier in (
            self.document_id, self.profile_version, self.parser_version, self.model_binding,
        ):
            validate_identifier(identifier)
        if self.schema_version != SCHEMA_VERSION:
            raise InvalidInput("unsupported_schema_version")
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
    record: Record
    evidence: tuple[Evidence, ...]
    review_status: ReviewStatus = ReviewStatus.PENDING
    semantic_validation_performed: bool = False


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
