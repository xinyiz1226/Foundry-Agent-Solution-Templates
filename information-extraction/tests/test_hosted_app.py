import asyncio
import gc
import importlib.util
import json
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch
from uuid import UUID

from information_extraction import Execution, FailureCode, ModelFailure, NotFound, SQLiteStore
from information_extraction.batch import Batch, BatchLimits
from information_extraction.codec import _hash, _json
from information_extraction.sample import synthetic_plan
from tests.test_batch import QueueScheduler
from tests.test_execution import SyntheticModel

try:
    INVOCATIONS_AVAILABLE = importlib.util.find_spec("azure.ai.agentserver.invocations") is not None
except ModuleNotFoundError:
    INVOCATIONS_AVAILABLE = False


@unittest.skipUnless(INVOCATIONS_AVAILABLE, "optional Invocations SDK not installed")
class HostedAppTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import httpx
        from azure.ai.agentserver.core.tasks import resilient_tasks_enabled, set_resilient_tasks_enabled
        from azure.ai.agentserver.core.tasks._decorator import _REGISTERED_DESCRIPTORS
        from information_extraction.hosted_app import create_offline_app

        enabled = resilient_tasks_enabled()
        descriptors = list(_REGISTERED_DESCRIPTORS)
        log_factory = logging.getLogRecordFactory()
        self.addCleanup(lambda: self.assertIs(logging.getLogRecordFactory(), log_factory))
        self.addCleanup(set_resilient_tasks_enabled, enabled)
        self.restore_task_registry = lambda: _REGISTERED_DESCRIPTORS.__setitem__(slice(None), descriptors)
        self.addCleanup(self.restore_task_registry)
        Path(".test-data").mkdir(exist_ok=True)
        self.directory = Path(self.enterContext(TemporaryDirectory(dir=".test-data")))
        self.enterContext(patch.dict(os.environ, {
            "AGENTSERVER_TASKS_BACKEND": "local",
            "AGENTSERVER_STATE_ROOT": str((self.directory / "native-state").resolve()),
            "AGENTSERVER_SHUTDOWN_GRACE_SECONDS": "1",
            "FOUNDRY_HOSTING_ENVIRONMENT": "",
            "FOUNDRY_AGENT_NAME": "synthetic-app-test",
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
        self.model = SyntheticModel()
        self.now = 1000.0
        self.store = self.make_store()
        self.app = create_offline_app(self.store, model=self.model, clock=lambda: self.now, job_id="job")
        lifespan = self.app.router.lifespan_context(self.app)
        self.lifespan = lifespan
        await lifespan.__aenter__()
        self.addAsyncCleanup(lifespan.__aexit__, None, None, None)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://in-process",
        )
        self.addAsyncCleanup(self.client.aclose)
        self.request = {
            "action": "start", "job_id": "job", "request_id": "start",
            "expected_revision": 0, "max_attempts": 5, "deadline": 1060.0,
        }

    def make_store(self):
        return SQLiteStore(self.directory / "ledger.sqlite3")

    async def status(self, run_id):
        response = await self.client.post("/invocations", json={"action": "status", "run_id": run_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def current(self):
        response = await self.client.post("/invocations", json={"action": "current"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_current_of_missing_or_rootless_job_is_read_only_and_strict(self):
        with (
            patch.object(self.store, "create", side_effect=AssertionError("read_must_not_create")),
            patch.object(self.store, "create_batch_record", side_effect=AssertionError("read_must_not_write")),
            patch("azure.ai.agentserver.core.tasks.Task.get_active_run", side_effect=AssertionError("read_must_not_schedule")),
        ):
            missing = await self.current()
        self.assertEqual(missing["job_id"], "job")
        self.assertIsNone(missing["current"])
        self.assertIsNone(missing["pending_request"])
        self.assertTrue(missing["synthetic_only"])
        with self.assertRaises(NotFound):
            Execution(self.store, self.model).read("job")
        Execution(self.store, self.model).create("job", synthetic_plan(), "fixture")
        self.assertEqual(await self.current(), missing)
        invalid = await self.client.post("/invocations", json={"action": "current", "job_id": "job"})
        self.assertEqual(invalid.status_code, 400, invalid.text)
        self.assertEqual(self.model.calls, [])

    async def test_corrupt_discovery_records_neither_look_missing_nor_allow_a_new_start(self):
        read = self.store.read_batch_record
        root = _hash(_json(["root", "job"]))
        intent = _hash(_json(["synthetic-invocation-slot-v1", "job", None]))
        for key, payload in (
            (root, "null"),
            (root, _json({"run_id": "missing"})),
            (intent, "null"),
            (intent, _json({
                "version": 1, "job_id": "job", "body": {**self.request, "job_id": "foreign"},
            })),
        ):
            with (
                patch.object(
                    self.store, "read_batch_record",
                    side_effect=lambda requested: payload if requested == key else read(requested),
                ),
                patch.object(self.store, "create", side_effect=AssertionError("corruption_must_not_create")),
                patch.object(self.store, "create_batch_record", side_effect=AssertionError("corruption_must_not_write")),
            ):
                for request in ({"action": "current"}, self.request):
                    rejected = await self.client.post("/invocations", json=request)
                    self.assertEqual(rejected.status_code, 500, rejected.text)
                    self.assertEqual(rejected.json()["error"]["code"], "stored_state_invalid")
        self.assertEqual(self.model.calls, [])

    async def wait_for(self, run_id, state):
        async with asyncio.timeout(5):
            while True:
                result = await self.status(run_id)
                if result["state"] == state:
                    return result
                await asyncio.sleep(0.01)

    async def test_invocations_start_returns_before_model_and_status_observes_two_chunks(self):
        entered, release = Event(), Event()
        complete = self.model.complete

        def slow(request):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("synthetic_wait_timeout")
            return complete(request)

        self.model.complete = slow
        try:
            response = await asyncio.wait_for(
                self.client.post("/invocations", json=self.request), timeout=2,
            )
            self.assertEqual(response.status_code, 202, response.text)
            started = response.json()
            self.assertTrue(started["synthetic_only"])
            run_id = started["authorization"]["run_id"]
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            active = await self.status(run_id)
            self.assertEqual(active["state"], "in_progress_or_interrupted")
            replay = await self.client.post("/invocations", json=self.request)
            self.assertEqual(replay.status_code, 202, replay.text)
            self.assertEqual(replay.json(), started)
            self.assertEqual(self.model.calls, [])
        finally:
            release.set()
        completed = await self.wait_for(run_id, "completed")
        self.assertEqual(completed["revision"], 2)
        self.assertEqual(completed["completed_chunks"], ["chunk-1", "chunk-2"])
        self.assertEqual([c["record"]["value"] for c in completed["candidates"]], [120, 18])
        self.assertEqual(len(self.model.calls), 2)
        self.assertEqual(await self.status(run_id), completed)

    async def test_replacement_host_restores_fixed_job_without_work_then_explicitly_resumes(self):
        import httpx
        from information_extraction.hosted_app import create_offline_app

        request = {**self.request, "max_attempts": 1}
        response = await self.client.post("/invocations", json=request)
        self.assertEqual(response.status_code, 202, response.text)
        started = response.json()
        run_id = started["authorization"]["run_id"]
        limited = await self.wait_for(run_id, "limited")
        instance_id = started["app_instance_id"]
        self.assertEqual(UUID(instance_id).version, 4)
        self.assertEqual(limited["app_instance_id"], instance_id)
        self.assertEqual(len(self.model.calls), 1)
        old_model = self.model

        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)
        self.restore_task_registry()
        self.store = self.make_store()
        self.model = SyntheticModel()
        self.app = create_offline_app(self.store, model=self.model, clock=lambda: self.now, job_id="job")
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.addAsyncCleanup(self.lifespan.__aexit__, None, None, None)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://in-process",
        )
        self.addAsyncCleanup(self.client.aclose)

        discovered = await self.current()
        self.assertEqual(discovered["job_id"], "job")
        self.assertIsNone(discovered["pending_request"])
        self.assertEqual(discovered["current"]["authorization"]["run_id"], run_id)
        restored = await self.status(discovered["current"]["authorization"]["run_id"])
        self.assertNotEqual(restored["app_instance_id"], instance_id)
        self.assertEqual(UUID(restored["app_instance_id"]).version, 4)
        self.assertEqual({**restored, "app_instance_id": instance_id}, limited)
        replay = await self.client.post("/invocations", json=request)
        self.assertEqual(replay.status_code, 202, replay.text)
        self.assertEqual(replay.json()["authorization"], started["authorization"])
        self.assertEqual(replay.json()["app_instance_id"], restored["app_instance_id"])
        self.assertEqual(self.model.calls, [])

        rejected = await self.client.post("/invocations", json={**request, "job_id": "other-job"})
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(rejected.json()["app_instance_id"], restored["app_instance_id"])
        resumed = await self.client.post("/invocations", json={
            "action": "resume", "run_id": run_id, "request_id": "replacement-resume",
            "expected_revision": 1, "max_attempts": 1, "deadline": 1060,
        })
        self.assertEqual(resumed.status_code, 202, resumed.text)
        completed = await self.wait_for(resumed.json()["authorization"]["run_id"], "completed")
        self.assertEqual([candidate["record"]["value"] for candidate in completed["candidates"]], [120, 18])
        self.assertEqual(completed["app_instance_id"], restored["app_instance_id"])
        self.assertEqual((len(old_model.calls), len(self.model.calls)), (1, 1))

    async def test_invalid_json_shapes_types_and_limits_reject_before_mutation(self):
        cases = [
            "{", "null", "[]", '{"action":"unknown"}',
            json.dumps({**self.request, "model": "forbidden-real-model"}),
            json.dumps({key: value for key, value in self.request.items() if key != "deadline"}),
            json.dumps(self.request)[:-1] + ',"action":"status"}',
        ]
        for key, values in {
            "expected_revision": [True, -1, 1.5, 2**63],
            "max_attempts": [True, 0, 6, 1.5],
            "deadline": [True, -1, 999, 9999999, float("nan"), float("inf")],
            "job_id": ["", "bad/id", None],
        }.items():
            cases.extend(json.dumps({**self.request, key: value}) for value in values)
        for body in cases:
            with self.subTest(body=body):
                response = await self.client.post(
                    "/invocations", content=body, headers={"content-type": "application/json"},
                )
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertEqual(self.model.calls, [])
        with self.assertRaises(NotFound):
            Execution(self.store, self.model).read("job")

    async def test_body_size_bound_is_enforced_even_without_a_truthful_content_length(self):
        for headers in (
            {"content-type": "application/json"},
            {"content-type": "application/json", "content-length": "1"},
        ):
            response = await self.client.post("/invocations", content=b" " * 16385, headers=headers)
            self.assertEqual(response.status_code, 413, response.text)
            self.assertEqual(response.json()["error"]["code"], "request_too_large")

        async def chunks():
            for _ in range(3):
                yield b" " * 8192

        streamed = await self.client.post(
            "/invocations", content=chunks(), headers={"content-type": "application/json"},
        )
        self.assertEqual(streamed.status_code, 413, streamed.text)
        self.assertEqual(self.model.calls, [])
        with self.assertRaises(NotFound):
            Execution(self.store, self.model).read("job")

    async def test_limited_round_requires_explicit_resume_and_preserves_expired_start_replay(self):
        request = {**self.request, "max_attempts": 1}
        first = await self.client.post("/invocations", json=request)
        self.assertEqual(first.status_code, 202, first.text)
        first_body = first.json()
        first_id = first_body["authorization"]["run_id"]
        limited = await self.wait_for(first_id, "limited")
        self.assertEqual(limited["attempts_reserved"], 1)
        self.now = 1061
        replay = await self.client.post("/invocations", json=request)
        self.assertEqual(replay.status_code, 202, replay.text)
        self.assertEqual(replay.json(), first_body)
        self.assertEqual(len(self.model.calls), 1)
        resume = {
            "action": "resume", "run_id": first_id, "request_id": "resume",
            "expected_revision": 1, "max_attempts": 1, "deadline": 1120,
        }
        second = await self.client.post("/invocations", json=resume)
        self.assertEqual(second.status_code, 202, second.text)
        completed = await self.wait_for(second.json()["authorization"]["run_id"], "completed")
        self.assertEqual(completed["candidates"][0], limited["candidates"][0])
        self.assertEqual(len(self.model.calls), 2)
        self.assertEqual(await self.status(first_id), limited)
        repeated_resume = await self.client.post("/invocations", json=resume)
        self.assertEqual(repeated_resume.json(), second.json())
        stale = await self.client.post(
            "/invocations", json={**resume, "request_id": "stale-resume", "expected_revision": 0},
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        conflicting = await self.client.post("/invocations", json={**request, "deadline": 1120})
        self.assertEqual(conflicting.status_code, 409, conflicting.text)
        self.assertEqual(len(self.model.calls), 2)

    async def test_registration_unknown_is_safe_http_503_with_persisted_retry_identity(self):
        with patch(
            "azure.ai.agentserver.core.tasks.Task.start",
            side_effect=TimeoutError("secret_sdk_diagnostic"),
        ):
            failed = await self.client.post("/invocations", json=self.request)
        self.assertEqual(failed.status_code, 503, failed.text)
        error = failed.json()["error"]
        self.assertEqual(error["code"], "batch_registration_unknown")
        self.assertNotIn("secret", failed.text)
        run_id = error["authorization"]["run_id"]
        with patch(
            "azure.ai.agentserver.core.tasks.Task.get_active_run",
            side_effect=AssertionError("status_must_not_reclaim"),
        ):
            pending = await self.status(run_id)
            recovered = await self.current()
        self.assertEqual(recovered["current"]["authorization"]["run_id"], run_id)
        self.assertEqual(recovered["pending_request"], self.request)
        self.assertFalse(pending["registration_confirmed"])
        self.assertEqual(self.model.calls, [])
        retried = await self.client.post("/invocations", json=self.request)
        self.assertEqual(retried.status_code, 202, retried.text)
        self.assertEqual(retried.json()["authorization"], error["authorization"])
        await self.wait_for(run_id, "completed")
        self.assertEqual(len(self.model.calls), 2)

    async def test_pre_index_rounds_are_discovered_without_migration_or_scheduling(self):
        execution = Execution(self.store, self.model)
        execution.create("job", synthetic_plan(), "legacy-create")
        scheduler = QueueScheduler()
        batch = Batch(execution, self.store, scheduler, clock=lambda: self.now)
        request = {**self.request, "max_attempts": 1}
        first = await batch.start("job", 0, "start", BatchLimits(max_attempts=1, deadline=1060.0))
        with patch.object(self.store, "create_batch_record", side_effect=AssertionError("no_migration_writes")):
            current = await self.current()
        self.assertEqual(current["pending_request"], request)
        self.assertEqual(current["current"]["authorization"]["run_id"], first.run_id)
        batch.run(first.run_id)
        second = await batch.resume(first.run_id, 1, "resume", BatchLimits(max_attempts=1, deadline=1060))
        with patch.object(self.store, "create_batch_record", side_effect=AssertionError("no_migration_writes")):
            resumed = await self.current()
        self.assertEqual(resumed["pending_request"], {
            "action": "resume", "run_id": first.run_id, "request_id": "resume",
            "expected_revision": 1, "max_attempts": 1, "deadline": 1060,
        })
        self.assertEqual(resumed["current"]["authorization"]["run_id"], second.run_id)
        self.assertEqual(len(scheduler.deliveries), 2)
        self.assertEqual(len(self.model.calls), 1)

    async def test_legacy_committed_start_and_resume_replay_after_deadline_without_new_budget(self):
        execution = Execution(self.store, self.model)
        execution.create("job", synthetic_plan(), "legacy-create")
        batch = Batch(execution, self.store, QueueScheduler(), clock=lambda: self.now)
        first = await batch.start("job", 0, "start", BatchLimits(max_attempts=1, deadline=1060.0))
        batch.run(first.run_id)
        second = await batch.resume(first.run_id, 1, "resume", BatchLimits(max_attempts=1, deadline=1060))
        batch.run(second.run_id)
        self.now = 1061
        for request, run in (
            ({**self.request, "max_attempts": 1}, first),
            ({
                "action": "resume", "run_id": first.run_id, "request_id": "resume",
                "expected_revision": 1, "max_attempts": 1, "deadline": 1060,
            }, second),
        ):
            replay = await self.client.post("/invocations", json=request)
            self.assertEqual(replay.status_code, 202, replay.text)
            self.assertEqual(replay.json()["authorization"]["run_id"], run.run_id)
        self.assertEqual((await self.current())["current"]["authorization"]["run_id"], second.run_id)
        self.assertIsNone((await self.current())["pending_request"])
        self.assertEqual(len(self.model.calls), 2)

    async def test_root_intent_survives_loss_before_per_request_receipt_in_replacement_app(self):
        await self.lost_root_intent("receipt")

    async def test_root_intent_survives_lost_index_write_ack_in_replacement_app(self):
        await self.lost_root_intent("index_ack")

    async def lost_root_intent(self, stage):
        import httpx
        from information_extraction.hosted_app import create_offline_app

        create = self.store.create_batch_record

        def interrupt(key, payload):
            value = json.loads(payload)
            if stage == "receipt" and "request" in value:
                raise RuntimeError("synthetic_loss_before_receipt")
            saved = create(key, payload)
            if stage == "index_ack" and "body" in value:
                raise RuntimeError("synthetic_lost_index_ack")
            return saved

        with patch.object(self.store, "create_batch_record", side_effect=interrupt):
            lost = await self.client.post("/invocations", json=self.request)
        self.assertEqual(lost.status_code, 503, lost.text)
        replacement_store = self.make_store()
        replacement = create_offline_app(
            replacement_store, model=SyntheticModel(), clock=lambda: self.now, job_id="job",
        )
        with (
            patch.object(replacement_store, "create_batch_record", side_effect=AssertionError("read_must_not_write")),
            patch.object(replacement_store, "create", side_effect=AssertionError("read_must_not_create")),
            patch("azure.ai.agentserver.core.tasks.Task.start", side_effect=AssertionError("read_must_not_schedule")),
            patch("azure.ai.agentserver.core.tasks.Task.get_active_run", side_effect=AssertionError("read_must_not_schedule")),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=replacement), base_url="http://replacement",
            ) as client:
                recovered = await client.post("/invocations", json={"action": "current"})
        self.assertEqual(recovered.status_code, 200, recovered.text)
        pending = recovered.json()
        self.assertIsNone(pending["current"])
        self.assertEqual(pending["pending_request"], self.request)
        with self.assertRaises(NotFound):
            Execution(replacement_store, self.model).read("job")
        retry = await self.client.post("/invocations", json=pending["pending_request"])
        self.assertEqual(retry.status_code, 202, retry.text)
        await self.wait_for(retry.json()["authorization"]["run_id"], "completed")
        self.assertIsNone((await self.current())["pending_request"])

    async def test_expired_uncommitted_intent_cannot_be_renewed_or_create_execution(self):
        with patch.object(self.store, "create", side_effect=RuntimeError("synthetic_loss")):
            interrupted = await self.client.post("/invocations", json=self.request)
        self.assertEqual(interrupted.status_code, 503, interrupted.text)
        self.now = 1061
        pending = await self.current()
        with patch.object(self.store, "create", side_effect=AssertionError("expired_must_not_create")):
            expired = await self.client.post("/invocations", json=pending["pending_request"])
        self.assertEqual(expired.status_code, 409, expired.text)
        self.assertEqual(expired.json()["error"]["code"], "saved_request_expired")
        replacement = await self.client.post(
            "/invocations", json={**self.request, "request_id": "replacement", "deadline": 1120},
        )
        self.assertEqual(replacement.status_code, 409, replacement.text)
        self.assertEqual((await self.current())["pending_request"], self.request)
        with self.assertRaises(NotFound):
            Execution(self.store, self.model).read("job")
        self.assertEqual(self.model.calls, [])

    async def test_lost_start_before_fixture_is_discoverable_and_only_exact_request_can_retry(self):
        with patch.object(self.store, "create", side_effect=RuntimeError("synthetic_process_loss")):
            interrupted = await self.client.post("/invocations", json=self.request)
        self.assertEqual(interrupted.status_code, 503, interrupted.text)
        with (
            patch.object(self.store, "create_batch_record", side_effect=AssertionError("read_must_not_write")),
            patch("azure.ai.agentserver.core.tasks.Task.get_active_run", side_effect=AssertionError("read_must_not_schedule")),
        ):
            pending = await self.current()
        self.assertIsNone(pending["current"])
        self.assertEqual(pending["pending_request"], self.request)
        self.assertEqual(self.model.calls, [])
        for changes in (
            {"request_id": "new-tab"}, {"deadline": 1120}, {"max_attempts": 1},
        ):
            rejected = await self.client.post("/invocations", json={**self.request, **changes})
            self.assertEqual(rejected.status_code, 409, rejected.text)
        retried = await self.client.post("/invocations", json=pending["pending_request"])
        self.assertEqual(retried.status_code, 202, retried.text)
        run_id = retried.json()["authorization"]["run_id"]
        await self.wait_for(run_id, "completed")
        finished = await self.current()
        self.assertEqual(finished["current"]["authorization"]["run_id"], run_id)
        self.assertIsNone(finished["pending_request"])
        self.assertEqual(len(self.model.calls), 2)

    async def test_lost_resume_before_receipt_keeps_terminal_history_and_exact_pending_intent(self):
        first = await self.client.post("/invocations", json={**self.request, "max_attempts": 1})
        first_id = first.json()["authorization"]["run_id"]
        limited = await self.wait_for(first_id, "limited")
        resume = {
            "action": "resume", "run_id": first_id, "request_id": "resume",
            "expected_revision": 1, "max_attempts": 1, "deadline": 1060,
        }
        create = self.store.create_batch_record

        def interrupt(key, payload):
            if json.loads(payload).get("action") == "resume":
                raise RuntimeError("synthetic_loss_before_receipt")
            return create(key, payload)

        with patch.object(self.store, "create_batch_record", side_effect=interrupt):
            lost = await self.client.post("/invocations", json=resume)
        self.assertEqual(lost.status_code, 503, lost.text)
        pending = await self.current()
        self.assertEqual(pending["current"]["state"], "limited")
        self.assertEqual(pending["current"]["candidates"], limited["candidates"])
        self.assertEqual(pending["pending_request"], resume)
        for changes in ({"request_id": "another-tab"}, {"deadline": 1120}, {"max_attempts": 2}):
            rejected = await self.client.post("/invocations", json={**resume, **changes})
            self.assertEqual(rejected.status_code, 409, rejected.text)
        retry = await self.client.post("/invocations", json=pending["pending_request"])
        self.assertEqual(retry.status_code, 202, retry.text)
        second_id = retry.json()["authorization"]["run_id"]
        await self.wait_for(second_id, "completed")
        discovered = await self.current()
        self.assertEqual(discovered["current"]["authorization"]["run_id"], second_id)
        self.assertIsNone(discovered["pending_request"])
        self.assertEqual(await self.status(first_id), limited)
        self.assertEqual(len(self.model.calls), 2)

    async def test_handled_failure_counts_and_explicit_resume_preserves_candidates(self):
        complete = self.model.complete

        def fail(request):
            if request.chunk.id == "chunk-2":
                self.model.calls.append(request)
                raise ModelFailure(FailureCode.MODEL_TIMEOUT)
            return complete(request)

        self.model.complete = fail
        started = await self.client.post("/invocations", json=self.request)
        run_id = started.json()["authorization"]["run_id"]
        failed = await self.wait_for(run_id, "failed")
        self.assertEqual(failed["attempts_reserved"], 2)
        self.assertEqual(failed["usage"]["unknown_usage_attempts"], 1)
        self.model.complete = complete
        resumed = await self.client.post("/invocations", json={
            "action": "resume", "run_id": run_id, "request_id": "resume",
            "expected_revision": 2, "max_attempts": 1, "deadline": 1060,
        })
        self.assertEqual(resumed.status_code, 202, resumed.text)
        finished = await self.wait_for(resumed.json()["authorization"]["run_id"], "completed")
        self.assertEqual(finished["candidates"][0], failed["candidates"][0])
        self.assertEqual(len(self.model.calls), 3)

    async def test_unknown_model_outcome_blocks_http_resume_without_blind_retry(self):
        def interrupt(request):
            self.model.calls.append(request)
            raise RuntimeError("secret_provider_diagnostic")

        self.model.complete = interrupt
        started = await self.client.post("/invocations", json=self.request)
        run_id = started.json()["authorization"]["run_id"]
        blocked = await self.wait_for(run_id, "in_progress_or_interrupted")
        self.assertEqual(blocked["usage"]["unknown_usage_attempts"], 1)
        with patch(
            "azure.ai.agentserver.core.tasks.Task.get_active_run",
            side_effect=AssertionError("inspection_must_not_reclaim"),
        ):
            recovered = await self.current()
        self.assertEqual(recovered["current"]["state"], "in_progress_or_interrupted")
        self.assertIsNone(recovered["pending_request"])
        resumed = await self.client.post("/invocations", json={
            "action": "resume", "run_id": run_id, "request_id": "unsafe-resume",
            "expected_revision": 0, "max_attempts": 5, "deadline": 1060,
        })
        self.assertEqual(resumed.status_code, 409, resumed.text)
        replay = await self.client.post("/invocations", json=self.request)
        self.assertEqual(replay.json(), started.json())
        self.assertNotIn("secret", json.dumps(blocked))
        self.assertEqual(len(self.model.calls), 1)

    async def test_terminal_round_with_lost_registration_receipt_is_not_a_pending_retry(self):
        execution = Execution(self.store, self.model)
        execution.create("job", synthetic_plan(), "legacy-create")
        batch = Batch(execution, self.store, QueueScheduler(), clock=lambda: self.now)
        run = await batch.start("job", 0, "start", BatchLimits(deadline=1060))
        batch.run(run.run_id)
        registered = _hash(_json(["registered", run.run_id]))
        read = self.store.read_batch_record
        with (
            patch.object(
                self.store, "read_batch_record",
                side_effect=lambda key: None if key == registered else read(key),
            ),
            patch.object(self.store, "create_batch_record", side_effect=AssertionError("read_must_not_write")),
            patch("azure.ai.agentserver.core.tasks.Task.start", side_effect=AssertionError("read_must_not_schedule")),
            patch("azure.ai.agentserver.core.tasks.Task.get_active_run", side_effect=AssertionError("read_must_not_schedule")),
        ):
            current = await self.current()
        self.assertEqual(current["current"]["state"], "completed")
        self.assertFalse(current["current"]["registration_confirmed"])
        self.assertIsNone(current["pending_request"])
        self.assertEqual(len(self.model.calls), 2)

    async def test_storage_and_unexpected_request_errors_are_sanitized(self):
        with patch.object(self.store, "read_batch_record", side_effect=RuntimeError("secret_storage")):
            response = await self.client.post("/invocations", json=self.request)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()["error"]["code"], "execution_unavailable")
        self.assertNotIn("secret", response.text)

        async def broken_body():
            yield b'{"action":'
            raise RuntimeError("secret_transport")

        with self.assertLogs("information_extraction.hosted_app", level="ERROR") as logs:
            response = await self.client.post(
                "/invocations", content=broken_body(), headers={"content-type": "application/json"},
            )
        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(response.json()["error"]["code"], "internal_error")
        self.assertNotIn("secret", response.text + str(logs.output))
        self.assertEqual(self.model.calls, [])

    async def test_concurrent_operators_cannot_allocate_two_budgets_for_one_job(self):
        results = await asyncio.gather(*(
            self.client.post("/invocations", json={**self.request, "request_id": request_id})
            for request_id in ("operator-a", "operator-b")
        ))
        self.assertEqual(sorted(result.status_code for result in results), [202, 409])
        winner = next(result for result in results if result.status_code == 202)
        await self.wait_for(winner.json()["authorization"]["run_id"], "completed")
        self.assertEqual(len(self.model.calls), 2)

    async def test_concurrent_resume_intents_select_one_budget_and_one_current_successor(self):
        first = await self.client.post("/invocations", json={**self.request, "max_attempts": 1})
        first_id = first.json()["authorization"]["run_id"]
        await self.wait_for(first_id, "limited")
        results = await asyncio.gather(*(
            self.client.post("/invocations", json={
                "action": "resume", "run_id": first_id, "request_id": request_id,
                "expected_revision": 1, "max_attempts": 1, "deadline": 1060,
            })
            for request_id in ("resume-a", "resume-b")
        ))
        self.assertEqual(sorted(result.status_code for result in results), [202, 409])
        winner = next(result for result in results if result.status_code == 202)
        run_id = winner.json()["authorization"]["run_id"]
        await self.wait_for(run_id, "completed")
        current = await self.current()
        self.assertEqual(current["current"]["authorization"]["run_id"], run_id)
        self.assertIsNone(current["pending_request"])
        self.assertEqual(len(self.model.calls), 2)

    async def test_detached_native_failure_does_not_leak_unobserved_sdk_tracebacks(self):
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        unhandled = []
        loop.set_exception_handler(lambda loop, context: unhandled.append(context))
        self.addCleanup(loop.set_exception_handler, previous)

        def fail(request):
            raise RuntimeError("secret_provider_exception")

        self.model.complete = fail
        started = await self.client.post("/invocations", json=self.request)
        await self.wait_for(started.json()["authorization"]["run_id"], "in_progress_or_interrupted")
        for _ in range(10):
            await asyncio.sleep(0.01)
            gc.collect()
        self.assertEqual(unhandled, [])

    async def test_sdk_registration_diagnostics_are_redacted_in_host_logs(self):
        async def unavailable(*args, **kwargs):
            try:
                raise RuntimeError("secret_sdk_diagnostic")
            except RuntimeError:
                logging.getLogger("azure.ai.agentserver.tasks").exception("upstream secret diagnostic")
                raise

        with (
            self.assertLogs("azure.ai.agentserver.tasks", level="ERROR") as logs,
            patch("azure.ai.agentserver.core.tasks.Task.start", side_effect=unavailable),
        ):
            response = await self.client.post("/invocations", json=self.request)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("secret", response.text + str(logs.output))
        self.assertNotIn("Traceback", str(logs.output))

    async def test_probe_rejects_other_jobs_before_writes_and_cannot_inspect_or_resume_their_rounds(self):
        with (
            patch.object(self.store, "create", side_effect=AssertionError("wrong_job_write")) as creates,
            patch.object(self.store, "create_batch_record", side_effect=AssertionError("wrong_job_write")) as writes,
        ):
            response = await self.client.post(
                "/invocations", json={**self.request, "job_id": "other-job"},
            )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["error"]["code"], "job_not_owned")
        creates.assert_not_called()
        writes.assert_not_called()

        foreign_model = SyntheticModel()
        foreign_execution = Execution(self.store, foreign_model)
        foreign_execution.create("other-job", synthetic_plan(), "other-create")
        foreign = Batch(foreign_execution, self.store, QueueScheduler(), clock=lambda: self.now)
        run = await foreign.start("other-job", 0, "other-start", BatchLimits(max_attempts=1, deadline=1060))
        foreign.run(run.run_id)
        for request in (
            {"action": "status", "run_id": run.run_id},
            {
                "action": "resume", "run_id": run.run_id, "request_id": "other-resume",
                "expected_revision": 1, "max_attempts": 1, "deadline": 1060,
            },
        ):
            with patch.object(
                self.store, "create_batch_record", side_effect=AssertionError("foreign_round_write"),
            ) as writes:
                response = await self.client.post("/invocations", json=request)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()["error"]["code"], "job_not_owned")
            self.assertNotIn("candidates", response.json())
            writes.assert_not_called()
        self.assertEqual(self.model.calls, [])
