"""Bounded synthetic-only Invocations/ASGI smoke; no HTTP listener or cloud calls."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from information_extraction import SQLiteStore
from information_extraction.contracts import ExecutionError

if __package__:
    from .batch_smoke import SyntheticModel, _offline_environment
else:
    from batch_smoke import SyntheticModel, _offline_environment


async def _smoke(directory: Path) -> dict:
    import httpx
    from azure.ai.agentserver.core.tasks import resilient_tasks_enabled, set_resilient_tasks_enabled
    from information_extraction.hosted_app import create_offline_app

    with (
        _offline_environment(directory),
        patch("socket.socket.connect", side_effect=RuntimeError("network_forbidden")),
        patch("socket.socket.connect_ex", side_effect=RuntimeError("network_forbidden")),
        patch("socket.getaddrinfo", side_effect=RuntimeError("network_forbidden")),
        patch("socket.socket.bind", side_effect=RuntimeError("server_bind_forbidden")),
    ):
        enabled = resilient_tasks_enabled()
        try:
            model = SyntheticModel()
            app = create_offline_app(SQLiteStore(directory / "ledger.sqlite3"), model=model)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://in-process",
                ) as client:
                    async def post(data, expected):
                        response = await client.post("/invocations", json=data)
                        if response.status_code != expected:
                            raise ExecutionError("synthetic_invocations_http_failure")
                        return response.json()

                    async def status(run_id, state):
                        while True:
                            result = await post({"action": "status", "run_id": run_id}, 200)
                            if result["state"] == state:
                                return result
                            await asyncio.sleep(0.01)

                    async with asyncio.timeout(10):
                        request = {
                            "action": "start", "job_id": "synthetic-job", "request_id": "start",
                            "expected_revision": 0, "max_attempts": 1, "deadline": time.time() + 10,
                        }
                        first = await post(request, 202)
                        first_id = first["authorization"]["run_id"]
                        limited = await status(first_id, "limited")
                        if await post(request, 202) != first or model.calls != 1:
                            raise ExecutionError("synthetic_start_replay_mismatch")
                        second = await post({
                            "action": "resume", "run_id": first_id, "request_id": "resume",
                            "expected_revision": 1, "max_attempts": 1, "deadline": time.time() + 10,
                        }, 202)
                        completed = await status(second["authorization"]["run_id"], "completed")
                        if (
                            model.calls != 2
                            or [c["record"]["value"] for c in completed["candidates"]] != [120, 18]
                            or completed["candidates"][0] != limited["candidates"][0]
                        ):
                            raise ExecutionError("synthetic_invocations_result_mismatch")
            return {
                "lifecycle": "InvocationAgentServerHost",
                "transport": "in_process_asgi",
                "provider": "native-local-file",
                "first_round": limited["state"],
                "final_round": completed["state"],
                "revision": completed["revision"],
                "synthetic_model_calls": model.calls,
                "real_model_calls": 0,
                "cloud_recovery_verified": False,
            }
        finally:
            set_resilient_tasks_enabled(enabled)


def main() -> int:
    try:
        root = Path(".test-data")
        root.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="invocations-smoke-", dir=root) as directory:
            result = asyncio.run(_smoke(Path(directory)))
    except ImportError:
        print(json.dumps({"error": "optional_hosted_test_dependencies_unavailable"}))
        return 1
    except Exception:
        print(json.dumps({"error": "offline_invocations_smoke_failed"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
