import asyncio
from contextlib import nullcontext, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from information_extraction import ModelResponse

from tests.test_native_batch import NATIVE_AVAILABLE


class BatchSmokeTests(unittest.TestCase):
    @unittest.skipUnless(NATIVE_AVAILABLE, "optional hosted SDK not installed")
    def test_native_developer_smoke_is_bounded_model_free_and_cleans_up(self):
        before = set(Path(".test-data").glob("native-batch-*"))
        result = subprocess.run(
            [sys.executable, str(Path("scripts") / "batch_smoke.py")],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "lifecycle": "AgentServerHost",
            "provider": "native-local-file",
            "sdk_version": "2.1.0",
            "first_round": "limited",
            "final_round": "completed",
            "revision": 2,
            "synthetic_model_calls": 2,
            "real_model_calls": 0,
            "cloud_recovery_verified": False,
        })
        self.assertEqual(set(Path(".test-data").glob("native-batch-*")), before)

    @unittest.skipUnless(NATIVE_AVAILABLE, "optional hosted SDK not installed")
    def test_public_host_smoke_restores_environment_and_closes_host_on_success_and_failure(self):
        from azure.ai.agentserver.core.tasks import (
            TaskContext, TaskManagerNotInitialized, resilient_tasks_enabled, task,
        )
        from scripts import batch_smoke

        @task(name="offline-smoke-cleanup-probe")
        async def probe(ctx: TaskContext[str]) -> None:
            raise AssertionError("cleanup_probe_must_not_execute")

        for fail in (False, True):
            with self.subTest(fail=fail), patch.dict(os.environ, {
                "AGENTSERVER_TASKS_BACKEND": "hosted",
                "AGENTSERVER_STATE_ROOT": "unused-fixture-root",
                "FOUNDRY_HOSTING_ENVIRONMENT": "synthetic-ambient-host",
                "FOUNDRY_AGENT_NAME": "synthetic-ambient-agent",
                "PORT": "invalid-ambient-port",
            }):
                before = dict(os.environ)
                enabled_before = resilient_tasks_enabled()
                directories_before = set(Path(".test-data").glob("native-batch-*"))
                output = io.StringIO()
                with (
                    redirect_stdout(output),
                    patch.object(
                        batch_smoke.SyntheticModel, "complete",
                        return_value=ModelResponse({"records": []}),
                    ) if fail else nullcontext(),
                ):
                    code = batch_smoke.main()
                self.assertEqual(code, 1 if fail else 0)
                if fail:
                    self.assertEqual(json.loads(output.getvalue()), {"error": "offline_batch_smoke_failed"})
                else:
                    self.assertEqual(json.loads(output.getvalue())["lifecycle"], "AgentServerHost")
                self.assertEqual(dict(os.environ), before)
                self.assertEqual(resilient_tasks_enabled(), enabled_before)
                self.assertEqual(set(Path(".test-data").glob("native-batch-*")), directories_before)
                with self.assertRaises(TaskManagerNotInitialized):
                    asyncio.run(probe.get_active_run("missing-cleanup-probe"))
