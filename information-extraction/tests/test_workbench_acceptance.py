"""Acceptance report contract, owned cleanup, and the real offline UI/process flow."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.metadata
import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from scripts import workbench_acceptance as acceptance


ROOT = Path(__file__).resolve().parents[1]
try:
    for package in ("streamlit", "httpx", "azure-ai-agentserver-invocations", "azure-ai-agentserver-core"):
        importlib.metadata.version(package)
    AVAILABLE = True
except importlib.metadata.PackageNotFoundError:
    AVAILABLE = False


class OwnedDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / ".test-data" / ("acceptance-test-" + uuid4().hex)
        self.directory.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.directory)
        self.sentinel = self.directory / "unrelated.txt"
        self.sentinel.write_text("preserve me", encoding="utf-8")

    def test_success_json_shape_and_only_owned_directory_removed(self):
        stdout = io.StringIO()
        with patch.object(acceptance, "exercise", return_value={"observed": True}) as exercise:
            with redirect_stdout(stdout):
                code = acceptance.main(["--temp-root", str(self.directory)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {
            "schema_version": 1, "status": "passed", "scope": acceptance.SCOPE,
            "scenarios": {"observed": True},
            "cleanup": {"owned_processes_stopped": True, "owned_temp_removed": True},
        })
        self.assertEqual(len(stdout.getvalue().splitlines()), 1)
        owned = exercise.call_args.args[0]
        self.assertEqual(owned.parent, self.directory.resolve())
        self.assertFalse(owned.exists())
        self.assertEqual(list(self.directory.iterdir()), [self.sentinel])
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "preserve me")

    def test_failure_retains_owned_state_reports_original_and_cleanup_failure(self):
        def fail(owned):
            (owned / "diagnostic.txt").write_text("retained", encoding="utf-8")
            try:
                raise acceptance.AcceptanceFailure("UI assertion failed")
            except acceptance.AcceptanceFailure as error:
                raise RuntimeError("owned backend cleanup failed") from error

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(acceptance, "exercise", side_effect=fail):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = acceptance.main(["--temp-root", str(self.directory)])
        self.assertEqual(code, 1)
        report = json.loads(stdout.getvalue())
        retained = Path(report["retained_state_dir"])
        self.assertEqual(report, {
            "schema_version": 1, "status": "failed", "scope": acceptance.SCOPE,
            "errors": [
                {"type": "RuntimeError", "message": "owned backend cleanup failed"},
                {"type": "AcceptanceFailure", "message": "UI assertion failed"},
            ],
            "retained_state_dir": str(retained),
        })
        self.assertEqual(retained.parent, self.directory.resolve())
        self.assertEqual((retained / "diagnostic.txt").read_text(encoding="utf-8"), "retained")
        self.assertTrue(self.sentinel.exists())
        self.assertIn("UI assertion failed", stderr.getvalue())
        self.assertIn("owned backend cleanup failed", stderr.getvalue())

    def test_unusable_root_is_a_failed_machine_report_without_claiming_ownership(self):
        with redirect_stderr(io.StringIO()):
            report = acceptance.run_acceptance(self.sentinel)
        self.assertEqual(report["status"], "failed")
        self.assertIsNone(report["retained_state_dir"])
        self.assertEqual(report["errors"][0]["type"], "FileExistsError")
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "preserve me")

    def test_ledger_snapshot_is_read_only_and_closes_windows_handle(self):
        database = self.directory / "ledger.sqlite3"
        connection = sqlite3.connect(database)
        try:
            for table in ("jobs", "checkpoints", "requests", "claims", "batch_records"):
                connection.execute(f"CREATE TABLE {table} (value TEXT)")
                connection.execute(f"INSERT INTO {table} VALUES ('saved')")
            connection.commit()
        finally:
            connection.close()
        before = database.read_bytes()
        self.assertEqual(acceptance.ledger_snapshot(self.directory), {
            table: (("saved",),)
            for table in ("jobs", "checkpoints", "requests", "claims", "batch_records")
        })
        self.assertEqual(before, database.read_bytes())
        database.unlink()
        self.assertFalse(database.exists())

    def test_process_startup_failure_stops_exact_owned_process(self):
        from scripts import run_workbench

        process = Mock()
        with (
            patch.object(acceptance.subprocess, "Popen", return_value=process) as popen,
            patch.object(acceptance.Backend, "ready", side_effect=acceptance.AcceptanceFailure("startup failed")),
            patch.object(run_workbench, "_stop", return_value=True) as stop,
        ):
            with self.assertRaisesRegex(acceptance.AcceptanceFailure, "startup failed"):
                with acceptance.running_backend(self.directory / "backend", "acceptance-test"):
                    self.fail("Failed startup must not yield a backend.")
        stop.assert_called_once_with(process, backend=True)
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--job-id") + 1], "acceptance-test")
        self.assertIn("--parent-pipe", command)
        self.assertIn("--backend-only", command)
        environment = popen.call_args.kwargs["env"]
        self.assertEqual(environment["AGENTSERVER_TASKS_BACKEND"], "local")
        self.assertEqual(environment["OTEL_SDK_DISABLED"], "true")

    def test_process_cleanup_failure_is_not_reported_as_success(self):
        from scripts import run_workbench

        with (
            patch.object(acceptance.subprocess, "Popen"),
            patch.object(acceptance.Backend, "ready"),
            patch.object(run_workbench, "_stop", return_value=False),
        ):
            with self.assertRaisesRegex(acceptance.AcceptanceFailure, "did not stop cleanly"):
                with acceptance.running_backend(self.directory / "backend", "acceptance-test"):
                    pass

    def test_poll_errors_are_not_swallowed_or_retried(self):
        backend = acceptance.Backend(self.directory, "acceptance-test")
        backend.current = Mock(side_effect=RuntimeError("invalid projection"))
        with self.assertRaisesRegex(RuntimeError, "invalid projection"):
            backend.wait_round("limited")
        backend.current.assert_called_once_with()

    def test_read_only_poll_has_a_deadline(self):
        backend = acceptance.Backend(self.directory, "acceptance-test")
        backend.current = Mock()
        with patch.object(acceptance, "WAIT_SECONDS", 0):
            with self.assertRaisesRegex(acceptance.AcceptanceFailure, "within 0s"):
                backend.wait_round("completed")
        backend.current.assert_not_called()

    @unittest.skipUnless(AVAILABLE, "optional hosted/workbench dependencies unavailable")
    def test_acceptance_never_retries_a_ui_mutation(self):
        page = acceptance.Page.__new__(acceptance.Page)
        page.page = Mock()
        page.clicks = acceptance.Counter()
        page.run = Mock(side_effect=acceptance.AcceptanceFailure("mutation failed"))
        with self.assertRaisesRegex(acceptance.AcceptanceFailure, "mutation failed"):
            page.authorize("start", 1)
        self.assertEqual(page.clicks, {"start": 1})
        page.run.assert_called_once()
        with self.assertRaisesRegex(acceptance.AcceptanceFailure, "Only explicit Start/Resume"):
            page.authorize("retry", 1)
        page.run.assert_called_once()

    def test_report_counts_are_copied_from_the_actual_projection(self):
        current = SimpleNamespace(
            state=SimpleNamespace(value="limited"), revision=3, max_attempts=4,
            attempts_reserved=2, committed_attempts=3, completed_chunks=("chunk-1",),
            candidates=(), known_input_tokens=37, known_output_tokens=11, unknown_usage_attempts=1,
        )
        self.assertEqual(acceptance.projection(current), {
            "state": "limited", "revision": 3, "max_attempts": 4,
            "attempts_reserved": 2, "committed_attempts": 3, "completed_chunks": ["chunk-1"],
            "candidates": [],
            "synthetic_usage": {"known_input_tokens": 37, "known_output_tokens": 11, "unknown_usage_attempts": 1},
        })

    def test_prepared_manifest_supplies_actual_scenario_ids_and_fresh_state_paths(self):
        with patch.object(acceptance, "prepare", wraps=acceptance.prepare) as prepare:
            scenarios = acceptance.prepared_scenarios(self.directory)
        prepare.assert_called_once_with(self.directory)
        manifests = [directory / "acceptance.json" for directory in self.directory.glob("acceptance-*")]
        self.assertEqual(len(manifests), 1)
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        self.assertEqual(scenarios, manifest["scenarios"])
        for scenario in scenarios:
            self.assertTrue(Path(scenario["local_state_dir"]).is_relative_to(manifests[0].parent))
            self.assertFalse(Path(scenario["local_state_dir"]).exists())
            self.assertEqual(
                scenario["hosted_environment"]["EXTRACTION_JOB_ID"],
                f"{manifests[0].parent.name}-{scenario['name']}",
            )
        self.assertTrue(self.sentinel.exists())

    def test_prepared_manifest_cannot_retarget_unowned_or_existing_state(self):
        path = acceptance.prepare(self.directory)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["scenarios"][0]["local_state_dir"] = str(self.directory)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with patch.object(acceptance, "prepare", return_value=path):
            with self.assertRaisesRegex(acceptance.AcceptanceFailure, "fresh and inside"):
                acceptance.prepared_scenarios(self.directory)
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "preserve me")


@unittest.skipUnless(AVAILABLE, "optional hosted/workbench dependencies unavailable")
class NativeWorkbenchAcceptanceTests(unittest.TestCase):
    def test_cli_runs_fresh_limited_resume_restart_and_independent_task(self):
        directory = ROOT / ".test-data" / ("native-acceptance-test-" + uuid4().hex)
        directory.mkdir(parents=True)
        sentinel = directory / "unrelated.txt"
        sentinel.write_text("keep", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "workbench_acceptance.py"), "--temp-root", str(directory)],
            cwd=ROOT, capture_output=True, text=True, timeout=180,
        )
        # Leave the runner's diagnostic state intact if real acceptance fails.
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.addCleanup(shutil.rmtree, directory)
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(set(report), {"schema_version", "status", "scope", "scenarios", "cleanup"})
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["scope"], {
            "backend": "local_native_subprocess", "ui": "streamlit_apptest", "model": "synthetic",
            "azure": "not_verified", "real_browser": "not_verified", "real_model_telemetry": "not_verified",
        })
        self.assertEqual(report["cleanup"], {"owned_processes_stopped": True, "owned_temp_removed": True})
        scenarios = report["scenarios"]
        self.assertEqual(set(scenarios), {"bounded_resume", "restart", "independent_task"})
        bounded, independent = scenarios["bounded_resume"], scenarios["independent_task"]
        self.assertTrue(bounded["job_id"].startswith("acceptance-"))
        self.assertNotEqual(bounded["job_id"], independent["job_id"])
        self.assertTrue(bounded["job_id"].endswith("-pause-resume"))
        self.assertEqual(
            bounded["job_id"].removesuffix("-pause-resume"),
            independent["job_id"].removesuffix("-single-start"),
        )
        candidates = [{
            "metric": metric, "value": value, "unit": "USD_millions",
            "evidence": [{"block_id": block_id, "location": location, "text": text}],
        } for metric, value, block_id, location, text in acceptance.EXPECTED]

        def expected_projection(state, revision, allowance):
            return {
                "state": state, "revision": revision, "max_attempts": allowance,
                "attempts_reserved": allowance, "committed_attempts": revision,
                "completed_chunks": [f"chunk-{index + 1}" for index in range(revision)],
                "candidates": candidates[:revision],
                "synthetic_usage": {"known_input_tokens": 0, "known_output_tokens": 0, "unknown_usage_attempts": 0},
            }

        self.assertEqual(bounded, {
            "job_id": bounded["job_id"], "ui_clicks": {"start": 1, "resume": 1},
            "transport_replays": {"start": 1, "resume": 1}, "exact_replays_unchanged": True,
            "manifest_scenario": "pause-resume", "round_duration_seconds": 60,
            "limited": expected_projection("limited", 1, 1),
            "completed": expected_projection("completed", 2, 1),
            "refresh_unchanged": True, "reopened_unchanged": True,
        })
        self.assertEqual(scenarios["restart"], {
            "round_unchanged": True, "candidates_unchanged": True,
            "app_instance_changed": True, "completed_mutations_absent": True,
        })
        self.assertEqual(independent, {
            "job_id": independent["job_id"], "ui_clicks": {"start": 1},
            "transport_replays": {"start": 1}, "exact_replays_unchanged": True,
            "manifest_scenario": "single-start", "round_duration_seconds": 60,
            "completed": expected_projection("completed", 2, 2),
            "prior_ledger_unchanged": True, "prior_candidates_unchanged": True,
        })
        self.assertEqual(list(directory.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
