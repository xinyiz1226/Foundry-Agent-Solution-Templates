"""Bounded, synthetic-only native SDK smoke. No server, credentials, or cloud calls."""

import asyncio
from contextlib import contextmanager
import importlib.metadata
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from typing import Iterator

from information_extraction import Execution, ModelResponse, SQLiteStore, TokenUsage
from information_extraction.batch import Batch, BatchLimits, BatchState
from information_extraction.contracts import ExecutionError
from information_extraction.sample import synthetic_plan


class SyntheticModel:
    binding = "synthetic-model-v1"

    def __init__(self):
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        metric, value = (
            ("revenue", 120) if request.chunk.id == "chunk-1" else ("operating_income", 18)
        )
        return ModelResponse({"records": [{
            "metric": metric, "value": value, "unit": "USD_millions",
            "block_ids": [request.chunk.blocks[0].id],
        }]}, TokenUsage(10, 5))


@contextmanager
def _offline_environment(directory: Path) -> Iterator[None]:
    settings = {
        "AGENTSERVER_TASKS_BACKEND": "local",
        "AGENTSERVER_STATE_ROOT": str((directory / "native-state").resolve()),
        "AGENTSERVER_SHUTDOWN_GRACE_SECONDS": "1",
        "FOUNDRY_HOSTING_ENVIRONMENT": "",
        "FOUNDRY_AGENT_NAME": "offline-batch-smoke",
        "FOUNDRY_AGENT_VERSION": "1",
        "FOUNDRY_AGENT_ID": "",
        "FOUNDRY_AGENT_SESSION_ID": "offline",
        "FOUNDRY_PROJECT_ENDPOINT": "",
        "FOUNDRY_PROJECT_ARM_ID": "",
        "APPLICATIONINSIGHTS_CONNECTION_STRING": "",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "",
        "PORT": "8000",
        "SSE_KEEPALIVE_INTERVAL": "0",
        "WS_KEEPALIVE_INTERVAL": "0",
    }
    previous = {key: os.environ.get(key) for key in settings}
    try:
        os.environ.update(settings)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def _exercise(batch: Batch, model: SyntheticModel) -> dict:
    async with asyncio.timeout(10):
        first = await batch.start(
            "synthetic-job", 0, "start", BatchLimits(max_attempts=1, deadline=time.time() + 10),
        )
        while batch.status(first.run_id).state != BatchState.LIMITED:
            await asyncio.sleep(0.01)
        second = await batch.resume(
            first.run_id, 1, "resume", BatchLimits(deadline=time.time() + 10),
        )
        while batch.status(second.run_id).state != BatchState.COMPLETED:
            await asyncio.sleep(0.01)
    status = batch.status(second.run_id)
    if model.calls != 2 or [c.record.value for c in status.snapshot.candidates] != [120, 18]:
        raise ExecutionError("synthetic_batch_mismatch")
    return {
        "lifecycle": "AgentServerHost",
        "provider": "native-local-file",
        "sdk_version": importlib.metadata.version("azure-ai-agentserver-core"),
        "first_round": batch.status(first.run_id).state.value,
        "final_round": status.state.value,
        "revision": status.snapshot.revision,
        "synthetic_model_calls": model.calls,
        "real_model_calls": 0,
        "cloud_recovery_verified": False,
    }


async def _smoke(directory: Path) -> dict:
    from azure.ai.agentserver.core import AgentServerHost
    from azure.ai.agentserver.core.tasks import resilient_tasks_enabled, set_resilient_tasks_enabled
    from information_extraction.native_batch import create_native_batch

    with _offline_environment(directory):
        enabled_before = resilient_tasks_enabled()
        try:
            model = SyntheticModel()
            store = SQLiteStore(directory / "batch.sqlite3")
            execution = Execution(store, model)
            execution.create("synthetic-job", synthetic_plan(), "create")
            batch = create_native_batch(execution, store)
            app = AgentServerHost(configure_observability=None, graceful_shutdown_timeout=1)
            failure = None
            async with app.router.lifespan_context(app):
                try:
                    result = await _exercise(batch, model)
                except BaseException as error:
                    # SDK 2.1.0 skips its post-yield shutdown on exceptional exit.
                    # Exit normally for cleanup, then propagate the original failure.
                    failure = error
            if failure is not None:
                raise failure
            return result
        finally:
            set_resilient_tasks_enabled(enabled_before)


def main() -> int:
    try:
        root = Path(".test-data")
        root.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="native-batch-", dir=root) as directory:
            result = asyncio.run(_smoke(Path(directory)))
    except ImportError:
        print(json.dumps({"error": "optional_hosted_sdk_unavailable"}))
        return 1
    except Exception:
        print(json.dumps({"error": "offline_batch_smoke_failed"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
