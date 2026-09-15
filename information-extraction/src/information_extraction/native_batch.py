"""Optional Foundry native resilient-task adapter, pinned to core SDK 2.1.0.

Construct once before AgentServerHost startup, with authenticated adapters
supplied by the host. This module neither starts a server nor chooses a provider.
Local SDK-provider evidence does not establish managed-provider crash recovery.
"""

import asyncio
from datetime import timedelta
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

    async def schedule(self, run_id: str) -> None:
        try:
            await self.registered_task.start(task_id=run_id, input=run_id, input_id=run_id)
        except TaskConflictError:
            # Reconnection may reclaim an expired lease; never use it for status.
            active = await self.registered_task.get_active_run(run_id)
            if active is None:
                raise ExecutionError("native_registration_unconfirmed") from None


def create_native_batch(
    execution: Execution, records: BatchRecords, *, clock: Callable[[], float] = time.time,
) -> Batch:
    """Register the stable recovery handler; use returned start/status/resume seams."""
    set_resilient_tasks_enabled(True)

    @task(name="information-extraction-batch-v1", timeout=timedelta(minutes=5), retry=None)
    async def bounded_batch(ctx: TaskContext[str]) -> None:
        try:
            await asyncio.to_thread(
                batch.run, ctx.input,
                cancelled=lambda: ctx.cancel.is_set() or ctx.shutdown.is_set(),
            )
        except Exception:
            # Native task diagnostics must not expose raw model/storage exceptions.
            raise ExecutionError("batch_worker_failed") from None

    batch = Batch(execution, records, NativeScheduler(bounded_batch), clock=clock)
    return batch
