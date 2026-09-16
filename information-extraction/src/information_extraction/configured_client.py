"""Bounded server-to-server client for the same-user configured workbench."""

from contextlib import closing
from dataclasses import asdict
import json
import math
import re
import time
from typing import Callable
from uuid import uuid4

import httpx

from .batch import BatchState
from .codec import _hash, _json, _snapshot
from .contracts import ConfiguredPlan, ExtractionProfile, Status, validate_identifier
from .schema import load_profile
from .workbench_client import _saved, _unique_object


_ERROR_CODES = frozenset({
    "unauthorized", "origin_not_allowed", "query_not_allowed", "invalid_request",
    "request_too_large", "unsupported_media_type", "execution_conflict", "not_found",
    "saved_request_expired", "batch_registration_unknown", "stored_state_invalid",
    "execution_unavailable", "internal_error", "model_disabled", "model_budget_exhausted",
})
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class ConfiguredWorkbenchError(Exception):
    """Only a fixed safe code is exposed, never response bodies or transport details."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _nonfinite(_):
    raise ValueError("nonfinite_json_number")


def _count(value):
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError("invalid_count")
    return value


def _snapshot_response(data, job_id=None):
    if type(data) is not dict:
        raise ValueError("invalid_response")
    validate_identifier(data["job_id"])
    if job_id is not None and data["job_id"] != job_id:
        raise ValueError("foreign_job")
    payload = _json(data["snapshot"])
    snapshot = _snapshot(payload, _hash(payload))
    _count(snapshot.revision)
    if (
        not isinstance(snapshot.plan, ConfiguredPlan) or snapshot.job_id != data["job_id"]
        or snapshot.plan_fingerprint != _hash(_json(asdict(snapshot.plan)))
        or snapshot.job_id != "configured-" + snapshot.plan_fingerprint
        or len(snapshot.completed_chunk_ids) != len(set(snapshot.completed_chunk_ids))
        or not set(snapshot.completed_chunk_ids) <= {chunk.id for chunk in snapshot.plan.chunks}
    ):
        raise ValueError("invalid_snapshot")
    return snapshot


def _authorization(value, job_id):
    if type(value) is not dict or value["job_id"] != job_id:
        raise ValueError("foreign_authorization")
    validate_identifier(value["run_id"])
    validate_identifier(value["request_id"])
    if value["run_id"] != _hash(_json(["run", value["request_id"]])):
        raise ValueError("invalid_run_identity")
    _count(value["expected_revision"])
    if type(value["plan_fingerprint"]) is not str or re.fullmatch(
        "[0-9a-f]{64}", value["plan_fingerprint"],
    ) is None or job_id != "configured-" + value["plan_fingerprint"]:
        raise ValueError("invalid_fingerprint")
    previous = value["previous_run_id"]
    if previous is not None:
        validate_identifier(previous)
    body = {
        "action": "start" if previous is None else "resume",
        "job_id" if previous is None else "run_id": job_id if previous is None else previous,
        "request_id": value["request_id"], "expected_revision": value["expected_revision"],
        **value["limits"],
    }
    return _saved(body, job_id).body()


class ConfiguredClient:
    def __init__(
        self, base_url: str, token: str, *, http_client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None, clock: Callable[[], float] = time.time,
    ):
        try:
            if (
                type(base_url) is not str
                or re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", base_url) is None
                or not 1 <= int(base_url.rsplit(":", 1)[1]) <= 65535
            ):
                raise ValueError
            if (
                type(token) is not str or not 32 <= len(token) <= 4096
                or any(not 33 <= ord(character) <= 126 for character in token)
            ):
                raise ValueError
            if http_client is not None and transport is not None:
                raise ValueError
        except (ValueError, TypeError):
            raise ConfiguredWorkbenchError("invalid_configuration") from None
        self._base_url = base_url
        self._token = token
        self._clock = clock
        self._owns_client = http_client is None
        self._client = http_client if http_client is not None else httpx.Client(
            transport=transport, trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(10, connect=3),
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self._owns_client:
            self._client.close()

    def _request(self, method, path, *, body=None, expected=200):
        mutation = method == "POST"
        uncertain = "mutation_unconfirmed" if mutation else "backend_unavailable"
        try:
            request = httpx.Request(
                method, self._base_url + path, json=body if mutation else None,
                headers={"Authorization": "Bearer " + self._token, "Accept": "application/json"},
                extensions={"timeout": {"connect": 3.0, "read": 10.0, "write": 10.0, "pool": 3.0}},
            )
            with closing(self._client.send(request, stream=True, auth=None, follow_redirects=False)) as response:
                payload = bytearray()
                for part in response.iter_bytes():
                    if len(payload) + len(part) > MAX_RESPONSE_BYTES:
                        raise ValueError("response_too_large")
                    payload.extend(part)
                if response.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                    raise ValueError("invalid_response_type")
                data = json.loads(
                    payload.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_nonfinite,
                )
                if type(data) is not dict:
                    raise ValueError("invalid_response")
                if response.status_code != expected:
                    code = data.get("error", {}).get("code")
                    if mutation and response.status_code >= 500 and code != "batch_registration_unknown":
                        raise ConfiguredWorkbenchError("mutation_unconfirmed")
                    if type(code) is str and code in _ERROR_CODES:
                        raise ConfiguredWorkbenchError(code)
                    raise ValueError("unexpected_status")
                return data
        except ConfiguredWorkbenchError:
            raise
        except Exception:
            raise ConfiguredWorkbenchError(uncertain) from None

    def configuration(self) -> dict:
        data = self._request("GET", "/configuration")
        try:
            if (
                type(data["enabled"]) is not bool or type(data["model_description"]) is not str
                or not data["model_description"].strip() or len(data["model_description"]) > 1024
                or set(data["profiles"]) != {"financial", "support"}
            ):
                raise ValueError
            _count(data["remaining_calls"])
            for profile in data["profiles"].values():
                load_profile(_json(profile).encode("utf-8"))
        except Exception:
            raise ConfiguredWorkbenchError("invalid_response") from None
        return data

    def jobs(self) -> tuple[dict, ...]:
        data = self._request("GET", "/jobs")
        try:
            jobs = data["jobs"]
            if type(jobs) is not list or len(jobs) > 100:
                raise ValueError
            seen = set()
            for job in jobs:
                if (
                    type(job) is not dict
                    or set(job) != {"job_id", "document_id", "profile_version", "revision", "status"}
                    or re.fullmatch(r"configured-[0-9a-f]{64}", job["job_id"]) is None
                    or job["job_id"] in seen
                ):
                    raise ValueError
                seen.add(job["job_id"])
                validate_identifier(job["document_id"])
                validate_identifier(job["profile_version"])
                _count(job["revision"])
                Status(job["status"])
        except Exception:
            raise ConfiguredWorkbenchError("invalid_response") from None
        return tuple(jobs)

    def prepare(
        self, content: bytes, *, kind: str, profile: ExtractionProfile,
        split: str = "train", conversation_id: int | None = None,
    ) -> dict:
        try:
            if (
                type(content) is not bytes or type(kind) is not str or kind not in ("text", "abcd")
                or len(content) > (32 * 1024 if kind == "text" else 128 * 1024)
                or type(split) is not str or split not in ("train", "dev", "test")
                or conversation_id is not None and (type(conversation_id) is not int or conversation_id < 0)
                or not isinstance(profile, ExtractionProfile)
            ):
                raise ValueError
            frozen = asdict(load_profile(_json(asdict(profile)).encode("utf-8")))
            body = {
                "kind": kind, "content": content.decode("utf-8"), "profile": frozen,
                "split": split, "conversation_id": conversation_id,
            }
        except Exception:
            raise ConfiguredWorkbenchError("invalid_request") from None
        data = self._request("POST", "/jobs", body=body)
        try:
            _snapshot_response(data)
        except Exception:
            raise ConfiguredWorkbenchError("mutation_unconfirmed") from None
        return data

    def current(self, job_id: str) -> dict:
        self._job_id(job_id)
        data = self._request("GET", "/jobs/" + job_id)
        try:
            snapshot = _snapshot_response(data, job_id)
            current = data["round"]
            if current is not None:
                _authorization(current["authorization"], job_id)
                if current["authorization"]["plan_fingerprint"] != snapshot.plan_fingerprint:
                    raise ValueError
                BatchState(current["state"])
                if (
                    type(current["registration_confirmed"]) is not bool
                    or _count(current["attempts_reserved"]) > current["authorization"]["limits"]["max_attempts"]
                ):
                    raise ValueError
            if data["pending_request"] is not None:
                _saved(data["pending_request"], job_id)
        except Exception:
            raise ConfiguredWorkbenchError("invalid_response") from None
        return data

    @staticmethod
    def _job_id(job_id):
        if type(job_id) is not str or re.fullmatch(r"configured-[0-9a-f]{64}", job_id) is None:
            raise ConfiguredWorkbenchError("invalid_request")

    def _limits(self, max_attempts, duration_seconds):
        if (
            type(max_attempts) is not int or not 1 <= max_attempts <= 5
            or type(duration_seconds) is not int or not 1 <= duration_seconds <= 300
        ):
            raise ConfiguredWorkbenchError("invalid_request")
        deadline = self._clock() + duration_seconds
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= 0:
            raise ConfiguredWorkbenchError("invalid_request")
        return {"max_attempts": max_attempts, "deadline": deadline}

    def start(self, job_id: str, *, max_attempts: int, duration_seconds: int) -> dict:
        self._job_id(job_id)
        return self.retry(job_id, {
            "action": "start", "job_id": job_id, "request_id": "configured-round-" + uuid4().hex,
            "expected_revision": 0, **self._limits(max_attempts, duration_seconds),
        })

    def resume(self, current: dict, *, max_attempts: int, duration_seconds: int) -> dict:
        try:
            snapshot = _snapshot_response(current)
            self._job_id(current["job_id"])
            run = current["round"]
            _authorization(run["authorization"], current["job_id"])
            if (
                run["state"] not in (BatchState.LIMITED, BatchState.FAILED)
                or run["authorization"]["plan_fingerprint"] != snapshot.plan_fingerprint
            ):
                raise ValueError
            body = {
                "action": "resume", "run_id": run["authorization"]["run_id"],
                "request_id": "configured-round-" + uuid4().hex,
                "expected_revision": snapshot.revision,
                **self._limits(max_attempts, duration_seconds),
            }
        except Exception:
            raise ConfiguredWorkbenchError("invalid_request") from None
        return self.retry(current["job_id"], body)

    def retry(self, job_id: str, pending: dict) -> dict:
        self._job_id(job_id)
        try:
            body = _saved(pending, job_id).body()
        except Exception:
            raise ConfiguredWorkbenchError("invalid_request") from None
        data = self._request("POST", "/jobs/" + job_id + "/round", body=body, expected=202)
        try:
            if _authorization(data["authorization"], job_id) != body:
                raise ValueError
        except Exception:
            raise ConfiguredWorkbenchError("mutation_unconfirmed") from None
        return data
