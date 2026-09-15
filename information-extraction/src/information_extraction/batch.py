"""Durable bounded authorization rounds, independent of the task host.

Deadlines bound admission, not provider cancellation. No total-token or billed
cost guarantee is supported. Only committed Execution outcomes permit resume.
"""

from dataclasses import asdict, dataclass
from enum import StrEnum
import json
import math
import time
from typing import Callable, Protocol

from .codec import _hash, _json, _snapshot
from .contracts import (
    Action, Blocked, Conflict, ExecutionError, InvalidInput, NotFound, Snapshot, Status,
    validate_identifier,
)
from .execution import Execution


@dataclass(frozen=True)
class BatchLimits:
    max_attempts: int = 5
    deadline: float = 0.0

    def __post_init__(self):
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 5:
            raise InvalidInput("batch_attempt_limit_must_be_1_to_5")
        if (
            type(self.deadline) not in (int, float)
            or not math.isfinite(self.deadline) or self.deadline <= 0
        ):
            raise InvalidInput("invalid_batch_deadline")


@dataclass(frozen=True)
class Authorization:
    run_id: str
    job_id: str
    request_id: str
    plan_fingerprint: str
    expected_revision: int
    limits: BatchLimits
    previous_run_id: str | None = None


class BatchState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    LIMITED = "limited"
    BLOCKED = "in_progress_or_interrupted"


@dataclass(frozen=True)
class BatchStatus:
    authorization: Authorization
    state: BatchState
    snapshot: Snapshot
    attempts_reserved: int = 0
    registration_confirmed: bool = False

    @property
    def known_input_tokens(self) -> int:
        return sum(usage.input_tokens for usage in self._known_usage())

    @property
    def known_output_tokens(self) -> int:
        return sum(usage.output_tokens for usage in self._known_usage())

    @property
    def unknown_usage_attempts(self) -> int:
        return self.attempts_reserved - len(self._known_usage())

    def _known_usage(self):
        start = self.authorization.expected_revision
        return tuple(
            attempt.usage for attempt in self.snapshot.attempts[start:start + self.attempts_reserved]
            if attempt.usage is not None
        )


class BatchRecords(Protocol):
    """Create-only, durable, atomic winner selection; reads verify integrity."""

    def read_batch_record(self, key: str) -> str | None: ...
    def create_batch_record(self, key: str, payload: str) -> str: ...


class Scheduler(Protocol):
    async def schedule(self, run_id: str) -> None: ...


class RegistrationUnknown(ExecutionError):
    """Saved intent may already be running; repeat the identical start/resume."""

    def __init__(self, authorization: Authorization):
        super().__init__("batch_registration_unknown")
        self.authorization = authorization


class Batch:
    def __init__(
        self, execution: Execution, records: BatchRecords, scheduler: Scheduler,
        *, clock: Callable[[], float] = time.time,
    ):
        self.execution = execution
        self.records = records
        self.scheduler = scheduler
        self.clock = clock

    def _key(self, *parts: object) -> str:
        return _hash(_json(parts))

    @staticmethod
    def _storage[T](operation: Callable[[], T]) -> T:
        try:
            return operation()
        except ExecutionError:
            raise
        except Exception:
            raise ExecutionError("batch_storage_unavailable") from None

    def _read_execution(self, job_id: str) -> Snapshot:
        return self._storage(lambda: self.execution.read(job_id))

    def _read(self, *parts: object) -> dict | None:
        value = self._storage(lambda: self.records.read_batch_record(self._key(*parts)))
        return None if value is None else json.loads(value)

    def _put(self, value: dict, *parts: object) -> dict:
        return json.loads(self._storage(
            lambda: self.records.create_batch_record(self._key(*parts), _json(value)),
        ))

    def _authorization(self, run_id: str) -> Authorization:
        validate_identifier(run_id)
        value = self._read("authorization", run_id)
        if value is None:
            raise NotFound("batch_not_found")
        return Authorization(**{**value, "limits": BatchLimits(**value["limits"])})

    async def start(
        self, job_id: str, expected_revision: int, request_id: str, limits: BatchLimits,
    ) -> Authorization:
        return await self._authorize(job_id, expected_revision, request_id, limits)

    async def resume(
        self, previous_run_id: str, expected_revision: int, request_id: str, limits: BatchLimits,
    ) -> Authorization:
        previous = self.status(previous_run_id)
        if previous.state not in (BatchState.FAILED, BatchState.LIMITED):
            raise Conflict("batch_not_safely_resumable")
        if previous.snapshot.revision != expected_revision:
            raise Conflict("batch_resume_revision_conflict")
        return await self._authorize(
            previous.authorization.job_id, expected_revision, request_id, limits, previous_run_id,
        )

    def _owner_key(self, run: Authorization) -> tuple[str, str]:
        return ("next", run.previous_run_id) if run.previous_run_id else ("root", run.job_id)

    async def _authorize(
        self, job_id: str, expected_revision: int, request_id: str, limits: BatchLimits,
        previous_run_id: str | None = None,
    ) -> Authorization:
        validate_identifier(job_id)
        validate_identifier(request_id)
        if type(expected_revision) is not int or expected_revision < 0:
            raise InvalidInput("invalid_expected_revision")
        if not isinstance(limits, BatchLimits):
            raise InvalidInput("invalid_batch_limits")
        snapshot = self._read_execution(job_id)
        run = Authorization(
            self._key("run", request_id), job_id, request_id,
            snapshot.plan_fingerprint, expected_revision, limits, previous_run_id,
        )
        saved = self._read("authorization", run.run_id)
        if saved is not None:
            if saved != asdict(run):
                raise Conflict("batch_request_identity_conflict")
        else:
            allowed = (Status.READY, Status.FAILED) if previous_run_id else (Status.READY,)
            if snapshot.revision != expected_revision or snapshot.status not in allowed:
                raise Conflict("batch_start_requires_ready_revision")
            if not self.clock() < limits.deadline <= self.clock() + 604800:
                raise InvalidInput("batch_deadline_must_be_within_seven_days")
            saved = self._put(asdict(run), "authorization", run.run_id)
            if saved != asdict(run):
                raise Conflict("batch_request_identity_conflict")
        owner = self._put({"run_id": run.run_id}, *self._owner_key(run))
        if owner["run_id"] != run.run_id:
            raise Conflict("batch_round_already_authorized")
        if (
            self._read("registered", run.run_id) is None
            or self.status(run.run_id).state in (BatchState.QUEUED, BatchState.RUNNING)
        ):
            try:
                await self.scheduler.schedule(run.run_id)
                self._put({"confirmed": True}, "registered", run.run_id)
            except Exception:
                # External scheduler failures never imply that registration failed.
                raise RegistrationUnknown(run) from None
        return run

    def status(self, run_id: str) -> BatchStatus:
        run = self._authorization(run_id)
        reserved = 0
        for index in range(run.limits.max_attempts + 1):
            step = self._read("step", run_id, index)
            if step is None:
                break
            if step["kind"] == "terminal":
                return BatchStatus(
                    run, BatchState(step["state"]), self._decode_snapshot(step["snapshot"]),
                    reserved, self._read("registered", run_id) is not None,
                )
            reserved += 1
        snapshot = self._read_execution(run.job_id)
        unresolved_expired = (
            reserved > 0 and snapshot.revision < run.expected_revision + reserved
            and self.clock() >= run.limits.deadline
        )
        return BatchStatus(
            run, BatchState.BLOCKED if snapshot.status == Status.IN_PROGRESS or unresolved_expired else (
                BatchState.RUNNING if reserved else BatchState.QUEUED
            ), snapshot, reserved,
            registration_confirmed=self._read("registered", run_id) is not None,
        )

    @staticmethod
    def _decode_snapshot(value: dict) -> Snapshot:
        payload = _json(value)
        return _snapshot(payload, _hash(payload))

    def run(
        self, run_id: str, *, cancelled: Callable[[], bool] = lambda: False,
    ) -> BatchStatus:
        """Task entry point; restart from immutable admissions and saved outcomes."""
        run = self._authorization(run_id)
        if self._read(*self._owner_key(run)) != {"run_id": run_id}:
            raise Conflict("batch_round_not_authorized")
        snapshot = self._read_execution(run.job_id)
        for index in range(run.limits.max_attempts + 1):
            step = self._read("step", run_id, index)
            expected = run.expected_revision + index
            if step is None:
                if snapshot.status == Status.IN_PROGRESS:
                    return self.status(run_id)
                if snapshot.revision != expected:
                    raise Conflict("batch_execution_revision_conflict")
                state = None
                if snapshot.status == Status.COMPLETED:
                    state = BatchState.COMPLETED
                elif snapshot.status == Status.FAILED and not (index == 0 and run.previous_run_id):
                    state = BatchState.FAILED
                elif (
                    index == run.limits.max_attempts
                    or self.clock() >= run.limits.deadline or cancelled()
                ):
                    state = BatchState.LIMITED
                if state is not None:
                    proposed = {
                        "kind": "terminal", "state": state.value, "snapshot": asdict(snapshot),
                    }
                else:
                    proposed = {
                        "kind": "attempt", "request_id": self._key("attempt", run_id, expected),
                        "expected_revision": expected,
                        "action": (
                            Action.RESUME if snapshot.status == Status.FAILED else Action.ADVANCE
                        ).value,
                        "admitted_at": self.clock(),
                    }
                step = self._put(proposed, "step", run_id, index)
            if step["kind"] == "terminal":
                return self.status(run_id)
            result = self._read("result", run_id, index)
            if result is None:
                current = self._read_execution(run.job_id)
                if current.status == Status.IN_PROGRESS:
                    return self.status(run_id)
                if current.revision == expected and self.clock() >= run.limits.deadline:
                    # An admission with no known outcome is not a resumable limit.
                    return self.status(run_id)
                if current.revision > expected and (
                    current.attempts[expected].request_id != step["request_id"]
                ):
                    raise Conflict("batch_execution_owner_conflict")
                try:
                    snapshot = self.execution.advance(
                        run.job_id, expected, step["request_id"], action=Action(step["action"]),
                    )
                except Blocked:
                    return self.status(run_id)
                except ExecutionError:
                    raise
                except Exception:
                    raise ExecutionError("batch_execution_interrupted") from None
                result = self._put(asdict(snapshot), "result", run_id, index)
            snapshot = self._decode_snapshot(result)
        raise Conflict("batch_terminal_missing")
