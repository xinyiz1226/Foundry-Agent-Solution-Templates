"""Server-side Foundry transport; gateway affinity is routing, not authorization."""

import json
import math
import re
import time
from threading import Lock
from typing import Callable

from azure.core.credentials import TokenCredential
import httpx

from .workbench_client import WorkbenchError, _mapping, _unique_object, _WorkbenchProtocol


class CloudWorkbenchClient(_WorkbenchProtocol):
    """One process-local routing/budget owner; injected credentials remain caller-owned.

    Limits gate invocation attempts, not Azure resource lifetime or billing. Replacing
    this object is an explicit operator lifecycle decision, never a polling recovery.
    """

    def __init__(
        self, project_endpoint: str, agent_name: str, credential: TokenCredential, *,
        authorize: Callable[[], None], transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        lifetime_seconds: int | float = 900, max_requests: int = 120,
    ):
        if (
            type(project_endpoint) is not str
            or re.fullmatch(
                r"https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
                r"\.services\.ai\.azure\.com/api/projects/[A-Za-z0-9][A-Za-z0-9_-]{0,127}",
                project_endpoint,
            ) is None
        ):
            raise WorkbenchError("Use a canonical HTTPS public Foundry project endpoint without a port or query.")
        if (
            type(agent_name) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", agent_name) is None
        ):
            raise WorkbenchError("The Foundry agent name is invalid.")
        if not callable(authorize):
            raise WorkbenchError("A current operator authorization check is required.")
        if not callable(clock) or not callable(monotonic):
            raise WorkbenchError("A valid clock is required.")
        if (
            type(lifetime_seconds) not in (int, float) or not 0 < lifetime_seconds <= 900
            or type(max_requests) is not int or not 1 <= max_requests <= 120
        ):
            raise WorkbenchError("Cloud invocation limits must be at most 900 seconds and 120 requests.")
        self._url = f"{project_endpoint}/agents/{agent_name}/endpoint/protocols/invocations"
        self._credential = credential
        self._authorize = authorize
        self._clock = clock
        self._monotonic = monotonic
        self._lifetime_seconds = lifetime_seconds
        self._max_requests = max_requests
        self._started_at = None
        self._last_time = None
        self._request_count = 0
        self._budget_blocked = False
        self._lock = Lock()
        self._session_id = None
        self._bootstrap_attempted = False
        self._routing_blocked = False
        self._closed = False
        self._client = httpx.Client(
            transport=transport, timeout=10, follow_redirects=False, trust_env=False,
        )

    def close(self):
        with self._lock:
            self._closed = True
            self._client.close()

    def _budget_time(self) -> float:
        try:
            now = self._monotonic()
            if (
                self._budget_blocked
                or type(now) not in (int, float) or not math.isfinite(now)
                or (self._last_time is not None and now < self._last_time)
                or self._request_count >= self._max_requests
                or (self._started_at is not None and now - self._started_at >= self._lifetime_seconds)
            ):
                raise ValueError
        except Exception:
            self._budget_blocked = True
            raise WorkbenchError("The cloud invocation budget is exhausted or uncertain. Stop and inspect.") from None
        self._last_time = now
        return now

    def _check_authorization(self) -> None:
        try:
            self._authorize()
        except WorkbenchError:
            raise
        except Exception:
            raise WorkbenchError("Current operator authorization could not be verified.") from None

    def _request(self, body: dict[str, object], expected_status: int) -> dict[str, object]:
        with self._lock:
            if self._closed:
                raise WorkbenchError("The cloud client is closed.")
            self._check_authorization()
            self._budget_time()
            if self._routing_blocked or (self._bootstrap_attempted and self._session_id is None):
                raise WorkbenchError("Gateway routing is uncertain. Stop and inspect; no replacement session was created.")
            try:
                token = self._credential.get_token("https://ai.azure.com/.default")
            except Exception:
                raise WorkbenchError("The server credential could not obtain a Foundry access token.") from None
            self._check_authorization()
            try:
                now = self._clock()
                if (
                    type(now) not in (int, float) or not math.isfinite(now)
                    or type(token.token) is not str
                    or re.fullmatch(r"[A-Za-z0-9._~+/-]{1,32768}=*", token.token) is None
                    or type(token.expires_on) not in (int, float)
                    or not math.isfinite(token.expires_on) or token.expires_on <= now
                ):
                    raise ValueError
            except (ValueError, TypeError, AttributeError, OverflowError):
                raise WorkbenchError("The server credential returned an invalid or expired access token.") from None
            now = self._budget_time()
            params = {"api-version": "v1"}
            if self._session_id is not None:
                params["agent_session_id"] = self._session_id
            if self._started_at is None:
                self._started_at = now
            self._request_count += 1
            self._bootstrap_attempted = True
            try:
                with self._client.stream(
                    "POST", self._url, params=params, json=body,
                    headers={"Authorization": f"Bearer {token.token}"},
                    timeout=min(10, self._lifetime_seconds - (now - self._started_at)),
                ) as response:
                    selectors = response.headers.get_list("x-agent-session-id")
                    if (
                        len(selectors) != 1
                        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", selectors[0]) is None
                        or (self._session_id is not None and selectors[0] != self._session_id)
                    ):
                        self._routing_blocked = True
                        raise WorkbenchError("Gateway routing was not confirmed. Stop and inspect the session.")
                    self._session_id = selectors[0]
                    raw = bytearray()
                    for chunk in response.iter_bytes(chunk_size=8192):
                        if len(raw) + len(chunk) > 65536:
                            raise WorkbenchError("The cloud backend returned an oversized response.")
                        raw.extend(chunk)
                    if response.status_code != expected_status:
                        raise WorkbenchError(f"The cloud backend rejected the request (HTTP {response.status_code}).")
                    return _mapping(json.loads(raw, object_pairs_hook=_unique_object))
            except httpx.HTTPError:
                raise WorkbenchError(
                    "The cloud request failed or its outcome is unknown. No automatic retry was made; "
                    "inspect the saved state before acting again."
                ) from None
            except (ValueError, TypeError, RecursionError):
                raise WorkbenchError("The cloud backend returned invalid data.") from None
