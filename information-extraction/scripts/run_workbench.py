"""Local synthetic workbench runtime; never uses the hosted application factory."""

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Event, Thread
import time


ROOT = Path(__file__).resolve().parents[1]


def _port(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("Choose a port between 1 and 65535.")
    return number


def _local_environment(state: Path, backend_port: int) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("AZURE_", "FOUNDRY_", "AGENTSERVER_", "OTEL_", "APPLICATIONINSIGHTS_"))
    }
    environment.update({
        "PYTHONUNBUFFERED": "1",
        "AGENTSERVER_TASKS_BACKEND": "local",
        "AGENTSERVER_STATE_ROOT": str(state / "native-state"),
        "AGENTSERVER_SHUTDOWN_GRACE_SECONDS": "1",
        "FOUNDRY_HOSTING_ENVIRONMENT": "",
        "FOUNDRY_AGENT_NAME": "local-information-extraction",
        "FOUNDRY_AGENT_VERSION": "1",
        "FOUNDRY_AGENT_SESSION_ID": "local",
        "OTEL_SDK_DISABLED": "true",
        "SSE_KEEPALIVE_INTERVAL": "0",
        "WS_KEEPALIVE_INTERVAL": "0",
        "PORT": str(backend_port),
        "INFORMATION_EXTRACTION_BACKEND_URL": f"http://127.0.0.1:{backend_port}",
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
    })
    return environment


def _backend(state: Path, port: int, parent_pipe: bool, job_id: str = "synthetic-job") -> None:
    environment = _local_environment(state, port)
    os.environ.clear()
    os.environ.update(environment)
    from uvicorn import Config, Server
    from information_extraction import SQLiteStore
    from information_extraction.hosted_app import create_offline_app

    app = create_offline_app(SQLiteStore(state / "ledger.sqlite3"), job_id=job_id)
    server = Server(Config(
        app, host="127.0.0.1", port=port, log_level="warning",
        timeout_graceful_shutdown=5,
    ))
    if parent_pipe:
        def watch_parent():
            # A stop line or EOF from the owning launcher requests normal lifespan cleanup.
            sys.stdin.readline()
            server.should_exit = True

        Thread(target=watch_parent, daemon=True).start()
    server.run()


def _available_port(port: int) -> None:
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", port))
    except OSError:
        raise RuntimeError(f"Port {port} is unavailable. Choose another port; no existing service was stopped.") from None


def _stop(process: subprocess.Popen, *, backend: bool) -> bool:
    if backend and process.stdin is not None:
        try:
            if process.poll() is None:
                process.stdin.write("stop\n")
                process.stdin.flush()
            process.stdin.close()
        except OSError:
            print("Backend control pipe closed unexpectedly; waiting for its exit.", file=sys.stderr)
    elif process.poll() is None:
        process.terminate()
    try:
        code = process.wait(timeout=15)
        if backend and code != 0:
            print(f"Backend exited with code {code}; inspect backend.log and retained state.", file=sys.stderr)
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"Owned process {process.pid} did not stop gracefully; forcing exit. Inspect retained state.", file=sys.stderr)
        process.kill()
        process.wait(timeout=5)
        return False


def _launch(
    state: Path, backend_port: int, ui_port: int, parent_pipe: bool, job_id: str = "synthetic-job",
) -> None:
    import httpx
    from information_extraction.workbench_client import WorkbenchClient, WorkbenchError

    if backend_port == ui_port:
        raise RuntimeError("The backend and UI need different ports.")
    _available_port(backend_port)
    _available_port(ui_port)
    environment = _local_environment(state, backend_port)
    children = []
    stopping = Event()
    if parent_pipe:
        def watch_parent():
            sys.stdin.readline()
            stopping.set()

        Thread(target=watch_parent, daemon=True).start()

    def wait_ready(process, probe, label):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"{label} exited during startup. See the logs in {state}.")
            if stopping.is_set():
                raise RuntimeError("The launcher owner disconnected during startup.")
            try:
                if probe():
                    return
            except (WorkbenchError, httpx.HTTPError):
                # Read-only startup probes may precede the listener; mutations are never retried.
                pass
            time.sleep(0.1)
        raise RuntimeError(f"{label} did not become healthy. See the logs in {state}.")

    with (
        (state / "backend.log").open("a", encoding="utf-8") as backend_log,
        (state / "streamlit.log").open("a", encoding="utf-8") as ui_log,
    ):
        try:
            backend = subprocess.Popen([
                sys.executable, str(Path(__file__).resolve()), "--backend-only", "--parent-pipe",
                "--backend-port", str(backend_port), "--state-dir", str(state),
                "--job-id", job_id,
            ], cwd=ROOT, env=environment, stdin=subprocess.PIPE,
                stdout=backend_log, stderr=subprocess.STDOUT, text=True)
            children.append((backend, True))
            with WorkbenchClient(environment["INFORMATION_EXTRACTION_BACKEND_URL"]) as client:
                wait_ready(backend, client.current, "Backend")

            ui = subprocess.Popen([
                sys.executable, "-m", "streamlit", "run", str(ROOT / "workbench.py"),
                "--server.address=127.0.0.1", f"--server.port={ui_port}",
                "--server.headless=true", "--browser.gatherUsageStats=false",
                "--server.enableCORS=true", "--server.enableXsrfProtection=true",
            ], cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                stdout=ui_log, stderr=subprocess.STDOUT)
            children.append((ui, False))
            url = f"http://127.0.0.1:{ui_port}"
            with httpx.Client(timeout=1, trust_env=False, follow_redirects=False) as probe:
                def healthy():
                    response = probe.get(url + "/_stcore/health")
                    return response.status_code == 200 and response.text == "ok"

                wait_ready(ui, healthy, "Streamlit")
            print(f"Workbench: {url}\nBackend: {environment['INFORMATION_EXTRACTION_BACKEND_URL']}\nState: {state}", flush=True)
            print("Local synthetic only. Ctrl+C stops owned services; state is retained.", flush=True)
            while not stopping.wait(0.5):
                for process, is_backend in children:
                    if process.poll() is not None:
                        label = "Backend" if is_backend else "Streamlit"
                        raise RuntimeError(f"{label} exited unexpectedly. See the logs in {state}.")
        except KeyboardInterrupt:
            print("Stopping owned services; durable state is retained.", flush=True)
        finally:
            clean = True
            for process, is_backend in reversed(children):
                clean = _stop(process, backend=is_backend) and clean
            if not clean:
                raise RuntimeError("An owned service did not stop cleanly. Inspect the retained job before resuming.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=ROOT / ".local-data" / "workbench")
    parser.add_argument("--backend-port", type=_port, default=8765)
    parser.add_argument("--ui-port", type=_port, default=8501)
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--parent-pipe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--job-id", default="synthetic-job",
        help="Server-owned synthetic job; use a fresh state directory for a new job.",
    )
    arguments = parser.parse_args()
    state = arguments.state_dir.resolve()
    try:
        from information_extraction.contracts import InvalidInput, validate_identifier

        try:
            validate_identifier(arguments.job_id)
        except InvalidInput:
            parser.error("job-id must be a valid execution identifier")
        state.mkdir(parents=True, exist_ok=True)
        if arguments.backend_only:
            _backend(state, arguments.backend_port, arguments.parent_pipe, arguments.job_id)
        else:
            _launch(state, arguments.backend_port, arguments.ui_port, arguments.parent_pipe, arguments.job_id)
    except ImportError:
        print('Install the optional dependencies: python -m pip install -e ".[hosted,workbench]"', file=sys.stderr)
        return 1
    except (OSError, RuntimeError) as error:
        print(f"Local workbench failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
