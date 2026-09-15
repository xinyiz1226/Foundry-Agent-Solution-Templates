import json
from copy import deepcopy
from copy import deepcopy
import unittest
from unittest.mock import patch

try:
    import httpx
except ImportError:
    httpx = None


ROUND = {
    "authorization": {
        "run_id": "run-1", "job_id": "synthetic-job", "request_id": "start-1",
        "plan_fingerprint": "fixture", "expected_revision": 0,
        "limits": {"max_attempts": 1, "deadline": 2000000000}, "previous_run_id": None,
    },
    "state": "limited", "execution_state": "ready", "revision": 1,
    "completed_chunks": ["chunk-1"], "attempts_reserved": 1, "committed_attempts": 1,
    "registration_confirmed": True,
    "usage": {"known_input_tokens": 0, "known_output_tokens": 0, "unknown_usage_attempts": 0},
    "candidates": [{
        "id": "candidate-1",
        "record": {"metric": "revenue", "value": 120, "unit": "USD_millions"},
        "evidence": [{"block_id": "block-1", "location": "synthetic:line:1",
                      "text": "ExampleCo revenue was USD 120 million."}],
        "review_status": "pending", "semantic_validation_performed": False,
    }],
}


@unittest.skipIf(httpx is None, "optional HTTP client not installed")
class WorkbenchClientTests(unittest.TestCase):
    def test_reopened_client_finds_no_job_without_starting_one(self):
        from information_extraction.workbench_client import WorkbenchClient

        requests = []

        def handle(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={
                "synthetic_only": True, "app_instance_id": "backend-1",
                "job_id": "synthetic-job", "current": None, "pending_request": None,
            })

        for _ in range(2):
            with WorkbenchClient(
                "http://127.0.0.1:8765", transport=httpx.MockTransport(handle),
            ) as client:
                current = client.current()
                self.assertEqual(current.job_id, "synthetic-job")
                self.assertIsNone(current.round)
                self.assertIsNone(current.pending)
        self.assertEqual(requests, [{"action": "current"}, {"action": "current"}])

    def test_discovery_restores_progress_and_source_evidence_without_a_run_id(self):
        from information_extraction.workbench_client import WorkbenchClient

        def handle(request):
            self.assertEqual(json.loads(request.content), {"action": "current"})
            return httpx.Response(200, json={
                "synthetic_only": True, "app_instance_id": "replacement-backend",
                "job_id": "synthetic-job", "current": ROUND, "pending_request": None,
            })

        with WorkbenchClient("http://127.0.0.1:8765", transport=httpx.MockTransport(handle)) as client:
            found = client.current()
        self.assertEqual(found.round.state, "limited")
        self.assertEqual(found.round.revision, 1)
        self.assertEqual(found.round.max_attempts, 1)
        self.assertEqual(found.round.candidates[0].value, 120)
        self.assertEqual(
            found.round.candidates[0].evidence[0].text,
            "ExampleCo revenue was USD 120 million.",
        )

    def test_only_explicit_start_and_resume_submit_bounded_commands(self):
        from information_extraction.workbench_client import WorkbenchClient

        commands = []

        def handle(request):
            body = json.loads(request.content)
            if body["action"] == "current":
                return httpx.Response(200, json={
                    "synthetic_only": True, "app_instance_id": "backend-1",
                    "job_id": "synthetic-job", "current": ROUND, "pending_request": None,
                })
            commands.append(body)
            authorization = deepcopy(ROUND["authorization"])
            authorization.update(
                request_id=body["request_id"], expected_revision=body["expected_revision"],
                limits={"max_attempts": body["max_attempts"], "deadline": body["deadline"]},
            )
            return httpx.Response(202, json={"synthetic_only": True, "authorization": authorization})

        with (
            WorkbenchClient("http://127.0.0.1:8765", transport=httpx.MockTransport(handle)) as client,
            patch("time.time", return_value=1000),
        ):
            found = client.current()
            self.assertEqual(commands, [])
            client.start(found.job_id, max_attempts=1, duration_seconds=120)
            client.resume(found.round, max_attempts=2, duration_seconds=60)
        self.assertEqual([body["action"] for body in commands], ["start", "resume"])
        self.assertEqual(commands[0]["job_id"], "synthetic-job")
        self.assertEqual(commands[0]["expected_revision"], 0)
        self.assertEqual(commands[0]["max_attempts"], 1)
        self.assertEqual(commands[0]["deadline"], 1120)
        self.assertEqual(commands[1]["run_id"], "run-1")
        self.assertEqual(commands[1]["expected_revision"], 1)
        self.assertEqual(commands[1]["deadline"], 1060)

    def test_reopened_client_retries_saved_intent_without_renewing_it(self):
        from information_extraction.workbench_client import WorkbenchClient

        saved = {
            "action": "start", "job_id": "synthetic-job", "request_id": "original-request",
            "expected_revision": 0, "max_attempts": 1, "deadline": 900,
        }
        commands = []

        def handle(request):
            body = json.loads(request.content)
            if body["action"] == "current":
                return httpx.Response(200, json={
                    "synthetic_only": True, "app_instance_id": "backend-1",
                    "job_id": "synthetic-job", "current": None, "pending_request": saved,
                })
            commands.append(body)
            return httpx.Response(202, json={
                "synthetic_only": True, "authorization": {
                    "run_id": "run-1", "request_id": "original-request",
                },
            })

        for _ in range(2):
            with WorkbenchClient("http://127.0.0.1:8765", transport=httpx.MockTransport(handle)) as client:
                found = client.current()
                self.assertEqual(found.pending.request_id, "original-request")
        self.assertEqual(commands, [])
        with (
            WorkbenchClient("http://127.0.0.1:8765", transport=httpx.MockTransport(handle)) as client,
            patch("time.time", return_value=1000),
        ):
            client.retry(found.pending)
        self.assertEqual(commands, [saved])

    def test_only_explicit_loopback_endpoints_are_allowed(self):
        from information_extraction.workbench_client import WorkbenchClient, WorkbenchError

        for endpoint in (
            "https://example.com", "http://localhost:8765", "http://127.0.0.1:0",
            "http://user:password@127.0.0.1:8765", "http://127.0.0.1:8765/path",
            "http://127.0.0.1:8765?key=secret",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(WorkbenchError):
                WorkbenchClient(endpoint)

    def test_transport_failure_is_visible_and_is_not_retried(self):
        from information_extraction.workbench_client import WorkbenchClient, WorkbenchError

        calls = []

        def fail(request):
            calls.append(request)
            raise httpx.ReadTimeout("private diagnostic", request=request)

        with WorkbenchClient("http://127.0.0.1:8765", transport=httpx.MockTransport(fail)) as client:
            with self.assertRaises(WorkbenchError) as raised:
                client.current()
        self.assertNotIn("private diagnostic", str(raised.exception))
        self.assertEqual(len(calls), 1)

    def test_invalid_or_failed_responses_do_not_look_like_an_empty_job(self):
        from information_extraction.workbench_client import WorkbenchClient, WorkbenchError

        for status, content in (
            (200, b'{"synthetic_only":true,"job_id":"synthetic-job"}'),
            (200, b'{"synthetic_only":true,"current":null,"current":{}}'),
            (200, b"x" * 65537),
            (200, b"[" * 1100 + b"0" + b"]" * 1100),
            (503, b'{"synthetic_only":true,"error":{"code":"execution_unavailable","detail":"private diagnostic"}}'),
            (307, b'{"synthetic_only":true}'),
        ):
            with self.subTest(status=status, size=len(content)):
                with WorkbenchClient(
                    "http://127.0.0.1:8765",
                    transport=httpx.MockTransport(lambda request: httpx.Response(status, content=content)),
                ) as client:
                    with self.assertRaises(WorkbenchError) as raised:
                        client.current()
                self.assertNotIn("private diagnostic", str(raised.exception))

    def test_inconsistent_progress_is_not_exposed_as_a_valid_round(self):
        from information_extraction.workbench_client import WorkbenchClient, WorkbenchError

        changes = (
            {"completed_chunks": ["chunk-1", "chunk-1", "chunk-2"]},
            {"attempts_reserved": 6},
            {"committed_attempts": 2},
            {"authorization": {**ROUND["authorization"], "limits": {"max_attempts": 1, "deadline": 10**100}}},
        )
        for change in changes:
            projection = deepcopy(ROUND)
            projection.update(change)
            with self.subTest(change=change), WorkbenchClient(
                "http://127.0.0.1:8765",
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
                    "synthetic_only": True, "app_instance_id": "backend-1",
                    "job_id": "synthetic-job", "current": projection, "pending_request": None,
                })),
            ) as client:
                with self.assertRaises(WorkbenchError):
                    client.current()

    def test_resumed_round_keeps_cumulative_commits_separate_from_its_allowance(self):
        from information_extraction.workbench_client import WorkbenchClient

        projection = deepcopy(ROUND)
        projection.update({
            "state": "completed", "execution_state": "completed", "revision": 2,
            "committed_attempts": 2, "completed_chunks": ["chunk-1", "chunk-2"],
        })
        with WorkbenchClient(
            "http://127.0.0.1:8765",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
                "synthetic_only": True, "app_instance_id": "backend-1",
                "job_id": "synthetic-job", "current": projection, "pending_request": None,
            })),
        ) as client:
            current = client.current()
        self.assertEqual(current.round.committed_attempts, 2)
        self.assertEqual(current.round.attempts_reserved, 1)
