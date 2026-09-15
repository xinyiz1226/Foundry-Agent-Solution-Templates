"""Owned native lifecycle for Core 2.1.0 / Invocations 1.1.0.

The pinned SDK lifespan has no provider-ownership hook and loses its manager
reference on startup failure. Its shutdown doesn't close the hosted provider or
credential, or await cancelled task finalizers. This instance-scoped adapter
uses the real SDK manager/provider; it never monkeypatches SDK classes/functions.
"""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
import inspect
import logging
from typing import AsyncIterator, Awaitable, Callable, NoReturn

from azure.ai.agentserver.core._base import _read_task_manager_shutdown_grace
from azure.ai.agentserver.core.tasks import TaskManagerNotInitialized
from azure.ai.agentserver.core.tasks._client import HostedTaskProvider
from azure.ai.agentserver.core.tasks._manager import TaskManager, get_task_manager, set_task_manager
from azure.ai.agentserver.invocations import InvocationAgentServerHost

from .contracts import ExecutionError


logger = logging.getLogger(__name__)


def _mismatch() -> NoReturn:
    logger.error("native_host_contract_mismatch")
    raise ExecutionError("native_host_contract_mismatch")


def _contract(host: InvocationAgentServerHost) -> None:
    try:
        compatible = (
            version("azure-ai-agentserver-core") == "2.1.0"
            and version("azure-ai-agentserver-invocations") == "1.1.0"
            and inspect.iscoroutinefunction(host._dispatch_shutdown)
            and isinstance(host._graceful_shutdown_timeout, int)
            and host.config.is_hosted
            and {"config", "provider", "shutdown_event", "shutdown_grace_seconds"}.issubset(
                inspect.signature(TaskManager).parameters,
            )
        )
    except (AttributeError, TypeError, ValueError, PackageNotFoundError):
        compatible = False
    if not compatible:
        _mismatch()
    try:
        get_task_manager()
    except TaskManagerNotInitialized:
        return
    raise ExecutionError("native_host_manager_already_active")


def _manager_contract(manager: TaskManager, provider: HostedTaskProvider) -> None:
    try:
        compatible = (
            manager._provider is provider
            and type(manager._active_tasks) is dict
            and type(manager._timeout_watchdogs) is dict
            and isinstance(manager._shutdown_event, asyncio.Event)
            and manager._periodic_recovery_task is None
            and inspect.iscoroutinefunction(manager.startup)
            and inspect.iscoroutinefunction(manager.shutdown)
        )
    except AttributeError:
        compatible = False
    if not compatible:
        _mismatch()


async def _drain(manager: TaskManager) -> None:
    # These private ownership fields are specific to Core 2.1.0.
    manager._shutdown_event.set()
    pending = set(manager._timeout_watchdogs.values())
    if manager._periodic_recovery_task is not None:
        pending.add(manager._periodic_recovery_task)
    for active in tuple(manager._active_tasks.values()):
        pending.add(active.execution_task)
        if active.renewal_task is not None:
            pending.add(active.renewal_task)
    try:
        await manager.shutdown()
    finally:
        for task in pending:
            if not task.done() and not task.cancelling():
                task.cancel()
        try:
            results = await asyncio.gather(*pending, return_exceptions=True)
        finally:
            set_task_manager(None)
    if any(isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError) for result in results):
        raise ExecutionError("native_host_task_drain_failed")


@asynccontextmanager
async def hosted_lifespan(host: InvocationAgentServerHost) -> AsyncIterator[None]:
    from azure.identity.aio import DefaultAzureCredential

    _contract(host)
    failure: BaseException | None = None

    async def cleanup(operation: Callable[[], Awaitable[None]]) -> None:
        nonlocal failure
        try:
            await operation()
        except BaseException as error:
            logger.error("native_host_cleanup_failed")
            if failure is None:
                failure = error

    try:
        async with AsyncExitStack() as resources:
            credential = DefaultAzureCredential()
            resources.push_async_callback(cleanup, credential.close)
            provider = HostedTaskProvider(project_endpoint=host.config.project_endpoint, credential=credential)
            resources.push_async_callback(cleanup, provider.close)
            manager = TaskManager(
                config=host.config, provider=provider, shutdown_event=asyncio.Event(),
                shutdown_grace_seconds=_read_task_manager_shutdown_grace(),
            )
            _manager_contract(manager, provider)
            resources.push_async_callback(cleanup, lambda: _drain(manager))
            set_task_manager(manager)
            await manager.startup()
            try:
                yield
            finally:
                if host._graceful_shutdown_timeout:
                    await asyncio.wait_for(host._dispatch_shutdown(), timeout=host._graceful_shutdown_timeout)
    except BaseException as error:
        failure = error
    if failure is not None:
        raise failure
