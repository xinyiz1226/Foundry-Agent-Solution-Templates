import asyncio
import importlib.util
import importlib.metadata
from pathlib import Path
import shutil
from threading import Event
import time
import unittest
import uuid

from information_extraction import Execution, SQLiteStore
from information_extraction.batch import BatchLimits, BatchState, RegistrationUnknown
from information_extraction.sample import synthetic_plan
from tests.test_execution import SyntheticModel

try:
    NATIVE_AVAILABLE = importlib.util.find_spec("azure.ai.agentserver.core.tasks") is not None
except ModuleNotFoundError:
    NATIVE_AVAILABLE = False


@unittest.skipUnless(NATIVE_AVAILABLE, "optional hosted SDK not installed")
class NativeBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_registered_task_progresses_without_a_request_connection(self):
        await self._exercise_native(lost_ack=False)

    async def test_real_sdk_reconnects_same_active_task_after_registration_response_loss(self):
        await self._exercise_native(lost_ack=True)

    async def _exercise_native(self, *, lost_ack):
        from azure.ai.agentserver.core.tasks import resilient_tasks_enabled
        from azure.ai.agentserver.core.tasks._local_provider import LocalFileTaskProvider
        from azure.ai.agentserver.core.tasks._manager import AgentConfig, TaskManager, set_task_manager
        from information_extraction.native_batch import create_native_batch

        self.assertEqual(importlib.metadata.version("azure-ai-agentserver-core"), "2.1.0")
        directory = Path(".test-data") / uuid.uuid4().hex
        directory.mkdir(parents=True)
        entered, release = Event(), Event()
        model = SyntheticModel()
        complete = model.complete

        def slow(request):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("synthetic_worker_wait")
            return complete(request)

        model.complete = slow
        store = SQLiteStore(directory / "batch.sqlite3")
        execution = Execution(store, model)
        execution.create("job", synthetic_plan(), "create")
        batch = create_native_batch(execution, store)
        scheduler = batch.scheduler
        seen = []

        class LoseFirstAck:
            async def schedule(self, run_id):
                await scheduler.schedule(run_id)
                seen.append(run_id)
                if len(seen) == 1:
                    raise TimeoutError("synthetic_registration_ack_loss")

        if lost_ack:
            batch.scheduler = LoseFirstAck()
        self.assertTrue(resilient_tasks_enabled())
        config = AgentConfig(
            agent_name="offline-batch", agent_version="1", agent_id="offline",
            is_hosted=False, project_endpoint="", project_id="", session_id="offline",
            port=0, appinsights_connection_string="", otlp_endpoint="",
            sse_keepalive_interval=0,
        )
        manager = TaskManager(
            config, provider=LocalFileTaskProvider(directory / "native-tasks"),
            shutdown_grace_seconds=1,
        )
        set_task_manager(manager)
        try:
            await manager.startup()
            limits = BatchLimits(deadline=time.time() + 30)
            if lost_ack:
                with self.assertRaises(RegistrationUnknown):
                    await asyncio.wait_for(batch.start("job", 0, "start", limits), timeout=2)
                self.assertFalse(batch.status(seen[0]).registration_confirmed)
            run = await asyncio.wait_for(batch.start("job", 0, "start", limits), timeout=2)
            if lost_ack:
                self.assertEqual(seen, [run.run_id, run.run_id])
            self.assertEqual(model.calls, [])
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            self.assertEqual(await batch.start("job", 0, "start", limits), run)
            self.assertEqual(batch.status(run.run_id).state, BatchState.BLOCKED)
            release.set()
            async with asyncio.timeout(5):
                while batch.status(run.run_id).state != BatchState.COMPLETED:
                    await asyncio.sleep(0.01)
            self.assertEqual(len(model.calls), 2)
            self.assertEqual(batch.status(run.run_id).snapshot.completed_chunk_ids, ("chunk-1", "chunk-2"))
            saved = batch.status(run.run_id)
            async with asyncio.timeout(5):
                while await manager.provider.get(run.run_id) is not None:
                    await asyncio.sleep(0.01)
            self.assertEqual(batch.status(run.run_id), saved)
            self.assertEqual(await batch.start("job", 0, "start", limits), run)
            self.assertEqual(len(model.calls), 2)
        finally:
            release.set()
            await manager.shutdown()
            set_task_manager(None)
            shutil.rmtree(directory)
