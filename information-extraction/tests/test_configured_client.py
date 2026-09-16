from dataclasses import asdict
import importlib.util
import json
import unittest
from unittest.mock import patch

from information_extraction.codec import _hash, _json
from information_extraction.configured_inputs import prepare_plan
from information_extraction.contracts import Snapshot
from information_extraction.profiles import FINANCIAL_PROFILE, SUPPORT_PROFILE


HTTPX_AVAILABLE = importlib.util.find_spec("httpx") is not None
TOKEN = "fixture-only-configured-token-0123456789"


def prepared(profile=FINANCIAL_PROFILE):
    plan = prepare_plan(b"Fixture source.", kind="text", profile=profile, model_binding="fixture")
    fingerprint = _hash(_json(asdict(plan)))
    job = "configured-" + fingerprint
    return json.loads(_json({"job_id": job, "snapshot": asdict(Snapshot(job, plan, fingerprint))}))


def authorization(body, job_id):
    return {
        "run_id": _hash(_json(["run", body["request_id"]])),
        "job_id": job_id,
        "request_id": body["request_id"],
        "plan_fingerprint": job_id.removeprefix("configured-"),
        "expected_revision": body["expected_revision"],
        "limits": {"max_attempts": body["max_attempts"], "deadline": body["deadline"]},
        "previous_run_id": body.get("run_id"),
    }


@unittest.skipUnless(HTTPX_AVAILABLE, "optional httpx not installed")
class ConfiguredClientTests(unittest.TestCase):
    def setUp(self):
        import httpx
        from information_extraction.configured_client import ConfiguredClient

        self.requests = []
        self.now = 1000.0
        self.job = prepared()
        self.handler = lambda request: httpx.Response(200, json=self.job)

        def handle(request):
            self.requests.append(request)
            return self.handler(request)

        self.client = ConfiguredClient(
            "http://127.0.0.1:8000", TOKEN, transport=httpx.MockTransport(handle),
            clock=lambda: self.now,
        )
        self.addCleanup(self.client.close)

    def assert_code(self, code, operation):
        from information_extraction.configured_client import ConfiguredWorkbenchError

        with self.assertRaises(ConfiguredWorkbenchError) as caught:
            operation()
        self.assertEqual(str(caught.exception), code)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_literal_loopback_port_only_and_strong_token(self):
        from information_extraction.configured_client import ConfiguredClient

        for url in (
            "https://127.0.0.1:8000", "http://localhost:8000", "http://0.0.0.0:8000",
            "http://[::1]:8000", "http://127.0.0.1", "http://127.0.0.1:0",
            "http://127.0.0.1:65536", "http://127.0.0.1:8000/", "http://127.0.0.1:8000/jobs",
            "http://127.0.0.1:8000?token=foo", "http://127.0.0.1:8000#fragment",
            "http://user:pass@127.0.0.1:8000", "http://2130706433:8000",
            "http://127.0.0.1:8000\n", " http://127.0.0.1:8000",
        ):
            self.assert_code("invalid_configuration", lambda: ConfiguredClient(url, TOKEN))
        for token in ("short", " " * 32, "é" * 32, "\n" + TOKEN):
            self.assert_code("invalid_configuration", lambda: ConfiguredClient("http://127.0.0.1:80", token))

    def test_default_client_disables_env_proxies_redirects_and_uses_bounded_timeouts(self):
        import httpx
        from information_extraction.configured_client import ConfiguredClient

        with patch("httpx.Client", wraps=httpx.Client) as constructor:
            with ConfiguredClient("http://127.0.0.1:8000", TOKEN):
                pass
        self.assertFalse(constructor.call_args.kwargs["trust_env"])
        self.assertFalse(constructor.call_args.kwargs["follow_redirects"])
        timeout = constructor.call_args.kwargs["timeout"]
        self.assertEqual(timeout.connect, 3)
        self.assertEqual(timeout.read, 10)

    def test_prepare_preserves_utf8_bom_and_exact_profile_without_url_or_path(self):
        content = b"\xef\xbb\xbfFixture \xe2\x82\xac\r\nsource.\n"
        result = self.client.prepare(content, kind="text", profile=FINANCIAL_PROFILE)
        self.assertEqual(result, self.job)
        request = self.requests[0]
        body = json.loads(request.content)
        self.assertEqual(body["content"].encode("utf-8"), content)
        self.assertEqual(body["profile"], json.loads(_json(asdict(FINANCIAL_PROFILE))))
        self.assertEqual(set(body), {"kind", "content", "profile", "split", "conversation_id"})
        self.assertEqual(request.headers["Authorization"], "Bearer " + TOKEN)
        self.assertNotIn(TOKEN, str(request.url))
        self.assertNotIn("Origin", request.headers)
        self.assertEqual(request.extensions["timeout"], {
            "connect": 3.0, "read": 10.0, "write": 10.0, "pool": 3.0,
        })

    def test_abcd_selectors_and_custom_profile_roundtrip(self):
        import httpx

        self.handler = lambda request: httpx.Response(200, json=prepared(SUPPORT_PROFILE))
        content = b'[{"convo_id":7,"original":[["customer","help"]]}]'
        self.client.prepare(content, kind="abcd", profile=SUPPORT_PROFILE, split="dev", conversation_id=7)
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["content"].encode(), content)
        self.assertEqual(body["split"], "dev")
        self.assertEqual(body["conversation_id"], 7)
        self.assertEqual(body["profile"], json.loads(_json(asdict(SUPPORT_PROFILE))))

    def test_invalid_prepare_or_identifier_never_sends(self):
        invalid = (
            lambda: self.client.prepare(b"\xff", kind="text", profile=FINANCIAL_PROFILE),
            lambda: self.client.prepare("C:\\secret", kind="text", profile=FINANCIAL_PROFILE),
            lambda: self.client.prepare(b"hello", kind="url", profile=FINANCIAL_PROFILE),
            lambda: self.client.prepare(b"x" * (32768 + 1), kind="text", profile=FINANCIAL_PROFILE),
            lambda: self.client.prepare(b"hello", kind="abcd", profile=FINANCIAL_PROFILE, conversation_id=True),
            lambda: self.client.current("../private"),
        )
        for operation in invalid:
            self.assert_code("invalid_request", operation)
        self.assertEqual(self.requests, [])

    def test_configuration_jobs_current_and_context_manager(self):
        import httpx

        config = {
            "enabled": False, "model_description": "Prepare only", "remaining_calls": 0,
            "profiles": json.loads(_json({
                "financial": asdict(FINANCIAL_PROFILE), "support": asdict(SUPPORT_PROFILE),
            })),
        }
        job = self.job["job_id"]
        row = {
            "job_id": job, "document_id": self.job["snapshot"]["plan"]["document_id"],
            "profile_version": FINANCIAL_PROFILE.version, "revision": 0, "status": "ready",
        }
        current = {**self.job, "round": None, "pending_request": None}
        responses = iter([config, {"jobs": [row]}, current])
        self.handler = lambda request: httpx.Response(200, json=next(responses))
        with self.client as client:
            self.assertEqual(client.configuration(), config)
            self.assertEqual(client.jobs(), (row,))
            self.assertEqual(client.current(job), current)
        self.assertTrue(self.client._client.is_closed)
        self.assertEqual([request.method for request in self.requests], ["GET"] * 3)

    def test_start_fixed_uuid_absolute_deadline_and_retry_never_renews(self):
        import httpx

        job = self.job["job_id"]
        self.handler = lambda request: httpx.Response(
            202, json={"authorization": authorization(json.loads(request.content), job)},
        )
        first = self.client.start(job, max_attempts=2, duration_seconds=60)
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["deadline"], 1060)
        self.assertEqual(body["expected_revision"], 0)
        self.assertTrue(body["request_id"].startswith("configured-round-"))
        self.now = 5000
        second = self.client.retry(job, body)
        self.assertEqual(first, second)
        self.assertEqual(self.requests[0].content, self.requests[1].content)
        self.assertEqual(json.loads(self.requests[1].content)["deadline"], 1060)
        self.assertEqual(len(self.requests), 2)

    def test_resume_uses_exact_predecessor_and_latest_revision(self):
        import httpx

        job = self.job["job_id"]
        original = {
            "action": "start", "job_id": job, "request_id": "first", "expected_revision": 0,
            "max_attempts": 1, "deadline": 1020,
        }
        run = authorization(original, job)
        current = {
            **self.job, "snapshot": {**self.job["snapshot"], "revision": 1},
            "round": {"authorization": run, "state": "limited", "attempts_reserved": 1, "registration_confirmed": True},
            "pending_request": None,
        }
        self.handler = lambda request: httpx.Response(
            202, json={"authorization": authorization(json.loads(request.content), job)},
        )
        self.client.resume(current, max_attempts=3, duration_seconds=90)
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["run_id"], run["run_id"])
        self.assertEqual(body["expected_revision"], 1)
        self.assertEqual(body["deadline"], 1090)
        self.assertEqual(body["max_attempts"], 3)
        current["round"]["state"] = "completed"
        self.assert_code("invalid_request", lambda: self.client.resume(current, max_attempts=1, duration_seconds=20))
        self.assertEqual(len(self.requests), 1)

    def test_timeout_ambiguous_mutation_is_safe_and_never_automatically_retried(self):
        import httpx

        def timeout(request):
            raise httpx.ReadTimeout("PRIVATE token=" + TOKEN)

        self.handler = timeout
        self.assert_code(
            "mutation_unconfirmed",
            lambda: self.client.start(self.job["job_id"], max_attempts=1, duration_seconds=30),
        )
        self.assertEqual(len(self.requests), 1)
        self.assert_code("backend_unavailable", lambda: self.client.current(self.job["job_id"]))
        self.assertEqual(len(self.requests), 2)

    def test_registration_unknown_expiration_and_server_errors_only_expose_known_codes(self):
        import httpx

        for code in ("batch_registration_unknown", "saved_request_expired", "model_disabled", "model_budget_exhausted"):
            self.handler = lambda request: httpx.Response(
                503 if code == "batch_registration_unknown" else 409,
                json={"error": {"code": code, "message": "PRIVATE " + TOKEN}},
            )
            self.assert_code(
                code, lambda: self.client.start(self.job["job_id"], max_attempts=1, duration_seconds=30),
            )
        self.handler = lambda request: httpx.Response(500, json={"error": {"code": "PRIVATE " + TOKEN}})
        self.assert_code(
            "mutation_unconfirmed",
            lambda: self.client.start(self.job["job_id"], max_attempts=1, duration_seconds=30),
        )
        self.handler = lambda request: httpx.Response(500, json={"error": {"code": "internal_error"}})
        self.assert_code(
            "mutation_unconfirmed",
            lambda: self.client.start(self.job["job_id"], max_attempts=1, duration_seconds=30),
        )

    def test_redirect_never_follows_or_sends_credentials_elsewhere(self):
        import httpx

        self.handler = lambda request: httpx.Response(
            307, headers={"Location": "https://external.invalid/steal"}, text="PRIVATE " + TOKEN,
        )
        self.assert_code(
            "mutation_unconfirmed",
            lambda: self.client.prepare(b"fixture", kind="text", profile=FINANCIAL_PROFILE),
        )
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].url.host, "127.0.0.1")

    def test_duplicate_nonfinite_oversize_and_corrupt_responses_are_rejected(self):
        import httpx
        from information_extraction.configured_client import MAX_RESPONSE_BYTES

        for payload in (b'{"x":1,"x":2}', b'{"x":NaN}', b"[]", b" " * (MAX_RESPONSE_BYTES + 1)):
            self.handler = lambda request: httpx.Response(
                200, content=payload, headers={"Content-Type": "application/json"},
            )
            self.assert_code("backend_unavailable", self.client.configuration)
        self.handler = lambda request: httpx.Response(200, json={**self.job, "snapshot": {}})
        self.assert_code("invalid_response", lambda: self.client.current(self.job["job_id"]))
        self.assert_code(
            "mutation_unconfirmed",
            lambda: self.client.prepare(b"fixture", kind="text", profile=FINANCIAL_PROFILE),
        )

    def test_response_authorization_must_acknowledge_exact_request(self):
        import httpx

        def wrong(request):
            body = json.loads(request.content)
            run = authorization({**body, "deadline": body["deadline"] + 1}, self.job["job_id"])
            return httpx.Response(202, json={"authorization": run})

        self.handler = wrong
        self.assert_code(
            "mutation_unconfirmed",
            lambda: self.client.start(self.job["job_id"], max_attempts=1, duration_seconds=60),
        )

    def test_invalid_round_limits_and_retry_body_send_nothing(self):
        for attempts, duration in ((0, 60), (6, 60), (True, 60), (1, 0), (1, 301), (1, True)):
            self.assert_code(
                "invalid_request",
                lambda: self.client.start(self.job["job_id"], max_attempts=attempts, duration_seconds=duration),
            )
        self.assert_code("invalid_request", lambda: self.client.retry(self.job["job_id"], {"action": "start"}))
        self.assertEqual(self.requests, [])

    def test_injected_http_client_has_no_default_auth_params_or_redirects_and_stays_owned_by_caller(self):
        import httpx
        from information_extraction.configured_client import ConfiguredClient

        def handle(request):
            self.requests.append(request)
            return httpx.Response(200, json={**self.job, "round": None, "pending_request": None})

        with httpx.Client(
            transport=httpx.MockTransport(handle), params={"credential": "unwanted"},
            auth=("username", "password"), follow_redirects=True,
        ) as injected:
            with ConfiguredClient("http://127.0.0.1:8000", TOKEN, http_client=injected) as client:
                client.current(self.job["job_id"])
            self.assertFalse(injected.is_closed)
        self.assertEqual(self.requests[0].url.query, b"")
        self.assertEqual(self.requests[0].headers["authorization"], "Bearer " + TOKEN)
