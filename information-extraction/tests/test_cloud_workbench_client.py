import json
import time
import unittest
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event, local

try:
    import httpx
    from azure.core.credentials import AccessToken
except ImportError:
    httpx = None

from tests.test_workbench_client import ROUND


ENDPOINT = "https://example.services.ai.azure.com/api/projects/example-project"
CURRENT = {
    "synthetic_only": True, "app_instance_id": "backend-1",
    "job_id": "synthetic-job", "current": ROUND, "pending_request": None,
}


class Credential:
    def __init__(self):
        self.scopes = []
        self.closed = False

    def get_token(self, *scopes, **kwargs):
        self.scopes.append(scopes)
        return AccessToken("external-test-token", time.time() + 3600)

    def close(self):
        self.closed = True


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


@unittest.skipIf(httpx is None, "optional HTTP/Azure client not installed")
class CloudWorkbenchClientTests(unittest.TestCase):
    def test_waiting_session_rechecks_current_authorization_after_the_lock(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        class Denied(WorkbenchError):
            pass

        context = local()
        permissions = {"first": True, "second": True}
        in_http = Event()
        release_http = Event()
        second_started = Event()
        requests = []
        credential = Credential()

        def authorize():
            if not permissions[context.operator]:
                raise Denied("Operator denied.")

        def handle(request):
            requests.append(request)
            in_http.set()
            if not release_http.wait(5):
                raise AssertionError("bootstrap not released")
            return httpx.Response(200, json=CURRENT, headers={"x-agent-session-id": "session-1"})

        with CloudWorkbenchClient(
            ENDPOINT, "agent", credential, authorize=authorize,
            transport=httpx.MockTransport(handle),
        ) as client, ThreadPoolExecutor(max_workers=2) as executor:
            def discover(operator):
                context.operator = operator
                if operator == "second":
                    second_started.set()
                return client.current()

            first = executor.submit(discover, "first")
            try:
                self.assertTrue(in_http.wait(5))
                second = executor.submit(discover, "second")
                self.assertTrue(second_started.wait(5))
                permissions["second"] = False
            finally:
                release_http.set()
            self.assertEqual(first.result(timeout=5).job_id, "synthetic-job")
            with self.assertRaises(Denied):
                second.result(timeout=5)
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(credential.scopes), 1)

    def test_failed_invocations_consume_budget_and_bad_clocks_fail_closed(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        requests = []

        def handle(request):
            requests.append(request)
            if len(requests) == 2:
                raise httpx.ReadTimeout("private diagnostic", request=request)
            return httpx.Response(200, json=CURRENT, headers={"x-agent-session-id": "session-1"})

        with CloudWorkbenchClient(
            ENDPOINT, "agent", Credential(), authorize=lambda: None, max_requests=2,
            transport=httpx.MockTransport(handle),
        ) as client:
            client.current()
            for _ in range(2):
                with self.assertRaises(WorkbenchError):
                    client.current()
        self.assertEqual(len(requests), 2)
        for invalid_time in (float("nan"), float("inf"), "bad", True, 999):
            clock = Clock()
            with self.subTest(invalid_time=invalid_time), CloudWorkbenchClient(
                ENDPOINT, "agent", Credential(), authorize=lambda: None, monotonic=clock,
                transport=httpx.MockTransport(lambda request: httpx.Response(
                    200, json=CURRENT, headers={"x-agent-session-id": "session-1"},
                )),
            ) as client:
                client.current()
                clock.now = invalid_time
                with self.assertRaises(WorkbenchError):
                    client.current()
                clock.now = 1001
                with self.assertRaises(WorkbenchError):
                    client.current()

    def test_token_expired_during_authorization_and_invalid_wall_clock_never_send(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        class TokenSource(Credential):
            def get_token(self, *scopes, **kwargs):
                return AccessToken("token", 1001)

        for invalid_time in (1001, float("nan"), float("inf"), True, "bad"):
            clock = Clock()
            authorizations = []

            def authorize():
                authorizations.append(True)
                if len(authorizations) == 2:
                    clock.now = invalid_time

            with self.subTest(invalid_time=invalid_time), CloudWorkbenchClient(
                ENDPOINT, "agent", TokenSource(), authorize=authorize, clock=clock,
                transport=httpx.MockTransport(lambda request: self.fail("invalid token reached HTTP")),
            ) as client:
                with self.assertRaises(WorkbenchError):
                    client.current()

    def test_simultaneous_discovery_bootstraps_only_one_gateway_session(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient

        first_request = Event()
        release_first = Event()
        second_started = Event()
        requests = []
        credential = Credential()

        def handle(request):
            requests.append(request)
            if len(requests) == 1:
                first_request.set()
                if not release_first.wait(5):
                    raise AssertionError("concurrent request did not release bootstrap")
            return httpx.Response(200, json=CURRENT, headers={"x-agent-session-id": "session-1"})

        with CloudWorkbenchClient(
            ENDPOINT, "agent", credential, authorize=lambda: None,
            transport=httpx.MockTransport(handle),
        ) as client, ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(client.current)
            try:
                self.assertTrue(first_request.wait(5))

                def discover():
                    second_started.set()
                    return client.current()

                second = executor.submit(discover)
                self.assertTrue(second_started.wait(5))
            finally:
                release_first.set()
            self.assertEqual(first.result(timeout=5).job_id, "synthetic-job")
            self.assertEqual(second.result(timeout=5).job_id, "synthetic-job")
        self.assertEqual(len(requests), 2)
        self.assertNotIn("agent_session_id", requests[0].url.params)
        self.assertEqual(requests[1].url.params["agent_session_id"], "session-1")

    def test_authorization_denies_every_public_operation_before_token_or_http(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import SavedRequest, WorkbenchError

        class Denied(WorkbenchError):
            pass

        allowed = True
        requests = []
        credential = Credential()

        def authorize():
            if not allowed:
                raise Denied("Operator denied.")

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json=CURRENT, headers={"x-agent-session-id": "session-1"})

        with CloudWorkbenchClient(
            ENDPOINT, "agent", credential, authorize=authorize, transport=httpx.MockTransport(handle),
        ) as client:
            found = client.current()
            allowed = False
            for operation in (
                client.current, lambda: client.start(found.job_id),
                lambda: client.resume(found.round),
                lambda: client.retry(SavedRequest("start", found.job_id, "saved-1", 0, 1, 900)),
            ):
                with self.assertRaises(Denied):
                    operation()
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(credential.scopes), 1)

    def test_unexpected_authorizer_errors_are_sanitized_without_sending(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        def authorize():
            raise RuntimeError("private authorization diagnostic")

        with CloudWorkbenchClient(
            ENDPOINT, "agent", Credential(), authorize=authorize,
            transport=httpx.MockTransport(lambda request: self.fail("unauthorized HTTP request")),
        ) as client:
            with self.assertRaises(WorkbenchError) as raised:
                client.current()
            self.assertNotIn("private authorization diagnostic", str(raised.exception))

    def test_protocol_errors_are_safe_and_never_report_an_empty_job(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        inconsistent = deepcopy(CURRENT)
        inconsistent["current"]["attempts_reserved"] = 6
        cases = (
            (200, b'{"synthetic_only":true,"job_id":"synthetic-job"}'),
            (200, b'{"synthetic_only":true,"current":null,"current":{}}'),
            (200, b"x" * 65537),
            (200, b"[" * 1100 + b"0" + b"]" * 1100),
            (200, b"private diagnostic"),
            (200, b"[]"),
            (200, json.dumps(inconsistent).encode()),
            (200, b'{"ignored":NaN}'),
            (401, b"private diagnostic"), (403, b"private diagnostic"),
            (429, b"private diagnostic"), (503, b"private diagnostic"),
            (307, b"private diagnostic"),
        )
        for status, content in cases:
            requests = []

            def handle(request):
                requests.append(request)
                return httpx.Response(status, content=content, headers={
                    "x-agent-session-id": "session-1", "location": "https://example.invalid/",
                })

            with self.subTest(status=status, size=len(content)), CloudWorkbenchClient(
                ENDPOINT, "agent", Credential(), authorize=lambda: None,
                transport=httpx.MockTransport(handle),
            ) as client:
                with self.assertRaises(WorkbenchError) as raised:
                    client.current()
                self.assertNotIn("private diagnostic", str(raised.exception))
                self.assertEqual(len(requests), 1)

    def test_not_found_and_gone_never_replace_a_known_selector(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        for status in (404, 410):
            requests = []

            def handle(request):
                requests.append(request)
                return httpx.Response(
                    200 if len(requests) == 1 else status, json=CURRENT,
                    headers={"x-agent-session-id": "session-1"},
                )

            with self.subTest(status=status), CloudWorkbenchClient(
                ENDPOINT, "agent", Credential(), authorize=lambda: None,
                transport=httpx.MockTransport(handle),
            ) as client:
                client.current()
                for _ in range(2):
                    with self.assertRaises(WorkbenchError):
                        client.current()
            self.assertEqual(len(requests), 3)
            for request in requests[1:]:
                self.assertEqual(request.url.params["agent_session_id"], "session-1")

    def test_close_is_idempotent_and_does_not_close_caller_owned_credential(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        credential = Credential()
        client = CloudWorkbenchClient(
            ENDPOINT, "agent", credential, authorize=lambda: None,
            transport=httpx.MockTransport(lambda request: self.fail("closed client made request")),
        )
        client.close()
        client.close()
        with self.assertRaises(WorkbenchError):
            client.current()
        self.assertFalse(credential.closed)

    def test_lifetime_starts_at_first_invocation_and_is_not_renewed_by_polls(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        clock = Clock()
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json=CURRENT, headers={"x-agent-session-id": "session-1"})

        with CloudWorkbenchClient(
            ENDPOINT, "agent", Credential(), authorize=lambda: None, monotonic=clock,
            transport=httpx.MockTransport(handle),
        ) as client:
            clock.now = 10000
            client.current()
            clock.now = 10899
            client.current()
            clock.now = 10900
            for _ in range(2):
                with self.assertRaises(WorkbenchError):
                    client.current()
        self.assertEqual(len(requests), 2)

    def test_default_request_budget_counts_polls_and_never_renews(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json=CURRENT, headers={"x-agent-session-id": "session-1"})

        with CloudWorkbenchClient(
            ENDPOINT, "agent", Credential(), authorize=lambda: None,
            transport=httpx.MockTransport(handle),
        ) as client:
            for _ in range(120):
                client.current()
            with self.assertRaises(WorkbenchError):
                client.current()
        self.assertEqual(len(requests), 120)

    def test_budget_is_checked_again_after_slow_token_acquisition(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        clock = Clock()
        requests = []

        class TokenSource(Credential):
            def get_token(self, *scopes, **kwargs):
                if self.scopes:
                    clock.now += 900
                return super().get_token(*scopes, **kwargs)

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json=CURRENT, headers={"x-agent-session-id": "session-1"})

        with CloudWorkbenchClient(
            ENDPOINT, "agent", TokenSource(), authorize=lambda: None, monotonic=clock,
            transport=httpx.MockTransport(handle),
        ) as client:
            client.current()
            with self.assertRaises(WorkbenchError):
                client.current()
        self.assertEqual(len(requests), 1)

    def test_optional_budgets_are_finite_and_cannot_raise_the_safety_ceiling(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        for options in (
            {"max_requests": 0}, {"max_requests": 121}, {"max_requests": True},
            {"max_requests": 1.5}, {"lifetime_seconds": 0}, {"lifetime_seconds": 901},
            {"lifetime_seconds": True}, {"lifetime_seconds": float("nan")},
            {"lifetime_seconds": float("inf")}, {"monotonic": None}, {"clock": None},
        ):
            with self.subTest(options=options), self.assertRaises(WorkbenchError):
                CloudWorkbenchClient(ENDPOINT, "agent", Credential(), authorize=lambda: None, **options)

    def test_invalid_or_failed_credentials_never_send_and_hide_sdk_details(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError
        from azure.core.exceptions import ClientAuthenticationError

        tokens = (
            AccessToken("", 2000), AccessToken("token", 1000), AccessToken("token", 999),
            AccessToken("token", float("nan")), AccessToken("token", float("inf")),
            AccessToken("token", True), AccessToken("bad\nheader", 2000),
            None, ClientAuthenticationError("private SDK diagnostic"),
        )
        for result in tokens:
            requests = []

            class TokenSource(Credential):
                def get_token(self, *scopes, **kwargs):
                    if isinstance(result, Exception):
                        raise result
                    return result

            with self.subTest(result=result), CloudWorkbenchClient(
                ENDPOINT, "agent", TokenSource(), authorize=lambda: None, clock=Clock(),
                transport=httpx.MockTransport(lambda request: requests.append(request)),
            ) as client:
                with self.assertRaises(WorkbenchError) as raised:
                    client.current()
                self.assertNotIn("private SDK diagnostic", str(raised.exception))
                self.assertNotIn("bad\nheader", str(raised.exception))
                self.assertEqual(requests, [])

    def test_authorization_is_current_after_slow_token_acquisition(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        class Denied(WorkbenchError):
            pass

        permitted = True
        requests = []

        def authorize():
            if not permitted:
                raise Denied("Operator is no longer authorized.")

        class TokenSource(Credential):
            def get_token(self, *scopes, **kwargs):
                nonlocal permitted
                permitted = False
                return super().get_token(*scopes, **kwargs)

        with CloudWorkbenchClient(
            ENDPOINT, "agent", TokenSource(), authorize=authorize,
            transport=httpx.MockTransport(lambda request: requests.append(request)),
        ) as client:
            with self.assertRaises(Denied):
                client.current()
        self.assertEqual(requests, [])

    def test_contradictory_or_missing_known_affinity_quarantines_routing(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        for headers in ({}, {"x-agent-session-id": "other-session"}):
            requests = []

            def handle(request):
                requests.append(request)
                return httpx.Response(200, json=CURRENT, headers=(
                    {"x-agent-session-id": "original-session"} if len(requests) == 1 else headers
                ))

            with self.subTest(headers=headers), CloudWorkbenchClient(
                ENDPOINT, "agent", Credential(), authorize=lambda: None,
                transport=httpx.MockTransport(handle),
            ) as client:
                client.current()
                for _ in range(2):
                    with self.assertRaises(WorkbenchError):
                        client.current()
                self.assertEqual(len(requests), 2)
                self.assertEqual(requests[1].url.params["agent_session_id"], "original-session")

    def test_explicit_commands_and_expired_retry_preserve_intent_after_lost_ack(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        saved = {
            "action": "start", "job_id": "synthetic-job", "request_id": "original-request",
            "expected_revision": 0, "max_attempts": 1, "deadline": 900,
        }
        requests = []
        commands = []

        def handle(request):
            requests.append(request)
            body = json.loads(request.content)
            if body["action"] == "current":
                return httpx.Response(200, json={**CURRENT, "pending_request": saved},
                                      headers={"x-agent-session-id": "session-1"})
            commands.append(body)
            if len(commands) == 1:
                raise httpx.ReadTimeout("private lost acknowledgement", request=request)
            return httpx.Response(202, json={
                "synthetic_only": True,
                "authorization": {"run_id": "run-1", "request_id": body["request_id"]},
            }, headers={"x-agent-session-id": "session-1"})

        with CloudWorkbenchClient(
            ENDPOINT, "agent", Credential(), authorize=lambda: None,
            transport=httpx.MockTransport(handle),
        ) as client:
            found = client.current()
            before = time.time()
            with self.assertRaises(WorkbenchError):
                client.start(found.job_id, max_attempts=2, duration_seconds=60)
            self.assertEqual(len(commands), 1)
            recovered = client.current()
            client.retry(recovered.pending)
            client.resume(found.round, max_attempts=3, duration_seconds=120)
            after = time.time()
        self.assertEqual(commands[1], saved)
        self.assertEqual(commands[0]["action"], "start")
        self.assertEqual(commands[0]["expected_revision"], 0)
        self.assertEqual(commands[0]["max_attempts"], 2)
        self.assertTrue(before + 60 <= commands[0]["deadline"] <= after + 60)
        self.assertEqual(commands[2]["action"], "resume")
        self.assertEqual(commands[2]["run_id"], "run-1")
        self.assertEqual(commands[2]["expected_revision"], 1)
        self.assertEqual(commands[2]["max_attempts"], 3)
        self.assertTrue(before + 120 <= commands[2]["deadline"] <= after + 120)
        self.assertNotEqual(commands[0]["request_id"], commands[2]["request_id"])
        for request in requests[1:]:
            self.assertEqual(request.url.params["agent_session_id"], "session-1")

    def test_lost_or_ambiguous_initial_affinity_never_bootstraps_again(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        responses = (
            None, [], [("x-agent-session-id", "")],
            [("x-agent-session-id", "bad session")],
            [("x-agent-session-id", "a,b")],
            [("x-agent-session-id", "a?secret=1")],
            [("x-agent-session-id", "a" * 257)],
            [("x-agent-session-id", "one"), ("x-agent-session-id", "one")],
            [("x-agent-session-id", "one"), ("x-agent-session-id", "two")],
        )
        for headers in responses:
            calls = []

            def handle(request):
                calls.append(request)
                if headers is None:
                    raise httpx.ReadTimeout("private diagnostic", request=request)
                return httpx.Response(200, json=CURRENT, headers=headers)

            with self.subTest(headers=headers), CloudWorkbenchClient(
                ENDPOINT, "agent", Credential(), authorize=lambda: None,
                transport=httpx.MockTransport(handle),
            ) as client:
                for _ in range(2):
                    with self.assertRaises(WorkbenchError) as raised:
                        client.current()
                    self.assertNotIn("private diagnostic", str(raised.exception))
                self.assertEqual(len(calls), 1)

    def test_cloud_routes_reject_noncanonical_endpoints_and_agent_names(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient
        from information_extraction.workbench_client import WorkbenchError

        endpoints = (
            "http://example.services.ai.azure.com/api/projects/project",
            "https://example.com/api/projects/project",
            "https://example.services.ai.azure.com.evil.test/api/projects/project",
            "https://a.b.services.ai.azure.com/api/projects/project",
            ENDPOINT + "/", ENDPOINT + "?", ENDPOINT + "#",
            ENDPOINT + "?api-version=v1", ENDPOINT + "#fragment",
            ENDPOINT.replace("example.services", "user@example.services"),
            ENDPOINT.replace(".com/", ".com:8443/"),
            ENDPOINT.replace(".com/", ".com:443/"),
            ENDPOINT.replace("example-project", "%2e%2e"),
            ENDPOINT.replace("example-project", ".."),
            ENDPOINT.replace("example-project", "project/other"),
            ENDPOINT.replace("example-project", "project\\other"),
            ENDPOINT.replace("https://", "https://\n"),
            ENDPOINT + " ", None, 123,
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint), self.assertRaises(WorkbenchError):
                CloudWorkbenchClient(endpoint, "agent", Credential(), authorize=lambda: None)
        for agent in ("", ".", "..", "agent/other", "agent?x=1", "a%2fb", "a b", None, "a" * 129):
            with self.subTest(agent=agent), self.assertRaises(WorkbenchError):
                CloudWorkbenchClient(ENDPOINT, agent, Credential(), authorize=lambda: None)
        with self.assertRaises(WorkbenchError):
            CloudWorkbenchClient(ENDPOINT, "agent", Credential(), authorize=None)

    def test_current_projects_progress_and_reuses_gateway_query_affinity(self):
        from information_extraction.cloud_workbench_client import CloudWorkbenchClient

        credential = Credential()
        requests = []
        authorized = []

        def handle(request):
            requests.append(request)
            return httpx.Response(
                200, json=CURRENT, headers={"x-agent-session-id": "session-1"},
            )

        with CloudWorkbenchClient(
            ENDPOINT, "example-agent", credential, authorize=lambda: authorized.append(True),
            transport=httpx.MockTransport(handle),
        ) as client:
            self.assertEqual(client.current().round.candidates[0].value, 120)
            self.assertEqual(client.current().round.revision, 1)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].url.path,
                         "/api/projects/example-project/agents/example-agent/endpoint/protocols/invocations")
        self.assertEqual(dict(requests[0].url.params), {"api-version": "v1"})
        self.assertEqual(dict(requests[1].url.params),
                         {"api-version": "v1", "agent_session_id": "session-1"})
        for request in requests:
            self.assertEqual(json.loads(request.content), {"action": "current"})
            self.assertEqual(request.headers["authorization"], "Bearer external-test-token")
            self.assertNotIn("x-agent-session-id", request.headers)
        self.assertGreaterEqual(len(authorized), 4)
        self.assertEqual(credential.scopes, [("https://ai.azure.com/.default",)] * 2)
        self.assertFalse(credential.closed)
