"""Local upload/profile workbench; prepare-only unless real inference is explicitly enabled."""

import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys
from threading import Event, Thread
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_workbench import ROOT, _available_port, _local_environment, _port, _stop
from scripts.import_abcd import _local_path


def prepare_state(path: Path) -> None:
    path = _local_path(path)
    path.mkdir(parents=True, exist_ok=True)
    marker = path / ".configured-workbench-v1"
    _local_path(marker)
    expected = b"configured-local-workbench-v1\n"
    if not marker.exists():
        if any(path.iterdir()):
            raise RuntimeError("dedicated_empty_configured_state_directory_required")
        try:
            with marker.open("xb") as stream:
                stream.write(expected)
        except FileExistsError:
            pass
    with marker.open("rb") as stream:
        if stream.read(len(expected) + 1) != expected:
            raise RuntimeError("configured_state_owner_mismatch")


def environment(args, token: str) -> dict[str, str]:
    result = {key: value for key, value in _local_environment(args.state_dir, args.backend_port).items()
              if not key.startswith("OPENAI_")}
    result.update({
        "INFORMATION_EXTRACTION_CONFIGURED_BACKEND_URL": f"http://127.0.0.1:{args.backend_port}",
        "INFORMATION_EXTRACTION_CONFIGURED_TOKEN": token,
    })
    if args.real_model:
        result["AZURE_CONFIG_DIR"] = str(args.azure_config_dir)
    return result


def backend(args) -> None:
    token = os.environ.get("INFORMATION_EXTRACTION_CONFIGURED_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("missing_private_backend_token")
    clean = environment(args, token)
    os.environ.clear()
    os.environ.update(clean)
    from uvicorn import Config, Server
    from information_extraction import SQLiteStore
    from information_extraction.configured_app import create_configured_app
    from information_extraction.configured_runtime import FoundryProvider, PrepareOnlyProvider

    store = SQLiteStore(args.state_dir / "configured-workbench-v1.sqlite3")
    provider = PrepareOnlyProvider()
    if args.real_model:
        from azure.identity import AzureCliCredential
        from azure.core.exceptions import ClientAuthenticationError
        from information_extraction.contracts import InvalidInput
        from information_extraction.foundry_model import FoundrySettings

        settings = FoundrySettings(
            args.project_endpoint, args.deployment, max_output_tokens=args.max_output_tokens,
            timeout=args.timeout, reasoning_effort=args.reasoning_effort,
        )
        try:
            with AzureCliCredential() as credential:
                credential.get_token("https://ai.azure.com/.default")
        except ClientAuthenticationError:
            raise InvalidInput("azure_cli_login_required_or_denied") from None
        provider = FoundryProvider(store, settings, AzureCliCredential, call_limit=args.model_call_limit,
                                   budget_id=args.budget_id)
    app = create_configured_app(store, provider, token=token)
    server = Server(Config(app, host="127.0.0.1", port=args.backend_port, log_level="warning",
                           access_log=False, timeout_graceful_shutdown=5))
    if args.parent_pipe:
        def watch_parent():
            sys.stdin.readline()
            server.should_exit = True

        Thread(target=watch_parent, daemon=True).start()
    server.run()


def launch(args) -> None:
    import httpx
    from information_extraction.configured_client import ConfiguredClient, ConfiguredWorkbenchError

    if args.backend_port == args.ui_port:
        raise RuntimeError("backend_and_ui_ports_must_differ")
    _available_port(args.backend_port)
    _available_port(args.ui_port)
    token = os.environ.get("INFORMATION_EXTRACTION_CONFIGURED_TOKEN") or secrets.token_urlsafe(32)
    if len(token) < 32 or not token.isascii():
        raise RuntimeError("invalid_private_backend_token")
    child_environment = environment(args, token)
    stopping = Event()
    children = []
    if args.parent_pipe:
        def watch_parent():
            sys.stdin.readline()
            stopping.set()

        Thread(target=watch_parent, daemon=True).start()

    def wait_ready(process, probe):
        deadline = time.monotonic() + 45
        last_code = "not_ready"
        while time.monotonic() < deadline:
            if process.poll() is not None or stopping.is_set():
                raise RuntimeError("configured_process_exited_during_startup")
            try:
                if probe():
                    return
            except (ConfiguredWorkbenchError, httpx.HTTPError):
                last_code = "startup_read_not_ready"
            time.sleep(0.1)
        raise RuntimeError(last_code)

    with (
        (args.state_dir / "configured-backend.log").open("a", encoding="utf-8") as backend_log,
        (args.state_dir / "configured-streamlit.log").open("a", encoding="utf-8") as ui_log,
    ):
        try:
            command = [
                sys.executable, "-m", "scripts.run_configured_workbench", "--backend-only", "--parent-pipe",
                "--state-dir", str(args.state_dir), "--backend-port", str(args.backend_port),
            ]
            if args.real_model:
                command += [
                    "--real-model", "--project-endpoint", args.project_endpoint, "--deployment", args.deployment,
                    "--azure-config-dir", str(args.azure_config_dir), "--model-call-limit", str(args.model_call_limit),
                    "--budget-id", args.budget_id,
                    "--max-output-tokens", str(args.max_output_tokens), "--timeout", str(args.timeout),
                ]
                if args.reasoning_effort is not None:
                    command += ["--reasoning-effort", args.reasoning_effort]
            worker = subprocess.Popen(command, cwd=ROOT, env=child_environment, stdin=subprocess.PIPE,
                                      stdout=backend_log, stderr=subprocess.STDOUT, text=True)
            children.append((worker, True))
            url = child_environment["INFORMATION_EXTRACTION_CONFIGURED_BACKEND_URL"]
            with ConfiguredClient(url, token) as client:
                wait_ready(worker, client.configuration)
            ui_environment = {
                key: value for key, value in child_environment.items()
                if not key.startswith(("AZURE_", "FOUNDRY_", "AGENTSERVER_", "OTEL_", "APPLICATIONINSIGHTS_"))
            }
            ui = subprocess.Popen([
                sys.executable, "-m", "streamlit", "run", str(ROOT / "configured_workbench.py"),
                "--server.address=127.0.0.1", f"--server.port={args.ui_port}",
                "--server.headless=true", "--browser.gatherUsageStats=false",
                "--server.enableCORS=true", "--server.enableXsrfProtection=true",
                "--server.maxUploadSize=1",
            ], cwd=ROOT, env=ui_environment, stdin=subprocess.DEVNULL,
                stdout=ui_log, stderr=subprocess.STDOUT)
            children.append((ui, False))
            with httpx.Client(timeout=1, trust_env=False, follow_redirects=False) as probe:
                def healthy():
                    response = probe.get(f"http://127.0.0.1:{args.ui_port}/_stcore/health")
                    return response.status_code == 200 and response.text == "ok"

                wait_ready(ui, healthy)
            print(f"Configured workbench: http://127.0.0.1:{args.ui_port}", flush=True)
            print("Loopback only. Separate backend; closing the browser does not stop execution.", flush=True)
            print("Real inference enabled; durable call limit applies." if args.real_model
                  else "Prepare-only mode; no model calls are possible.", flush=True)
            while not stopping.wait(0.5):
                if any(process.poll() is not None for process, _ in children):
                    raise RuntimeError("configured_child_exited_inspect_retained_state")
        except KeyboardInterrupt:
            print("Stopping owned processes; preserving state.", flush=True)
        finally:
            clean = True
            for process, is_backend in reversed(children):
                clean = _stop(process, backend=is_backend) and clean
            if not clean:
                raise RuntimeError("configured_shutdown_incomplete_inspect_before_resume")


def main(argv=None) -> int:
    from information_extraction.contracts import ExecutionError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=ROOT / ".local-data" / "configured-workbench")
    parser.add_argument("--backend-port", type=_port, default=8766)
    parser.add_argument("--ui-port", type=_port, default=8502)
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--parent-pipe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--real-model", action="store_true")
    parser.add_argument("--project-endpoint")
    parser.add_argument("--deployment")
    parser.add_argument("--azure-config-dir", type=Path)
    parser.add_argument("--model-call-limit", type=int, choices=range(1, 6), default=5)
    parser.add_argument("--budget-id", default="initial",
                        help="Explicit named authorization grant; restarting reuses its remaining calls.")
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--reasoning-effort")
    args = parser.parse_args(argv)
    if args.real_model:
        if not args.project_endpoint or not args.deployment or args.azure_config_dir is None:
            parser.error("Real mode requires an explicit endpoint, deployment and Azure CLI configuration directory.")
        args.azure_config_dir = args.azure_config_dir.resolve()
        if not args.azure_config_dir.is_dir():
            parser.error("Azure CLI configuration directory does not exist; sign in separately first.")
    args.state_dir = args.state_dir.absolute()
    try:
        prepare_state(args.state_dir)
        if args.backend_only:
            backend(args)
        else:
            launch(args)
    except ImportError:
        print('Install optional dependencies: pip install -e ".[hosted,workbench,azure]"', file=sys.stderr)
        return 1
    except (ExecutionError, OSError, RuntimeError):
        print("Configured workbench failed; inspect retained state and sanitized local logs.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
