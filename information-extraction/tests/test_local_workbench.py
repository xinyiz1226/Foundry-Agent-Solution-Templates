"""Public local process/HTTP/page flow using the actual native task backend."""

import importlib.metadata
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
try:
    for package in ("streamlit", "azure-ai-agentserver-invocations", "azure-ai-agentserver-core"):
        importlib.metadata.version(package)
    AVAILABLE = True
except importlib.metadata.PackageNotFoundError:
    AVAILABLE = False


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@unittest.skipUnless(AVAILABLE, "optional hosted/workbench dependencies unavailable")
class LocalWorkbenchTests(unittest.TestCase):
    def setUp(self):
        (ROOT / ".test-data").mkdir(exist_ok=True)

    def test_invalid_job_id_is_rejected_before_creating_state(self):
        with TemporaryDirectory(dir=ROOT / ".test-data", prefix="workbench-") as directory:
            state = Path(directory) / "must-not-exist"
            result = subprocess.run([
                sys.executable, str(ROOT / "scripts" / "run_workbench.py"),
                "--job-id", "invalid/job", "--state-dir", str(state),
            ], cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 2)
            self.assertIn("job-id must be a valid execution identifier", result.stderr)
            self.assertFalse(state.exists())

    def test_occupied_ui_port_is_reported_without_starting_a_backend(self):
        from information_extraction.workbench_client import WorkbenchClient, WorkbenchError

        with TemporaryDirectory(dir=ROOT / ".test-data", prefix="workbench-") as directory, socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = free_port()
            result = subprocess.run([
                sys.executable, str(ROOT / "scripts" / "run_workbench.py"),
                "--backend-port", str(port), "--ui-port", str(listener.getsockname()[1]),
                "--state-dir", directory,
            ], cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertIn("unavailable", result.stderr)
            self.assertIn("no existing service was stopped", result.stderr)
            with WorkbenchClient(f"http://127.0.0.1:{port}") as client, self.assertRaises(WorkbenchError):
                client.current()

    def test_launcher_starts_two_local_services_without_authorizing_work_and_stops_both(self):
        import httpx
        from information_extraction.workbench_client import WorkbenchClient, WorkbenchError

        with TemporaryDirectory(dir=ROOT / ".test-data", prefix="workbench-") as directory:
            backend_port, ui_port = free_port(), free_port()
            while ui_port == backend_port:
                ui_port = free_port()
            endpoint = f"http://127.0.0.1:{backend_port}"
            health = f"http://127.0.0.1:{ui_port}/_stcore/health"
            log_path = Path(directory) / "launcher.log"
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen([
                    sys.executable, str(ROOT / "scripts" / "run_workbench.py"),
                    "--parent-pipe", "--backend-port", str(backend_port), "--ui-port", str(ui_port),
                    "--state-dir", directory, "--job-id", "fresh-launcher-job",
                ], cwd=ROOT, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, text=True, env={
                    **os.environ, "AGENTSERVER_TASKS_BACKEND": "hosted", "FOUNDRY_HOSTING_ENVIRONMENT": "1",
                    "FOUNDRY_PROJECT_ENDPOINT": "https://invalid.example",
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "https://invalid.example",
                })
                try:
                    deadline = time.monotonic() + 40
                    with httpx.Client(timeout=1, trust_env=False) as probe:
                        while True:
                            if process.poll() is not None:
                                self.fail(log_path.read_text(encoding="utf-8"))
                            try:
                                response = probe.get(health)
                                if response.status_code == 200 and response.text == "ok":
                                    break
                            except httpx.HTTPError:
                                pass
                            if time.monotonic() > deadline:
                                self.fail("Streamlit did not become healthy.")
                            time.sleep(0.1)
                    with WorkbenchClient(endpoint) as client:
                        current = client.current()
                    self.assertEqual(current.job_id, "fresh-launcher-job")
                    self.assertIsNone(current.round)
                    self.assertIsNone(current.pending)
                    process.stdin.write("stop\n")
                    process.stdin.flush()
                    process.wait(timeout=20)
                    self.assertEqual(process.returncode, 0, log_path.read_text(encoding="utf-8"))
                    with WorkbenchClient(endpoint) as client, self.assertRaises(WorkbenchError):
                        client.current()
                    with httpx.Client(timeout=1, trust_env=False) as probe, self.assertRaises(httpx.HTTPError):
                        probe.get(health)
                finally:
                    process.stdin.close()
                    if process.poll() is None:
                        try:
                            process.wait(timeout=20)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)

    def test_backend_survives_client_recreation_and_preserves_completed_job_after_restart(self):
        from streamlit.testing.v1 import AppTest
        from information_extraction.workbench_client import WorkbenchClient, WorkbenchError

        with TemporaryDirectory(dir=ROOT / ".test-data", prefix="workbench-") as directory:
            port = free_port()
            endpoint = f"http://127.0.0.1:{port}"
            state = Path(directory)
            log_path = state / "process.log"
            command = [
                sys.executable, str(ROOT / "scripts" / "run_workbench.py"),
                "--backend-only", "--parent-pipe", "--backend-port", str(port),
                "--state-dir", str(state),
            ]

            def wait_current(process, predicate):
                deadline = time.monotonic() + 30
                last = "not ready"
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(log_path.read_text(encoding="utf-8"))
                    try:
                        with WorkbenchClient(endpoint) as client:
                            found = client.current()
                        if predicate(found):
                            return found
                        last = repr(found)
                    except WorkbenchError as error:
                        last = str(error)
                    time.sleep(0.05)
                self.fail(f"Backend did not reach expected state: {last}")

            def stop(process):
                if process.poll() is None:
                    process.stdin.write("stop\n")
                    process.stdin.flush()
                process.stdin.close()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    self.fail("Owned local backend did not stop gracefully.")

            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command, cwd=ROOT, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, text=True,
                )
                try:
                    initial = wait_current(process, lambda job: job.round is None)
                    with WorkbenchClient(endpoint) as client:
                        client.start(initial.job_id, max_attempts=1, duration_seconds=60)
                    limited = wait_current(process, lambda job: job.round is not None and job.round.state.value == "limited")
                    self.assertEqual(limited.round.revision, 1)
                    self.assertEqual([record.value for record in limited.round.candidates], [120])
                    with patch.dict(os.environ, {"INFORMATION_EXTRACTION_BACKEND_URL": endpoint}):
                        page = AppTest.from_file(str(ROOT / "workbench.py"), default_timeout=15).run()
                        self.assertEqual(len(page.exception), 0)
                        self.assertEqual(page.table[0].value["Value"].tolist(), [120])
                        page.button(key="resume").click().run()
                        self.assertEqual(len(page.exception), 0)
                    completed = wait_current(process, lambda job: job.round is not None and job.round.state.value == "completed")
                    self.assertEqual(completed.round.revision, 2)
                    self.assertEqual([record.value for record in completed.round.candidates], [120, 18])
                    self.assertEqual(completed.round.candidates[0], limited.round.candidates[0])
                    self.assertIsNone(completed.pending)
                finally:
                    stop(process)
                self.assertEqual(process.returncode, 0)

                process = subprocess.Popen(
                    command, cwd=ROOT, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, text=True,
                )
                try:
                    restored = wait_current(process, lambda job: job.round is not None)
                    self.assertNotEqual(restored.app_instance_id, initial.app_instance_id)
                    self.assertEqual(restored.round, completed.round)
                    self.assertIsNone(restored.pending)
                    with patch.dict(os.environ, {"INFORMATION_EXTRACTION_BACKEND_URL": endpoint}):
                        reopened = AppTest.from_file(str(ROOT / "workbench.py"), default_timeout=15).run()
                        self.assertEqual(len(reopened.exception), 0)
                        self.assertEqual(reopened.table[0].value["Value"].tolist(), [120, 18])
                        self.assertFalse({"start", "resume", "retry"} & {button.key for button in reopened.button})
                finally:
                    stop(process)
                self.assertEqual(process.returncode, 0)
