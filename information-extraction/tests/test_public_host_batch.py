import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from information_extraction import Execution, SQLiteStore
from information_extraction.batch import BatchLimits, BatchState
from information_extraction.sample import synthetic_plan
from tests.test_execution import SyntheticModel
from tests.test_native_batch import NATIVE_AVAILABLE


@unittest.skipUnless(NATIVE_AVAILABLE, "optional hosted SDK not installed")
class PublicHostBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_host_start_status_resume_and_cleanup_without_network_or_server(self):
        from azure.ai.agentserver.core import AgentServerHost
        from azure.ai.agentserver.core.tasks import (
            TaskManagerNotInitialized, resilient_tasks_enabled, set_resilient_tasks_enabled,
        )
        from information_extraction.native_batch import create_native_batch

        environment_before = dict(os.environ)
        enabled_before = resilient_tasks_enabled()
        tasks_before = asyncio.all_tasks()
        Path(".test-data").mkdir(exist_ok=True)
        try:
            with TemporaryDirectory(prefix="public-host-", dir=".test-data") as temporary:
                directory = Path(temporary)
                settings = {
                    "AGENTSERVER_TASKS_BACKEND": "local",
                    "AGENTSERVER_STATE_ROOT": str((directory / "native-state").resolve()),
                    "AGENTSERVER_SHUTDOWN_GRACE_SECONDS": "1",
                    "FOUNDRY_HOSTING_ENVIRONMENT": "",
                    "FOUNDRY_AGENT_NAME": "offline-public-host-test",
                    "FOUNDRY_AGENT_VERSION": "1",
                    "FOUNDRY_AGENT_SESSION_ID": "offline",
                    "FOUNDRY_PROJECT_ENDPOINT": "",
                    "FOUNDRY_PROJECT_ARM_ID": "",
                    "APPLICATIONINSIGHTS_CONNECTION_STRING": "",
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "",
                    "PORT": "8000",
                    "SSE_KEEPALIVE_INTERVAL": "0",
                    "WS_KEEPALIVE_INTERVAL": "0",
                }
                with (
                    patch.dict(os.environ, settings),
                    patch("socket.socket.connect", side_effect=AssertionError("network_forbidden")),
                    patch("socket.socket.connect_ex", side_effect=AssertionError("network_forbidden")),
                    patch("socket.getaddrinfo", side_effect=AssertionError("network_forbidden")),
                    patch("socket.socket.bind", side_effect=AssertionError("server_bind_forbidden")),
                ):
                    model = SyntheticModel()
                    store = SQLiteStore(directory / "batch.sqlite3")
                    execution = Execution(store, model)
                    execution.create("job", synthetic_plan(), "create")
                    batch = create_native_batch(execution, store)
                    app = AgentServerHost(configure_observability=None, graceful_shutdown_timeout=1)
                    self.assertFalse(app.config.is_hosted)
                    self.assertEqual(app.config.project_endpoint, "")
                    failure = None
                    async with app.router.lifespan_context(app):
                        try:
                            async with asyncio.timeout(5):
                                limits = BatchLimits(max_attempts=1, deadline=time.time() + 30)
                                first = await batch.start("job", 0, "start", limits)
                                while batch.status(first.run_id).state != BatchState.LIMITED:
                                    await asyncio.sleep(0.01)
                                limited = batch.status(first.run_id)
                                self.assertEqual(limited.snapshot.revision, 1)
                                self.assertEqual(await batch.start("job", 0, "start", limits), first)
                                self.assertEqual(len(model.calls), 1)
                                resumed = await batch.resume(
                                    first.run_id, 1, "resume", BatchLimits(deadline=time.time() + 30),
                                )
                                while batch.status(resumed.run_id).state != BatchState.COMPLETED:
                                    await asyncio.sleep(0.01)
                                finished = batch.status(resumed.run_id)
                                self.assertEqual(finished.snapshot.completed_chunk_ids, ("chunk-1", "chunk-2"))
                                self.assertEqual(finished.snapshot.candidates[0], limited.snapshot.candidates[0])
                                self.assertEqual(len(model.calls), 2)
                                self.assertTrue((directory / "native-state" / "tasks").is_dir())
                        except BaseException as error:
                            failure = error
                    if failure is not None:
                        raise failure
                    self.assertEqual(batch.status(resumed.run_id), finished)
                    with self.assertRaises(TaskManagerNotInitialized):
                        await batch.scheduler.registered_task.get_active_run(first.run_id)
                    async with asyncio.timeout(2):
                        while asyncio.all_tasks() - tasks_before:
                            await asyncio.sleep(0.01)
                    self.assertEqual(asyncio.all_tasks() - tasks_before, set())
            self.assertFalse(directory.exists())
        finally:
            set_resilient_tasks_enabled(enabled_before)
        self.assertEqual(dict(os.environ), environment_before)
        self.assertEqual(resilient_tasks_enabled(), enabled_before)
