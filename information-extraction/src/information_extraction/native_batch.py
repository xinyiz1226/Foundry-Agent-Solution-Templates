"""Optional Foundry native resilient-task adapter, pinned to core SDK 2.1.0.

Construct once before AgentServerHost startup, with authenticated adapters
supplied by the host. This module neither starts a server nor chooses a provider.
Local SDK-provider evidence does not establish managed-provider crash recovery.
"""

import asyncio
from datetime import timedelta
import logging
from threading import Event
import time
from typing import Callable

from azure.ai.agentserver.core.tasks import (
    Task, TaskConflictError, TaskContext, set_resilient_tasks_enabled, task,
)

from .batch import Batch, BatchRecords
from .contracts import ExecutionError
from .execution import Execution


class NativeScheduler:
    def __init__(self, registered_task: Task[str, None]):
        self.registered_task = registered_task
        self._observations: dict[str, asyncio.Task[None]] = {}

    async def schedule(self, run_id: str) -> None:
        try:
            handle = await self.registered_task.start(task_id=run_id, input=run_id, input_id=run_id)
        except TaskConflictError:
            # Reconnection may reclaim an expired lease; never use it for status.
            handle = await self.registered_task.get_active_run(run_id)
            if handle is None:
                raise ExecutionError("native_registration_unconfirmed") from None
        existing = self._observations.get(run_id)
        if existing is None or existing.done():
            observation = asyncio.create_task(handle.result())
            self._observations[run_id] = observation
            observation.add_done_callback(lambda completed: self._observed(run_id, completed))

    def _observed(self, run_id: str, completed: asyncio.Task[None]) -> None:
        if self._observations.get(run_id) is completed:
            self._observations.pop(run_id, None)
        if not completed.cancelled() and completed.exception() is not None:
            logging.getLogger(__name__).error("native_batch_task_failed")


def create_native_batch(
    execution: Execution, records: BatchRecords, *, clock: Callable[[], float] = time.time,
) -> Batch:
    """Register the stable recovery handler; use returned start/status/resume seams."""
    set_resilient_tasks_enabled(True)

    @task(name="information-extraction-batch-v1", timeout=timedelta(minutes=5), retry=None)
    async def bounded_batch(ctx: TaskContext[str]) -> None:
        stopping = Event()
        worker = asyncio.create_task(asyncio.to_thread(
            batch.run, ctx.input,
            cancelled=lambda: stopping.is_set() or ctx.cancel.is_set() or ctx.shutdown.is_set(),
        ))
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            # Join the same worker before its storage clients close; never retry it.
            stopping.set()
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not worker.cancelled() and worker.exception() is not None:
                logging.getLogger(__name__).error("native_batch_worker_drain_failed")
            raise
        except Exception:
            # Native task diagnostics must not expose raw model/storage exceptions.
            raise ExecutionError("batch_worker_failed") from None

    batch = Batch(execution, records, NativeScheduler(bounded_batch), clock=clock)
    return batch
