import asyncio
from contextlib import AsyncExitStack, contextmanager
from dataclasses import asdict
import importlib.util
import json
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from information_extraction.codec import _json
from information_extraction.contracts import ModelResponse, TokenUsage
from information_extraction.profiles import FINANCIAL_PROFILE, SUPPORT_PROFILE
from information_extraction.sample import synthetic_plan
from information_extraction.sqlite_store import SQLiteStore

try:
    SDK_AVAILABLE = importlib.util.find_spec("azure.ai.agentserver.invocations") is not None
except ModuleNotFoundError:
    SDK_AVAILABLE = False

TOKEN = "fixture-only-configured-token-0123456789"


class FixtureProvider:
    """Explicit test injection: no credentials, network, or real model."""

    enabled = True
    description = "Fixture only"
    remaining_calls = 50

    def __init__(self):
        self.opened = []
        self.calls = []
        self.response = {"records": []}

    def binding(self, profile):
        return "fixture-" + profile.version

    @contextmanager
    def open(self, profile):
        self.opened.append(profile)
        provider = self

        class Model:
            binding = provider.binding(profile)

            def complete(self, request):
                provider.calls.append(request)
                return ModelResponse(provider.response, TokenUsage(1, 1))

        yield Model()


@unittest.skipUnless(SDK_AVAILABLE, "optional native SDK not installed")
class ConfiguredAppTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from azure.ai.agentserver.core.tasks import resilient_tasks_enabled, set_resilient_tasks_enabled
        from azure.ai.agentserver.core.tasks._decorator import _REGISTERED_DESCRIPTORS

        enabled = resilient_tasks_enabled()
        descriptors = list(_REGISTERED_DESCRIPTORS)
        self.restore_registry = lambda: _REGISTERED_DESCRIPTORS.__setitem__(slice(None), descriptors)
        self.addCleanup(self.restore_registry)
        self.addCleanup(set_resilient_tasks_enabled, enabled)
        factory = logging.getLogRecordFactory()
        self.addCleanup(lambda: self.assertIs(logging.getLogRecordFactory(), factory))
        Path(".test-data").mkdir(exist_ok=True)
        self.directory = Path(self.enterContext(TemporaryDirectory(dir=".test-data")))
        self.enterContext(patch.dict(os.environ, {
            "AGENTSERVER_TASKS_BACKEND": "local",
            "AGENTSERVER_STATE_ROOT": str((self.directory / "native-state").resolve()),
            "AGENTSERVER_SHUTDOWN_GRACE_SECONDS": "1",
            "FOUNDRY_HOSTING_ENVIRONMENT": "",
            "FOUNDRY_AGENT_NAME": "configured-fixture",
            "FOUNDRY_AGENT_VERSION": "1",
            "FOUNDRY_AGENT_SESSION_ID": "offline",
            "FOUNDRY_PROJECT_ENDPOINT": "",
            "FOUNDRY_PROJECT_ARM_ID": "",
            "APPLICATIONINSIGHTS_CONNECTION_STRING": "",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "",
            "PORT": "8000",
            "SSE_KEEPALIVE_INTERVAL": "0",
            "WS_KEEPALIVE_INTERVAL": "0",
        }))
        self.now = 1000.0
        self.provider = FixtureProvider()
        self.store = SQLiteStore(self.directory / "ledger.sqlite3")
        self.enterContext(patch("socket.socket.connect", side_effect=AssertionError("live_network_forbidden")))
        self.stack = AsyncExitStack()
        self.addAsyncCleanup(self.close)
        await self.open_host()

    async def close(self):
        await self.stack.aclose()

    async def open_host(self):
        import httpx
        from information_extraction.configured_app import create_configured_app

        self.app = create_configured_app(self.store, self.provider, token=TOKEN, clock=lambda: self.now)
        await self.stack.enter_async_context(self.app.router.lifespan_context(self.app))
        self.client = await self.stack.enter_async_context(httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://127.0.0.1:8000",
            headers={"Authorization": "Bearer " + TOKEN},
        ))

    def body(self, content="Fixture evidence.", profile=FINANCIAL_PROFILE, **kwargs):
        return {
            "kind": "text", "content": content, "profile": json.loads(_json(asdict(profile))),
            "split": "train", "conversation_id": None, **kwargs,
        }

    async def prepare(self, **kwargs):
        response = await self.client.post("/jobs", json=self.body(**kwargs))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def current(self, job_id):
        response = await self.client.get("/jobs/" + job_id)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def start_body(self, job_id, **kwargs):
        return {
            "action": "start", "job_id": job_id, "request_id": "fixture-start",
            "expected_revision": 0, "max_attempts": 1, "deadline": self.now + 60,
            **kwargs,
        }

    async def submit(self, job_id, body):
        return await self.client.post("/jobs/" + job_id + "/round", json=body)

    async def wait_for(self, job_id, state):
        async with asyncio.timeout(10):
            while True:
                result = await self.current(job_id)
                if result["round"] is not None and result["round"]["state"] == state:
                    return result
                await asyncio.sleep(0.01)

    async def test_prepare_profiles_exact_replay_catalog_and_read_never_open_model(self):
        config = await self.client.get("/configuration")
        self.assertEqual(config.status_code, 200)
        self.assertEqual(set(config.json()["profiles"]), {"financial", "support"})
        first = await self.prepare(content="\ufeffRevenue is 10.\r\n")
        duplicate = await self.prepare(content="\ufeffRevenue is 10.\r\n")
        second = await self.prepare(profile=SUPPORT_PROFILE)
        self.assertEqual(first, duplicate)
        self.assertNotEqual(first["job_id"], second["job_id"])
        with (
            patch.object(self.store, "create", side_effect=AssertionError("read_created")),
            patch.object(self.store, "create_batch_record", side_effect=AssertionError("read_wrote")),
            patch("azure.ai.agentserver.core.tasks.Task.get_active_run", side_effect=AssertionError("scheduled")),
        ):
            current = await self.current(first["job_id"])
            jobs = await self.client.get("/jobs")
        self.assertIsNone(current["round"])
        self.assertIsNone(current["pending_request"])
        self.assertEqual(current["snapshot"], first["snapshot"])
        self.assertEqual([j["job_id"] for j in jobs.json()["jobs"]], [second["job_id"], first["job_id"]])
        self.assertEqual(first["snapshot"]["plan"]["model_binding"], self.provider.binding(FINANCIAL_PROFILE))
        self.assertEqual(second["snapshot"]["plan"]["model_binding"], self.provider.binding(SUPPORT_PROFILE))
        self.assertEqual(self.provider.opened, [])
        self.assertEqual(self.provider.calls, [])

    async def test_abcd_selected_dialogue_profile_binding_omits_hidden_labels(self):
        content = json.dumps([{
            "convo_id": 7,
            "original": [["customer", "My package is missing."], ["agent", "I will check."]],
            "scenario": {"secret": "NEVER EVIDENCE"}, "delexed": ["NEVER EVIDENCE"],
        }])
        prepared = await self.prepare(
            content=content, profile=SUPPORT_PROFILE, kind="abcd", conversation_id=7,
        )
        plan = prepared["snapshot"]["plan"]
        self.assertEqual(plan["model_binding"], self.provider.binding(SUPPORT_PROFILE))
        self.assertEqual(len(plan["chunks"]), 1)
        self.assertEqual([b["speaker"] for b in plan["chunks"][0]["blocks"]], ["customer", "agent"])
        self.assertNotIn("NEVER EVIDENCE", json.dumps(plan))
        self.assertEqual(self.provider.opened, [])

    async def test_native_limit_resume_completion_and_exact_replay(self):
        prepared = await self.prepare(content=("x" * 5000 + "\n") * 2)
        job = prepared["job_id"]
        body = self.start_body(job)
        response = await self.submit(job, body)
        self.assertEqual(response.status_code, 202, response.text)
        limited = await self.wait_for(job, "limited")
        self.assertEqual(limited["snapshot"]["revision"], 1)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual((await self.submit(job, body)).json(), response.json())
        resume = {
            "action": "resume", "run_id": limited["round"]["authorization"]["run_id"],
            "expected_revision": 1, "request_id": "fixture-resume",
            "max_attempts": 1, "deadline": 1080,
        }
        resumed = await self.submit(job, resume)
        self.assertEqual(resumed.status_code, 202, resumed.text)
        completed = await self.wait_for(job, "completed")
        self.assertEqual(completed["snapshot"]["revision"], 2)
        self.assertEqual(len(self.provider.calls), 2)
        self.assertEqual((await self.submit(job, resume)).json(), resumed.json())
        self.assertIsNone(completed["pending_request"])

    async def test_native_support_result_contains_typed_candidates_original_speakers_and_evidence(self):
        content = json.dumps([{
            "convo_id": 8,
            "original": [["customer", "My package is missing."], ["agent", "I will check."]],
        }])
        job = (await self.prepare(
            content=content, profile=SUPPORT_PROFILE, kind="abcd", conversation_id=8,
        ))["job_id"]
        fields = {
            "customer_issue_or_request": "My package is missing.", "product_or_service": None,
            "attempted_action": None, "stated_outcome": None, "outcome_status": None,
        }
        self.provider.response = {"records": [{
            "fields": fields,
            "evidence": {key: ["turn-1"] if value is not None else [] for key, value in fields.items()},
        }]}
        self.assertEqual((await self.submit(job, self.start_body(job))).status_code, 202)
        result = await self.wait_for(job, "completed")
        candidate = result["snapshot"]["candidates"][0]
        self.assertEqual(
            {field["name"]: field["value"] for field in candidate["record"]["fields"]}, fields,
        )
        self.assertEqual(candidate["evidence"][0]["text"], "My package is missing.")
        self.assertEqual(candidate["review_status"], "pending")
        self.assertFalse(candidate["semantic_validation_performed"])
        self.assertEqual(self.provider.opened, [SUPPORT_PROFILE])

    async def test_restart_current_is_read_only_then_resume(self):
        prepared = await self.prepare(content=("x" * 5000 + "\n") * 2)
        job = prepared["job_id"]
        await self.submit(job, self.start_body(job))
        limited = await self.wait_for(job, "limited")
        await self.stack.aclose()
        self.restore_registry()
        self.stack = AsyncExitStack()
        self.provider = FixtureProvider()
        self.store = SQLiteStore(self.directory / "ledger.sqlite3")
        await self.open_host()
        self.assertEqual(await self.current(job), limited)
        self.assertEqual(self.provider.calls, [])
        resume = {
            "action": "resume", "run_id": limited["round"]["authorization"]["run_id"],
            "expected_revision": 1, "request_id": "restart-resume", "max_attempts": 1, "deadline": 1060,
        }
        self.assertEqual((await self.submit(job, resume)).status_code, 202)
        await self.wait_for(job, "completed")
        self.assertEqual(len(self.provider.calls), 1)

    async def test_auth_origin_query_rejected_and_health_only_readiness(self):
        health = await self.client.get("/health", headers={"Authorization": ""})
        self.assertEqual(health.json(), {"ready": True})
        for path in ("/configuration", "/jobs", "/jobs/missing", "/readiness", "/invocations/docs/openapi.json"):
            for header in ("", "Bearer wrong", "Basic " + TOKEN):
                response = await self.client.get(path, headers={"Authorization": header})
                self.assertEqual(response.status_code, 401)
                self.assertNotIn(TOKEN, response.text)
        self.assertEqual((await self.client.get("/jobs", headers={"Origin": "null"})).status_code, 403)
        self.assertEqual((await self.client.get("/jobs?token=" + TOKEN)).status_code, 400)
        self.assertNotIn("access-control-allow-origin", health.headers)
        self.assertEqual(self.provider.calls, [])

    async def test_strict_invalid_json_shapes_sizes_and_types(self):
        for content in (b'{"kind":"text","kind":"abcd"}', b'{"x":NaN}', b'{"x":Infinity}', b"[]", b"\xff"):
            response = await self.client.post("/jobs", content=content, headers={"Content-Type": "application/json"})
            self.assertEqual(response.status_code, 400, response.text)
        invalid = [
            {**self.body(), "path": "C:\\private.txt"},
            {**self.body(), "url": "https://example.org"},
            {**self.body(), "kind": ["text"]},
            {**self.body(), "content": 42},
            {**self.body(), "conversation_id": True},
            {**self.body(), "profile": {"arbitrary": "schema"}},
            {**self.body(), "content": "x" * (32 * 1024 + 1)},
            {**self.body(), "content": "\ud800"},
        ]
        for body in invalid:
            response = await self.client.post(
                "/jobs", content=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
            )
            self.assertEqual(response.status_code, 400, response.text)
        too_large = await self.client.post(
            "/jobs", content=b" " * (512 * 1024 + 1), headers={"Content-Type": "application/json"},
        )
        self.assertEqual(too_large.status_code, 413)

        async def stream():
            for _ in range(9):
                yield b" " * (64 * 1024)

        streamed = await self.client.post("/jobs", content=stream(), headers={"Content-Type": "application/json"})
        self.assertEqual(streamed.status_code, 413)
        self.assertEqual((await self.client.post("/jobs", content="{}")).status_code, 415)
        self.assertEqual(self.provider.opened, [])

    async def test_prepare_only_and_exhaustion_reject_before_intent_or_admission(self):
        prepared = await self.prepare()
        job = prepared["job_id"]
        for enabled, remaining, code in (
            (False, 0, "model_disabled"), (True, 0, "model_budget_exhausted"),
        ):
            self.provider.enabled, self.provider.remaining_calls = enabled, remaining
            with patch.object(self.store, "create_batch_record", side_effect=AssertionError("admitted")):
                response = await self.submit(job, self.start_body(job))
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["error"]["code"], code)
            self.assertIsNone((await self.current(job))["pending_request"])
        self.assertEqual(self.provider.opened, [])

    async def test_disabled_resume_does_not_persist_a_successor_intent(self):
        job = (await self.prepare(content=("x" * 5000 + "\n") * 2))["job_id"]
        await self.submit(job, self.start_body(job))
        limited = await self.wait_for(job, "limited")
        self.provider.enabled = False
        resume = {
            "action": "resume", "run_id": limited["round"]["authorization"]["run_id"],
            "expected_revision": 1, "request_id": "disabled-resume", "max_attempts": 1, "deadline": 1060,
        }
        with patch.object(self.store, "create_batch_record", side_effect=AssertionError("admitted")):
            response = await self.submit(job, resume)
        self.assertEqual(response.json()["error"]["code"], "model_disabled")
        self.assertIsNone((await self.current(job))["pending_request"])
        self.assertEqual(len(self.provider.calls), 1)

    async def test_changed_model_binding_blocks_new_start_and_resume_before_admission_but_not_reads(self):
        job = (await self.prepare(content=("x" * 5000 + "\n") * 2))["job_id"]
        body = self.start_body(job)
        with (
            patch.object(self.provider, "binding", return_value="different-model-settings"),
            patch.object(self.store, "create_batch_record", side_effect=AssertionError("admitted")),
        ):
            response = await self.submit(job, body)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["error"]["code"], "execution_conflict")
            self.assertIsNone((await self.current(job))["pending_request"])
        self.assertEqual(self.provider.opened, [])
        self.assertEqual((await self.submit(job, body)).status_code, 202)
        limited = await self.wait_for(job, "limited")
        resume = {
            "action": "resume", "run_id": limited["round"]["authorization"]["run_id"],
            "expected_revision": 1, "request_id": "changed-binding-resume",
            "max_attempts": 1, "deadline": 1060,
        }
        with (
            patch.object(self.provider, "binding", return_value="different-model-settings"),
            patch.object(self.store, "create_batch_record", side_effect=AssertionError("admitted")),
        ):
            response = await self.submit(job, resume)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["error"]["code"], "execution_conflict")
            self.assertEqual(await self.current(job), limited)
        self.assertEqual(len(self.provider.calls), 1)

    async def test_round_shape_ownership_limits_and_new_deadlines(self):
        job = (await self.prepare())["job_id"]
        for changes, status in (
            ({"expected_revision": 1}, 409), ({"max_attempts": 6}, 400),
            ({"max_attempts": True}, 400), ({"deadline": 1301}, 400),
            ({"deadline": 1000}, 400), ({"job_id": "foreign"}, 409),
            ({"extra": "field"}, 400),
        ):
            response = await self.submit(job, {**self.start_body(job), **changes})
            self.assertEqual(response.status_code, status, response.text)
            self.assertIsNone((await self.current(job))["pending_request"])
        missing = await self.submit("configured-" + "0" * 64, self.start_body("configured-" + "0" * 64))
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(self.provider.calls, [])

    async def test_concurrent_different_intents_choose_one_before_scheduler_unknown(self):
        from information_extraction.native_batch import NativeScheduler

        job = (await self.prepare())["job_id"]
        first, second = self.start_body(job), self.start_body(job, request_id="another-browser")
        with patch.object(NativeScheduler, "schedule", side_effect=RuntimeError("private scheduler error")):
            responses = await asyncio.gather(self.submit(job, first), self.submit(job, second))
        self.assertEqual(sorted(response.status_code for response in responses), [409, 503])
        winner = next(response for response in responses if response.status_code == 503)
        current = await self.current(job)
        self.assertFalse(current["round"]["registration_confirmed"])
        self.assertEqual(current["round"]["authorization"], winner.json()["error"]["authorization"])
        expected = first if current["pending_request"]["request_id"] == first["request_id"] else second
        self.assertEqual(current["pending_request"], expected)
        self.assertNotIn("private scheduler error", winner.text)
        self.assertEqual(self.provider.calls, [])
        replay = await self.submit(job, expected)
        self.assertEqual(replay.status_code, 202, replay.text)
        await self.wait_for(job, "completed")
        self.assertEqual(len(self.provider.calls), 1)

    async def test_concurrent_resume_intents_and_lost_acknowledgement_do_not_duplicate_work(self):
        from information_extraction.native_batch import NativeScheduler

        job = (await self.prepare(content=("x" * 5000 + "\n") * 2))["job_id"]
        await self.submit(job, self.start_body(job))
        limited = await self.wait_for(job, "limited")
        resume = {
            "action": "resume", "run_id": limited["round"]["authorization"]["run_id"],
            "expected_revision": 1, "request_id": "resume-one", "max_attempts": 1, "deadline": 1060,
        }
        schedule = NativeScheduler.schedule

        async def lost_ack(scheduler, run_id):
            await schedule(scheduler, run_id)
            raise RuntimeError("private acknowledgement error")

        with patch.object(NativeScheduler, "schedule", new=lost_ack):
            responses = await asyncio.gather(
                self.submit(job, resume), self.submit(job, {**resume, "request_id": "resume-two"}),
            )
        self.assertEqual(sorted(response.status_code for response in responses), [409, 503])
        completed = await self.wait_for(job, "completed")
        self.assertEqual(len(self.provider.calls), 2)
        self.assertFalse(completed["round"]["registration_confirmed"])
        pending = completed["pending_request"]
        self.assertIn(pending["request_id"], ("resume-one", "resume-two"))
        self.assertEqual((await self.submit(job, pending)).status_code, 202)
        refreshed = await self.current(job)
        self.assertTrue(refreshed["round"]["registration_confirmed"])
        self.assertIsNone(refreshed["pending_request"])
        self.assertEqual(len(self.provider.calls), 2)

    async def test_corrupt_saved_intent_never_looks_missing_or_admits_a_new_request(self):
        from information_extraction.hosted_app import _intent_key

        job = (await self.prepare())["job_id"]
        self.store.create_batch_record(_intent_key(job, None), "null")
        with patch.object(self.store, "create_batch_record", side_effect=AssertionError("admitted")):
            current = await self.client.get("/jobs/" + job)
            submit = await self.submit(job, self.start_body(job))
        for response in (current, submit):
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.json()["error"]["code"], "stored_state_invalid")
        self.assertEqual(self.provider.calls, [])

    async def test_expired_saved_intent_cannot_be_replaced_or_renewed(self):
        from information_extraction.batch import Batch

        job = (await self.prepare())["job_id"]
        body = self.start_body(job)
        with patch.object(Batch, "start", side_effect=RuntimeError("lost before authorization")):
            failed = await self.submit(job, body)
        self.assertEqual(failed.status_code, 500)
        self.assertEqual((await self.current(job))["pending_request"], body)
        self.now = 1061
        expired = await self.submit(job, body)
        self.assertEqual(expired.status_code, 409)
        self.assertEqual(expired.json()["error"]["code"], "saved_request_expired")
        renewed = await self.submit(job, {**body, "deadline": 1120})
        self.assertEqual(renewed.status_code, 409)
        different = await self.submit(job, {**body, "request_id": "replacement", "deadline": 1120})
        self.assertEqual(different.status_code, 409)
        self.assertEqual((await self.current(job))["pending_request"], body)
        self.assertEqual(self.provider.calls, [])

    async def test_expired_authorization_retry_retains_deadline_and_does_no_model_work(self):
        from information_extraction.native_batch import NativeScheduler

        job = (await self.prepare())["job_id"]
        body = self.start_body(job)
        with patch.object(NativeScheduler, "schedule", side_effect=RuntimeError("unknown acknowledgement")):
            unknown = await self.submit(job, body)
        self.assertEqual(unknown.status_code, 503)
        self.now = 1061
        current = await self.current(job)
        self.assertEqual(current["pending_request"], body)
        self.assertFalse(current["round"]["registration_confirmed"])
        replay = await self.submit(job, body)
        self.assertEqual(replay.status_code, 202)
        limited = await self.wait_for(job, "limited")
        self.assertEqual(limited["round"]["authorization"]["limits"]["deadline"], 1060)
        self.assertEqual(limited["round"]["attempts_reserved"], 0)
        self.assertEqual(self.provider.calls, [])
        self.assertEqual((await self.submit(job, {**body, "deadline": 1120})).status_code, 409)

    async def test_dedicated_catalog_rejects_legacy_instead_of_hiding_it(self):
        self.store.create("legacy", synthetic_plan(), "legacy-create")
        response = await self.client.get("/jobs")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "stored_state_invalid")
        self.assertNotEqual((await self.client.get("/jobs/legacy")).status_code, 200)

    async def test_factory_requires_explicit_local_environment_and_strong_token(self):
        from information_extraction.configured_app import create_configured_app
        from information_extraction.contracts import InvalidInput

        for token in ("short", " " * 32, "é" * 32, "a" * 31 + "\n"):
            with self.assertRaises(InvalidInput):
                create_configured_app(self.store, self.provider, token=token)
        with patch.dict(os.environ, {"AGENTSERVER_TASKS_BACKEND": "hosted"}):
            with self.assertRaises(InvalidInput):
                create_configured_app(self.store, self.provider, token=TOKEN)
        self.assertIsNone(self.app._access_log)
        self.assertNotIn(
            "InboundRequestLoggingMiddleware", [middleware.cls.__name__ for middleware in self.app.user_middleware],
        )


class ConfiguredCatalogTests(unittest.TestCase):
    def test_catalog_is_newest_first_bounded_and_readonly(self):
        from information_extraction.configured_inputs import prepare_plan

        Path(".test-data").mkdir(exist_ok=True)
        with TemporaryDirectory(dir=".test-data") as directory:
            store = SQLiteStore(Path(directory) / "catalog.sqlite3")
            plan = prepare_plan(b"fixture", kind="text", profile=FINANCIAL_PROFILE, model_binding="fixture")
            for index in range(105):
                store.create(f"job-{index}", plan, f"create-{index}")
            with patch.object(store, "create_batch_record", side_effect=AssertionError("write")):
                rows = store.list_jobs()
            self.assertEqual(len(rows), 100)
            self.assertEqual([row.job_id for row in rows], [f"job-{index}" for index in range(104, 4, -1)])
