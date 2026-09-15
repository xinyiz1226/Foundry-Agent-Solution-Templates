import asyncio
from functools import wraps
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from information_extraction import ExecutionError
from tests.test_hosted_app import INVOCATIONS_AVAILABLE
from tests.test_hosted_config import HOSTED_ENV


@unittest.skipUnless(INVOCATIONS_AVAILABLE, "optional hosted SDKs not installed")
class HostedLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from azure.ai.agentserver.core.tasks import resilient_tasks_enabled, set_resilient_tasks_enabled
        from azure.ai.agentserver.core.tasks._client import HostedTaskProvider
        from azure.ai.agentserver.core.tasks._decorator import _REGISTERED_DESCRIPTORS
        from azure.ai.agentserver.core.tasks._manager import TaskManager
        from azure.identity.aio import DefaultAzureCredential
        from information_extraction.hosted_app import create_app
        from tests.test_blob_store import Backend, FakeContainerClient

        enabled, descriptors = resilient_tasks_enabled(), list(_REGISTERED_DESCRIPTORS)
        log_factory = logging.getLogRecordFactory()
        self.addCleanup(lambda: self.assertIs(logging.getLogRecordFactory(), log_factory))
        self.addCleanup(set_resilient_tasks_enabled, enabled)
        self.addCleanup(lambda: _REGISTERED_DESCRIPTORS.__setitem__(slice(None), descriptors))
        self.enterContext(patch.dict(os.environ, {
            **HOSTED_ENV,
            "AZURE_CLIENT_ID": "00000000-0000-0000-0000-000000000001",
            "AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000002",
            "AZURE_FEDERATED_TOKEN_FILE": str(Path(".test-data") / "unused-token-fixture"),
            "AGENTSERVER_SHUTDOWN_GRACE_SECONDS": "0",
        }, clear=True))
        self.forbidden = []
        for target in (
            "socket.socket.connect", "socket.socket.connect_ex", "socket.socket.bind",
            "socket.getaddrinfo", "subprocess.Popen",
        ):
            self.forbidden.append(self.enterContext(patch(
                target, side_effect=AssertionError("network_or_process_forbidden"),
            )))
        for method in ("get_token", "get_token_info"):
            self.forbidden.append(self.enterContext(patch.object(
                DefaultAzureCredential, method, side_effect=AssertionError("token_forbidden"),
            )))
        self.events, self.credentials, self.providers = [], [], []

        def credential_factory(**kwargs):
            credential = DefaultAzureCredential(**kwargs)
            self.credentials.append(credential)
            close = credential.close
            self.addAsyncCleanup(close)

            async def observed_close():
                self.events.append("native_credential")
                await close()

            credential.close = AsyncMock(side_effect=observed_close)
            return credential

        self.enterContext(patch("azure.identity.aio.DefaultAzureCredential", side_effect=credential_factory))
        provider_init = HostedTaskProvider.__init__

        def observed_provider(provider, *args, **kwargs):
            provider_init(provider, *args, **kwargs)
            self.providers.append(provider)
            close = provider._client.close
            self.addAsyncCleanup(close)

            async def observed_close():
                self.events.append("native_http")
                await close()

            provider._client.close = AsyncMock(side_effect=observed_close)

        self.enterContext(patch.object(HostedTaskProvider, "__init__", observed_provider))
        response = Mock(status_code=200, headers={})
        response.body.return_value = b'{"data":[],"has_more":false}'
        self.send = self.enterContext(patch.object(
            HostedTaskProvider, "_send", new=AsyncMock(return_value=response),
        ))
        shutdown = TaskManager.shutdown

        async def observed_shutdown(manager):
            await shutdown(manager)
            self.events.append("manager_drained")

        self.enterContext(patch.object(TaskManager, "shutdown", observed_shutdown))
        credential = Mock()
        credential.close.side_effect = lambda: self.events.append("blob_credential")
        self.container = FakeContainerClient(Backend())
        self.container.close = Mock(side_effect=lambda: self.events.append("blob_http"))
        self.enterContext(patch("azure.identity.DefaultAzureCredential", return_value=credential))
        self.enterContext(patch("azure.storage.blob.ContainerClient", return_value=self.container))
        self.app = create_app()

    async def asyncTearDown(self):
        from azure.ai.agentserver.core.tasks import TaskManagerNotInitialized
        from azure.ai.agentserver.core.tasks._manager import get_task_manager
        for dependency in self.forbidden:
            dependency.assert_not_called()
        with self.assertRaises(TaskManagerNotInitialized):
            get_task_manager()

    async def test_real_hosted_provider_uses_prod_async_chain_and_closes_after_manager_drain(self):
        import httpx

        async with self.app.router.lifespan_context(self.app):
            self.assertEqual(len(self.providers), 1)
            self.assertEqual(len(self.credentials), 1)
            self.assertEqual(
                {type(credential).__name__ for credential in self.credentials[0].credentials},
                {"EnvironmentCredential", "WorkloadIdentityCredential", "ManagedIdentityCredential"},
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app), base_url="http://in-process",
            ) as client:
                response = await client.post("/invocations", json={"action": "status", "run_id": "absent"})
                self.assertEqual(response.status_code, 404, response.text)
            self.assertGreater(self.send.await_count, 0)
            self.assertEqual(self.events, [])
        self.assertEqual(self.events, [
            "manager_drained", "native_http", "native_credential", "blob_http", "blob_credential",
        ])
        self.providers[0]._client.close.assert_awaited_once()
        self.credentials[0].close.assert_awaited_once()
        for dependency in self.forbidden:
            dependency.assert_not_called()

    async def test_startup_cancellation_closes_partial_hosted_resources_after_drain(self):
        self.send.side_effect = asyncio.CancelledError("synthetic_startup_interruption")
        with self.assertRaises(asyncio.CancelledError):
            async with self.app.router.lifespan_context(self.app):
                self.fail("startup_must_not_succeed")
        self.assertEqual(self.events, [
            "manager_drained", "native_http", "native_credential", "blob_http", "blob_credential",
        ])

    async def test_failed_startup_after_recovery_stops_manager_and_closes_native_resources(self):
        from azure.ai.agentserver.core.tasks._manager import TaskManager
        startup = TaskManager.startup

        async def fail_after_recovery(manager):
            await startup(manager)
            raise RuntimeError("secret_startup_detail")

        with (
            patch.object(TaskManager, "startup", fail_after_recovery),
            self.assertRaisesRegex(ExecutionError, "^synthetic_host_lifecycle_failed$"),
        ):
            async with self.app.router.lifespan_context(self.app):
                self.fail("failed_startup_must_not_succeed")
        self.assertEqual(self.events, [
            "manager_drained", "native_http", "native_credential", "blob_http", "blob_credential",
        ])

    async def test_lifespan_error_keeps_original_cancellation_when_http_close_also_fails(self):
        async def failed_close():
            self.events.append("native_http")
            raise RuntimeError("secret_cleanup_detail")

        with self.assertLogs("information_extraction", level="ERROR") as logs:
            with self.assertRaises(asyncio.CancelledError):
                async with self.app.router.lifespan_context(self.app):
                    self.providers[0]._client.close.side_effect = failed_close
                    raise asyncio.CancelledError("synthetic_body_interruption")
        self.assertEqual(self.events, [
            "manager_drained", "native_http", "native_credential", "blob_http", "blob_credential",
        ])
        self.assertNotIn("secret_cleanup_detail", str(logs.output))

    async def test_manager_shutdown_failure_still_stops_recovery_and_closes_owned_resources(self):
        from azure.ai.agentserver.core.tasks._manager import TaskManager

        before = asyncio.all_tasks()
        pending = set()
        try:
            with (
                patch.object(TaskManager, "shutdown", new=AsyncMock(side_effect=RuntimeError("drain_failure"))),
                self.assertLogs("information_extraction", level="ERROR"),
                self.assertRaisesRegex(ExecutionError, "^synthetic_host_lifecycle_failed$"),
            ):
                async with self.app.router.lifespan_context(self.app):
                    pass
            pending = asyncio.all_tasks() - before
            self.assertEqual(pending, set(), "hosted recovery must not survive owned resource closure")
            self.assertEqual(self.events, ["native_http", "native_credential", "blob_http", "blob_credential"])
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def test_sdk_contract_mismatch_fails_visibly_before_native_resources_are_created(self):
        with (
            patch("information_extraction.hosted_lifecycle.version", return_value="unsupported"),
            self.assertLogs("information_extraction", level="ERROR") as logs,
            self.assertRaisesRegex(ExecutionError, "^synthetic_host_lifecycle_failed$"),
        ):
            async with self.app.router.lifespan_context(self.app):
                self.fail("unsupported_sdk_must_not_start")
        self.assertIn("native_host_contract_mismatch", str(logs.output))
        self.assertEqual(self.credentials, [])
        self.assertEqual(self.events, ["blob_http", "blob_credential"])

    async def test_changed_credential_category_is_rejected_before_async_factory(self):
        with (
            patch.dict(os.environ, {"AZURE_TOKEN_CREDENTIALS": "dev"}),
            self.assertRaisesRegex(ExecutionError, "^synthetic_host_lifecycle_failed$"),
        ):
            async with self.app.router.lifespan_context(self.app):
                self.fail("changed_credential_category_must_not_start")
        self.assertEqual(self.credentials, [])
        self.assertEqual(self.events, ["blob_http", "blob_credential"])

    async def test_provider_constructor_failure_closes_its_owned_async_credential(self):
        from azure.ai.agentserver.core.tasks._client import HostedTaskProvider
        with (
            patch.object(HostedTaskProvider, "__init__", side_effect=RuntimeError("constructor_failure")),
            self.assertRaisesRegex(ExecutionError, "^synthetic_host_lifecycle_failed$"),
        ):
            async with self.app.router.lifespan_context(self.app):
                self.fail("provider_constructor_must_not_succeed")
        self.assertEqual(len(self.credentials), 1)
        self.credentials[0].close.assert_awaited_once()
        self.assertEqual(self.events, ["native_credential", "blob_http", "blob_credential"])

    async def test_manager_constructor_failure_closes_provider_and_credential_before_yield(self):
        from azure.ai.agentserver.core.tasks._manager import TaskManager

        @wraps(TaskManager.__init__)
        def failed_constructor(manager, *args, **kwargs):
            raise RuntimeError("manager_constructor_failure")

        with (
            patch.object(TaskManager, "__init__", failed_constructor),
            self.assertRaisesRegex(ExecutionError, "^synthetic_host_lifecycle_failed$"),
        ):
            async with self.app.router.lifespan_context(self.app):
                self.fail("manager_constructor_must_not_succeed")
        self.assertEqual(self.events, ["native_http", "native_credential", "blob_http", "blob_credential"])

    async def test_final_cleanup_does_not_clear_a_replacement_manager(self):
        from azure.ai.agentserver.core.tasks._manager import TaskManager, get_task_manager, set_task_manager

        replacement = TaskManager(self.app.config, provider=Mock())
        shutdown = TaskManager.shutdown

        async def replace_after_drain(manager):
            await shutdown(manager)
            set_task_manager(replacement)

        try:
            with (
                patch.object(TaskManager, "shutdown", replace_after_drain),
                self.assertLogs("information_extraction", level="ERROR") as logs,
                self.assertRaisesRegex(ExecutionError, "^synthetic_host_lifecycle_failed$"),
            ):
                async with self.app.router.lifespan_context(self.app):
                    pass
            self.assertIs(get_task_manager(), replacement)
            self.assertIn("native_host_manager_ownership_changed", str(logs.output))
            self.assertEqual(self.events, [
                "manager_drained", "native_http", "native_credential", "blob_http", "blob_credential",
            ])
        finally:
            await shutdown(replacement)

    async def test_shutdown_joins_inflight_batch_worker_before_closing_blob_and_native_clients(self):
        import httpx
        from azure.ai.agentserver.core.tasks._client import HostedTaskProvider
        from azure.ai.agentserver.core.tasks._local_provider import LocalFileTaskProvider
        from information_extraction.hosted_app import SyntheticFinancialModel

        Path(".test-data").mkdir(exist_ok=True)
        directory = self.enterContext(TemporaryDirectory(dir=".test-data"))
        storage = LocalFileTaskProvider(Path(directory))
        # Substitute task-storage I/O, not the hosted provider factory/ownership.
        for method in ("create", "get", "update", "delete", "list"):
            async def operation(provider, *args, _method=method, **kwargs):
                return await getattr(storage, _method)(*args, **kwargs)
            self.enterContext(patch.object(HostedTaskProvider, method, operation))

        entered, release = Event(), Event()
        complete = SyntheticFinancialModel.complete
        calls = []

        def blocked_complete(model, request):
            calls.append(request.chunk.id)
            entered.set()
            if not release.wait(5):
                raise TimeoutError("synthetic_worker_wait")
            self.events.append("worker_returned")
            return complete(model, request)

        self.enterContext(patch.object(SyntheticFinancialModel, "complete", blocked_complete))
        lifespan = self.app.router.lifespan_context(self.app)
        await lifespan.__aenter__()
        closing = None
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app), base_url="http://in-process",
            ) as client:
                response = await client.post("/invocations", json={
                    "action": "start", "job_id": "synthetic-job", "request_id": "drain-probe",
                    "expected_revision": 0, "max_attempts": 1, "deadline": time.time() + 60,
                })
                self.assertEqual(response.status_code, 202, response.text)
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            closing = asyncio.create_task(lifespan.__aexit__(None, None, None))
            async with asyncio.timeout(2):
                while "manager_drained" not in self.events:
                    await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
            self.assertFalse(closing.done(), "the worker must finish before its clients close")
            self.assertNotIn("native_http", self.events)
            self.assertNotIn("blob_http", self.events)
        finally:
            release.set()
            if closing is not None:
                await asyncio.wait_for(closing, timeout=5)
            else:
                await lifespan.__aexit__(None, None, None)
        self.assertEqual(calls, ["chunk-1"])
        self.assertLess(self.events.index("worker_returned"), self.events.index("native_http"))
        self.assertLess(self.events.index("native_http"), self.events.index("blob_http"))
