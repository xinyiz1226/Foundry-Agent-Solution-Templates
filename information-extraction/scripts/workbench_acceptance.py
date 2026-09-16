"""Offline acceptance: real local native processes and Streamlit AppTest, not a browser.

From information-extraction:
    .venv\\Scripts\\python.exe scripts\\workbench_acceptance.py

Only unique directories created beneath --temp-root are owned by this runner.
Successful runs remove them; failures retain state and process logs for inspection.
No cloud credentials, Azure resources, or real model calls are required.
The standard-library acceptance preparer supplies both fresh job/state bindings.
UI rounds use at most 60 seconds of its prepared duration allowance.
"""

import argparse
from collections import Counter
from contextlib import closing, contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
from unittest.mock import patch
from uuid import uuid4

if __package__:
    from .prepare_workbench_acceptance import prepare
else:
    from prepare_workbench_acceptance import prepare


ROOT = Path(__file__).resolve().parents[1]
WAIT_SECONDS = 30
SCOPE = {
    "backend": "local_native_subprocess",
    "ui": "streamlit_apptest",
    "model": "synthetic",
    "azure": "not_verified",
    "real_browser": "not_verified",
    "real_model_telemetry": "not_verified",
}
EXPECTED = (
    ("revenue", 120, "block-1", "synthetic:line:1", "ExampleCo revenue was USD 120 million."),
    ("operating_income", 18, "block-3", "synthetic:line:3", "ExampleCo operating income was USD 18 million."),
)


class AcceptanceFailure(RuntimeError):
    """An observed result did not satisfy the offline acceptance contract."""


def require(condition, message):
    if not condition:
        raise AcceptanceFailure(message)


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def ledger_snapshot(state):
    """Read every durable application ledger row without initializing/writing a store."""
    path = state / "ledger.sqlite3"
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("BEGIN")
        return {
            table: tuple(connection.execute(f"SELECT * FROM {table} ORDER BY rowid"))
            for table in ("jobs", "checkpoints", "requests", "claims", "batch_records")
        }


def prepared_scenarios(owned):
    path = prepare(owned)
    require(path.resolve().is_relative_to(owned.resolve()), "Prepared manifest escaped the owned root.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    require(
        manifest["format_version"] == 1 and manifest["synthetic_only"] is True
        and manifest["azure_changes_performed"] is False and manifest["cloud_execution_authorized"] is False,
        "Expected an offline-only preparation manifest.",
    )
    scenarios = manifest["scenarios"]
    require(
        [item["name"] for item in scenarios] == ["pause-resume", "single-start"],
        "Unexpected prepared acceptance scenarios.",
    )
    require(
        [item["round_attempt_allowances"] for item in scenarios] == [[1, 1], [2]],
        "Unexpected prepared attempt allowances.",
    )
    for scenario in scenarios:
        state = Path(scenario["local_state_dir"])
        require(
            state.is_absolute() and state.resolve().is_relative_to(path.parent.resolve()) and not state.exists(),
            "Prepared state must be fresh and inside the owned manifest directory.",
        )
        require(
            type(scenario["round_duration_seconds"]) is int and 10 <= scenario["round_duration_seconds"] <= 120,
            "Prepared round duration must be between 10 and 120 seconds.",
        )
        require(
            scenario["expected_final_revision"] == 2 and scenario["expected_committed_attempts"] == 2,
            "Unexpected prepared completion expectations.",
        )
        require(scenario["expected_candidates"] == [
            {"metric": metric, "value": value, "unit": "USD_millions", "block_id": block_id}
            for metric, value, block_id, _, _ in EXPECTED
        ], "Prepared candidates do not match the synthetic acceptance contract.")
    require(
        len({item["local_state_dir"] for item in scenarios}) == 2
        and len({item["hosted_environment"]["EXTRACTION_JOB_ID"] for item in scenarios}) == 2,
        "Prepared tasks must have independent job IDs and state directories.",
    )
    return scenarios


class Backend:
    def __init__(self, state, job_id):
        self.state = state
        self.job_id = job_id
        self.port = free_port()
        self.endpoint = f"http://127.0.0.1:{self.port}"
        self.process = None

    def check_process(self):
        require(
            self.process.poll() is None,
            f"Owned backend exited ({self.process.returncode}); inspect {self.state / 'backend.log'}.",
        )

    def current(self):
        from information_extraction.workbench_client import WorkbenchClient

        self.check_process()
        with WorkbenchClient(self.endpoint) as client:
            current = client.current()
        require(current.job_id == self.job_id, "Backend returned a different job ID.")
        return current

    def ready(self):
        import httpx

        deadline = time.monotonic() + WAIT_SECONDS
        with httpx.Client(timeout=1, trust_env=False, follow_redirects=False) as probe:
            while time.monotonic() < deadline:
                self.check_process()
                try:
                    response = probe.post(self.endpoint + "/invocations", json={"action": "current"})
                except httpx.ConnectError:
                    # Only listener-startup races are retried; malformed replies fail immediately.
                    time.sleep(0.05)
                    continue
                response.raise_for_status()
                return self.current()
        raise AcceptanceFailure(f"Backend startup exceeded {WAIT_SECONDS}s: {self.state}.")

    def wait_round(self, state):
        deadline = time.monotonic() + WAIT_SECONDS
        last = None
        while time.monotonic() < deadline:
            last = self.current()
            if last.round is not None and last.round.state.value == state and last.pending is None:
                return last
            if last.round is not None:
                require(last.round.state.value != "failed", f"Backend round failed: {last.round!r}")
            time.sleep(0.05)
        raise AcceptanceFailure(f"Backend did not reach {state} within {WAIT_SECONDS}s: {last!r}")


@contextmanager
def running_backend(state, job_id):
    try:
        from scripts.run_workbench import _local_environment, _stop
    except ModuleNotFoundError as error:
        if error.name != "scripts":
            raise
        from run_workbench import _local_environment, _stop

    state.mkdir(parents=True, exist_ok=True)
    backend = Backend(state, job_id)
    command = [
        sys.executable, str(ROOT / "scripts" / "run_workbench.py"),
        "--backend-only", "--parent-pipe", "--job-id", job_id,
        "--state-dir", str(state), "--backend-port", str(backend.port),
    ]
    with (state / "backend.log").open("a", encoding="utf-8") as log:
        backend.process = subprocess.Popen(
            command, cwd=ROOT, env=_local_environment(state, backend.port),
            stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, text=True,
        )
        try:
            backend.ready()
            yield backend
        finally:
            require(
                _stop(backend.process, backend=True),
                f"Owned backend did not stop cleanly; inspect {state / 'backend.log'}.",
            )


class Page:
    def __init__(self, backend):
        self.backend = backend
        self.clicks = Counter()
        self.transport_replays = Counter()
        self.authorizations = []
        self.page = None
        self.open()

    def run(self, action):
        with patch.dict(os.environ, {
            "INFORMATION_EXTRACTION_BACKEND_URL": self.backend.endpoint,
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
            "OTEL_SDK_DISABLED": "true",
        }):
            self.page = action()
        require(not self.page.exception, f"Streamlit exceptions: {self.page.exception!r}")
        require(not self.page.error, f"Streamlit errors: {[item.value for item in self.page.error]}")
        return self

    def open(self):
        from streamlit.testing.v1 import AppTest

        return self.run(lambda: AppTest.from_file(str(ROOT / "workbench.py"), default_timeout=15).run())

    def refresh(self):
        return self.run(lambda: self.page.button(key="refresh").click().run())

    def authorize(self, action, allowance, duration=60):
        require(action in ("start", "resume"), "Only explicit Start/Resume are acceptance mutations.")
        from information_extraction.workbench_client import WorkbenchClient

        original = WorkbenchClient._request
        captured = []

        def request(client, body, expected_status):
            result = original(client, body, expected_status)
            if body["action"] == action:
                captured.append((dict(body), result["authorization"]))
            return result

        self.page.number_input(key="attempts").set_value(allowance)
        self.page.number_input(key="duration").set_value(duration)
        before = time.time()
        self.clicks[action] += 1
        with patch.object(WorkbenchClient, "_request", new=request):
            self.run(lambda: self.page.button(key=action).click().run())
        require(len(captured) == 1, "One UI click must send exactly one authorization request.")
        self.authorizations.extend(captured)
        return before, time.time()

    def replay_last(self):
        """Replay a captured body unchanged, never renewing its request ID or deadline."""
        from information_extraction.workbench_client import WorkbenchClient

        body, authorization = self.authorizations[-1]
        before = self.backend.current()
        ledger = ledger_snapshot(self.backend.state)
        with WorkbenchClient(self.backend.endpoint) as client:
            self.transport_replays[body["action"]] += 1
            result = client._request(dict(body), 202)
        require(result["authorization"] == authorization, "Exact replay changed the original authorization.")
        require(self.backend.current() == before, "Exact replay changed the durable round/candidates.")
        require(ledger_snapshot(self.backend.state) == ledger, "Exact replay changed durable attempts or ledger rows.")

    def assert_records(self, count):
        from information_extraction.sample import synthetic_plan

        table = self.page.table[0].value
        require(table["Metric"].tolist() == [row[0] for row in EXPECTED[:count]], "UI metric mismatch.")
        require(table["Value"].tolist() == [row[1] for row in EXPECTED[:count]], "UI value mismatch.")
        require(table["Unit"].tolist() == ["USD_millions"] * count, "UI unit mismatch.")
        require(table["Review"].tolist() == ["Pending"] * count, "Candidates must remain unreviewed.")
        sources = [item for item in self.page.expander if item.label == "Source blocks"]
        require(len(sources) == 1, "Expected exactly one source-block panel.")
        blocks = [block for chunk in synthetic_plan().chunks for block in chunk.blocks]
        require(
            [item.value for item in sources[0].code] == [block.text for block in blocks],
            "UI source text mismatch.",
        )
        require(
            [item.value for item in sources[0].caption] == [f"{block.id} | {block.location}" for block in blocks],
            "UI source block/location mismatch.",
        )
        evidence = [item for item in self.page.expander if item.label.startswith("Evidence:")]
        require(len(evidence) == count, "UI candidate evidence count mismatch.")
        for panel, (metric, value, block_id, location, text) in zip(evidence, EXPECTED[:count]):
            require(panel.label == f"Evidence: {metric} = {value} USD_millions", "UI evidence label mismatch.")
            require([item.value for item in panel.code] == [text], "UI candidate evidence text mismatch.")
            require(
                [item.value for item in panel.caption][1:] == [f"{block_id} | {location}"],
                "UI candidate evidence block/location mismatch.",
            )

    def assert_completed(self):
        self.assert_records(2)
        require(
            not {"start", "resume", "retry"} & {button.key for button in self.page.button},
            "A completed page still exposes a mutation button.",
        )


def check_round(job, *, state, revision, allowance, count, click_window, duration=60):
    current = job.round
    require(current is not None and job.pending is None, "Expected a settled round without saved requests.")
    require(current.state.value == state and current.revision == revision, "Round state/revision mismatch.")
    require(current.max_attempts == allowance, "Round did not use the UI attempt allowance.")
    require(current.attempts_reserved == allowance, "Reserved attempts differ from the authorized scenario.")
    require(
        click_window[0] + duration <= current.deadline <= click_window[1] + duration,
        "Round did not use the UI's authorized duration.",
    )
    require(current.registration_confirmed, "Native registration was not confirmed.")
    require(current.committed_attempts == revision, "Committed-attempt projection mismatch.")
    require(current.completed_chunks == tuple(f"chunk-{index + 1}" for index in range(count)), "Chunk mismatch.")
    require(len(current.candidates) == count, "Candidate projection count mismatch.")
    for candidate, (metric, value, block_id, location, text) in zip(current.candidates, EXPECTED[:count]):
        require((candidate.metric, candidate.value, candidate.unit) == (metric, value, "USD_millions"), "Candidate mismatch.")
        require(
            [(item.block_id, item.location, item.text) for item in candidate.evidence] == [(block_id, location, text)],
            "Candidate source evidence mismatch.",
        )
    return current


def projection(current):
    return {
        "state": current.state.value,
        "revision": current.revision,
        "max_attempts": current.max_attempts,
        "attempts_reserved": current.attempts_reserved,
        "committed_attempts": current.committed_attempts,
        "completed_chunks": list(current.completed_chunks),
        "candidates": [
            {key: value for key, value in asdict(candidate).items() if key != "id"}
            for candidate in current.candidates
        ],
        "synthetic_usage": {
            "known_input_tokens": current.known_input_tokens,
            "known_output_tokens": current.known_output_tokens,
            "unknown_usage_attempts": current.unknown_usage_attempts,
        },
    }


def exercise(owned):
    first_spec, second_spec = prepared_scenarios(owned)
    first_id = first_spec["hosted_environment"]["EXTRACTION_JOB_ID"]
    second_id = second_spec["hosted_environment"]["EXTRACTION_JOB_ID"]
    first_state, second_state = Path(first_spec["local_state_dir"]), Path(second_spec["local_state_dir"])
    first_duration, second_duration = (
        min(60, specification["round_duration_seconds"]) for specification in (first_spec, second_spec)
    )
    start_allowance, resume_allowance = first_spec["round_attempt_allowances"]
    second_allowance, = second_spec["round_attempt_allowances"]
    with running_backend(first_state, first_id) as backend:
        initial = backend.current()
        require(initial.round is None and initial.pending is None, "First task was not fresh.")
        page = Page(backend)
        start_window = page.authorize("start", start_allowance, first_duration)
        limited_job = backend.wait_round("limited")
        limited = check_round(
            limited_job, state="limited", revision=1, allowance=start_allowance, count=1,
            click_window=start_window, duration=first_duration,
        )
        page.replay_last()
        limited_ledger = ledger_snapshot(first_state)
        page.refresh().assert_records(1)
        require(backend.current() == limited_job, "Refresh progressed the limited task.")
        page.open().assert_records(1)
        require(backend.current() == limited_job, "Page recreation progressed the limited task.")
        require(ledger_snapshot(first_state) == limited_ledger, "Read-only UI changed the limited ledger.")
        resume_window = page.authorize("resume", resume_allowance, first_duration)
        completed_job = backend.wait_round("completed")
        completed = check_round(
            completed_job, state="completed", revision=first_spec["expected_final_revision"],
            allowance=resume_allowance, count=2, click_window=resume_window, duration=first_duration,
        )
        page.replay_last()
        require(completed.candidates[:1] == limited.candidates, "Resume changed the earlier candidate.")
        page.refresh().assert_completed()
        before_restart = ledger_snapshot(first_state)

    with running_backend(first_state, first_id) as restarted:
        restored = restarted.current()
        require(restored.app_instance_id != initial.app_instance_id, "Restart reused the application instance ID.")
        require(restored.round == completed and restored.pending is None, "Restart changed the durable round.")
        require(ledger_snapshot(first_state) == before_restart, "Restart changed the application ledger.")
        Page(restarted).assert_completed()
        before_second = ledger_snapshot(first_state)
        with running_backend(second_state, second_id) as independent:
            fresh = independent.current()
            require(fresh.round is None and fresh.pending is None, "Second task was not fresh.")
            require(fresh.job_id != restored.job_id, "Second task reused the prior job ID.")
            second_page = Page(independent)
            second_window = second_page.authorize("start", second_allowance, second_duration)
            second = check_round(
                independent.wait_round("completed"), state="completed", revision=second_spec["expected_final_revision"],
                allowance=second_allowance, count=2, click_window=second_window, duration=second_duration,
            )
            second_page.replay_last()
            second_page.refresh().assert_completed()
            require(ledger_snapshot(first_state) == before_second, "Independent task changed the prior ledger.")
            prior = restarted.current()
            require(prior == restored, "Independent task changed the prior round/candidates.")
            Page(restarted).assert_completed()
        require(ledger_snapshot(first_state) == before_second, "Independent shutdown changed the prior ledger.")

    return {
        "bounded_resume": {
            "job_id": first_id, "ui_clicks": dict(page.clicks),
            "transport_replays": dict(page.transport_replays), "exact_replays_unchanged": True,
            "manifest_scenario": first_spec["name"], "round_duration_seconds": first_duration,
            "limited": projection(limited), "completed": projection(completed),
            "refresh_unchanged": True, "reopened_unchanged": True,
        },
        "restart": {
            "round_unchanged": True, "candidates_unchanged": True,
            "app_instance_changed": True, "completed_mutations_absent": True,
        },
        "independent_task": {
            "job_id": second_id, "ui_clicks": dict(second_page.clicks), "completed": projection(second),
            "transport_replays": dict(second_page.transport_replays), "exact_replays_unchanged": True,
            "manifest_scenario": second_spec["name"], "round_duration_seconds": second_duration,
            "prior_ledger_unchanged": True, "prior_candidates_unchanged": True,
        },
    }


def run_acceptance(temp_root=ROOT / ".test-data"):
    root = Path(temp_root).resolve()
    owned = root / ("workbench-acceptance-" + uuid4().hex)
    created = False
    try:
        root.mkdir(parents=True, exist_ok=True)
        owned.mkdir()
        created = True
        scenarios = exercise(owned)
        shutil.rmtree(owned)
    except Exception as error:
        # Report failures, including chained cleanup failures, rather than masking them.
        traceback.print_exc(file=sys.stderr)
        errors = []
        seen = set()
        while error is not None and id(error) not in seen:
            seen.add(id(error))
            errors.append({"type": type(error).__name__, "message": str(error)})
            error = error.__cause__ or error.__context__
        return {
            "schema_version": 1, "status": "failed", "scope": dict(SCOPE),
            "errors": errors, "retained_state_dir": str(owned) if created else None,
        }
    return {
        "schema_version": 1, "status": "passed", "scope": dict(SCOPE),
        "scenarios": scenarios,
        "cleanup": {"owned_processes_stopped": True, "owned_temp_removed": True},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temp-root", type=Path, default=ROOT / ".test-data")
    arguments = parser.parse_args(argv)
    report = run_acceptance(arguments.temp_root)
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
