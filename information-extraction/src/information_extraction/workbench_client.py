"""Local-only workbench transport; reads never submit extraction work."""

from dataclasses import dataclass
import json
import math
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from .batch import BatchLimits, BatchState
from .contracts import InvalidInput, Metric, Status, validate_identifier
from .sample import synthetic_plan


class WorkbenchError(Exception):
    pass


_ERROR_MESSAGES = {
    "execution_unavailable": "The local backend could not read durable execution state.",
    "execution_conflict": "This job already changed. Refresh before acting again.",
    "invalid_request": "The backend rejected the command or its deadline. Refresh to inspect the saved request.",
    "not_found": "The saved job could not be found. Inspect the backend state; do not start a replacement.",
    "batch_registration_unknown": "The request was saved but scheduling is unconfirmed. Refresh to inspect it.",
    "saved_request_expired": "The saved request expired before authorization. It cannot be renewed; retain the state for inspection.",
}
_SAMPLE_CHUNKS = frozenset(chunk.id for chunk in synthetic_plan().chunks)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


@dataclass(frozen=True)
class EvidenceView:
    block_id: str
    location: str
    text: str


@dataclass(frozen=True)
class CandidateView:
    id: str
    metric: str
    value: int | float
    unit: str
    evidence: tuple[EvidenceView, ...]


@dataclass(frozen=True)
class RoundView:
    run_id: str
    state: BatchState
    execution_state: Status
    revision: int
    max_attempts: int
    deadline: int | float
    completed_chunks: tuple[str, ...]
    attempts_reserved: int
    committed_attempts: int
    registration_confirmed: bool
    known_input_tokens: int
    known_output_tokens: int
    unknown_usage_attempts: int
    candidates: tuple[CandidateView, ...]


@dataclass(frozen=True)
class SavedRequest:
    action: str
    target: str
    request_id: str
    expected_revision: int
    max_attempts: int
    deadline: int | float

    def body(self) -> dict[str, object]:
        return {
            "action": self.action,
            "job_id" if self.action == "start" else "run_id": self.target,
            "request_id": self.request_id, "expected_revision": self.expected_revision,
            "max_attempts": self.max_attempts, "deadline": self.deadline,
        }


@dataclass(frozen=True)
class CurrentJob:
    job_id: str
    app_instance_id: str
    round: RoundView | None = None
    pending: SavedRequest | None = None


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise ValueError("invalid_object")
    return value


def _items(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("invalid_array")
    return value


def _text(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("invalid_text")
    return value


def _identifier(value: object) -> str:
    result = _text(value)
    validate_identifier(result)
    return result


def _number(value: object) -> int | float:
    if type(value) is int or (type(value) is float and math.isfinite(value)):
        return value
    raise ValueError("invalid_number")


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid_count")
    return value


def _deadline(value: object) -> int | float:
    result = _number(value)
    if not 0 < result <= 253402300799:
        raise ValueError("invalid_deadline")
    return result


def _candidate(value: object) -> CandidateView:
    data = _mapping(value)
    record = _mapping(data["record"])
    metric = Metric(_text(record["metric"])).value
    if (
        record["unit"] != "USD_millions" or data["review_status"] != "pending"
        or data["semantic_validation_performed"] is not False
    ):
        raise ValueError("unexpected_candidate")
    evidence = []
    for raw in _items(data["evidence"]):
        item = _mapping(raw)
        evidence.append(EvidenceView(
            _identifier(item["block_id"]), _text(item["location"]), _text(item["text"]),
        ))
    if not evidence:
        raise ValueError("missing_evidence")
    return CandidateView(
        _text(data["id"]), metric, _number(record["value"]),
        "USD_millions", tuple(evidence),
    )


def _round(value: object, job_id: str) -> RoundView:
    data = _mapping(value)
    authorization = _mapping(data["authorization"])
    if authorization["job_id"] != job_id:
        raise ValueError("foreign_job")
    limits = _mapping(authorization["limits"])
    maximum = _count(limits["max_attempts"])
    if not 1 <= maximum <= 5 or type(data["registration_confirmed"]) is not bool:
        raise ValueError("invalid_round")
    completed = tuple(_identifier(item) for item in _items(data["completed_chunks"]))
    reserved = _count(data["attempts_reserved"])
    committed = _count(data["committed_attempts"])
    revision = _count(data["revision"])
    if (
        len(completed) != len(set(completed)) or not set(completed) <= _SAMPLE_CHUNKS
        or committed > revision or reserved > maximum
    ):
        raise ValueError("invalid_progress")
    usage = _mapping(data["usage"])
    return RoundView(
        _identifier(authorization["run_id"]), BatchState(_text(data["state"])),
        Status(_text(data["execution_state"])), revision,
        maximum, _deadline(limits["deadline"]), completed, reserved, committed,
        data["registration_confirmed"],
        _count(usage["known_input_tokens"]), _count(usage["known_output_tokens"]),
        _count(usage["unknown_usage_attempts"]),
        tuple(_candidate(item) for item in _items(data["candidates"])),
    )


def _saved(value: object, job_id: str | None = None) -> SavedRequest:
    data = _mapping(value)
    action = _text(data["action"])
    if action not in ("start", "resume"):
        raise ValueError("invalid_action")
    target_key = "job_id" if action == "start" else "run_id"
    if set(data) != {"action", target_key, "request_id", "expected_revision", "max_attempts", "deadline"}:
        raise ValueError("invalid_request")
    target = _identifier(data[target_key])
    if action == "start" and job_id is not None and target != job_id:
        raise ValueError("foreign_job")
    limits = BatchLimits(max_attempts=_count(data["max_attempts"]), deadline=_deadline(data["deadline"]))
    revision = _count(data["expected_revision"])
    if action == "start" and revision != 0:
        raise ValueError("invalid_start_revision")
    return SavedRequest(
        action, target, _identifier(data["request_id"]), revision,
        limits.max_attempts, limits.deadline,
    )


class WorkbenchClient:
    def __init__(self, endpoint: str, *, transport: httpx.BaseTransport | None = None):
        try:
            url = urlsplit(endpoint)
            if (
                url.scheme != "http" or url.hostname != "127.0.0.1"
                or url.port is None or not 1 <= url.port <= 65535
                or url.username is not None or url.password is not None
                or url.path not in ("", "/") or url.query or url.fragment
            ):
                raise ValueError("invalid_endpoint")
        except ValueError:
            raise WorkbenchError("Use a local backend URL of the form http://127.0.0.1:PORT.") from None
        self._client = httpx.Client(
            base_url=f"http://127.0.0.1:{url.port}", transport=transport, timeout=10,
            follow_redirects=False, trust_env=False,
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._client.close()

    def _request(self, body: dict[str, object], expected_status: int) -> dict[str, object]:
        try:
            with self._client.stream("POST", "/invocations", json=body) as response:
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=8192):
                    if len(raw) + len(chunk) > 65536:
                        raise WorkbenchError("The local backend returned an oversized response.")
                    raw.extend(chunk)
                data = _mapping(json.loads(raw, object_pairs_hook=_unique_object))
                if response.status_code != expected_status:
                    error = data.get("error")
                    code = error.get("code") if isinstance(error, dict) else None
                    message = _ERROR_MESSAGES.get(code) if isinstance(code, str) else None
                    raise WorkbenchError(message or f"The local backend rejected the request (HTTP {response.status_code}).")
                return data
        except httpx.HTTPError:
            raise WorkbenchError(
                "The local backend could not be reached or did not respond. No automatic retry was made; "
                "refresh to discover any saved request before acting again."
            ) from None
        except (ValueError, TypeError, RecursionError):
            raise WorkbenchError("The local backend returned invalid data.") from None

    @staticmethod
    def _limits(max_attempts: int, duration_seconds: int) -> BatchLimits:
        if type(duration_seconds) is not int or not 10 <= duration_seconds <= 300:
            raise WorkbenchError("Choose a time limit between 10 and 300 seconds.")
        try:
            return BatchLimits(max_attempts=max_attempts, deadline=time.time() + duration_seconds)
        except InvalidInput:
            raise WorkbenchError("Choose an attempt limit between 1 and 5.") from None

    def start(self, job_id: str, *, max_attempts: int = 1, duration_seconds: int = 120) -> None:
        validate_identifier(job_id)
        limits = self._limits(max_attempts, duration_seconds)
        self._submit({
            "action": "start", "job_id": job_id, "request_id": "workbench-" + uuid4().hex,
            "expected_revision": 0, "max_attempts": limits.max_attempts, "deadline": limits.deadline,
        })

    def resume(self, current: RoundView, *, max_attempts: int = 1, duration_seconds: int = 120) -> None:
        if current.state not in (BatchState.LIMITED, BatchState.FAILED):
            raise WorkbenchError("This round cannot be safely resumed.")
        limits = self._limits(max_attempts, duration_seconds)
        self._submit({
            "action": "resume", "run_id": current.run_id,
            "request_id": "workbench-" + uuid4().hex, "expected_revision": current.revision,
            "max_attempts": limits.max_attempts, "deadline": limits.deadline,
        })

    def retry(self, saved: SavedRequest) -> None:
        try:
            body = _saved(saved.body()).body()
        except (ValueError, KeyError, TypeError, InvalidInput):
            raise WorkbenchError("The saved request is invalid; no request was sent.") from None
        self._submit(body)

    def _submit(self, body: dict[str, object]) -> None:
        data = self._request(body, 202)
        try:
            authorization = _mapping(data["authorization"])
            if (
                data["synthetic_only"] is not True
                or authorization["request_id"] != body["request_id"]
            ):
                raise ValueError("unexpected_response")
            _identifier(authorization["run_id"])
        except (ValueError, KeyError, TypeError, InvalidInput):
            raise WorkbenchError("The local backend did not confirm the request. Refresh before acting again.") from None

    def current(self) -> CurrentJob:
        data = self._request({"action": "current"}, 200)
        try:
            if data["synthetic_only"] is not True:
                raise ValueError("unexpected_response")
            job_id = _identifier(data["job_id"])
            return CurrentJob(
                job_id, _identifier(data["app_instance_id"]),
                _round(data["current"], job_id) if data["current"] is not None else None,
                _saved(data["pending_request"], job_id) if data["pending_request"] is not None else None,
            )
        except (ValueError, KeyError, TypeError, InvalidInput):
            raise WorkbenchError("The local backend returned invalid data.") from None
