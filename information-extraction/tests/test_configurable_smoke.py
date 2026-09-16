from contextlib import closing, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from information_extraction import Execution, SQLiteStore
from information_extraction.contracts import (
    Action, Conflict, DialogueBlock, ExecutionError, ModelRequest, ReviewStatus, Status,
)
from scripts.configurable_smoke import (
    DATABASE_NAME, FINANCIAL_JOB, SUPPORT_JOBS, ScriptedFixtureModel,
    fixture_plans, main, run_smoke,
)


class ConfigurableSmokeTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(".test-data") / f"configurable-smoke-{uuid4().hex}"
        self.directory.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.directory)
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.create_connection"):
            blocker = patch(target, side_effect=AssertionError("network_access_forbidden"))
            blocker.start()
            self.addCleanup(blocker.stop)

    def test_two_domains_and_exact_zero_call_rerun(self):
        first = run_smoke(self.directory)
        self.assertEqual(first["synthetic_model_calls"], 5)
        self.assertEqual(first["real_model_calls"], 0)
        self.assertEqual(first["replay_model_calls"], 0)
        self.assertTrue(first["historical_replay_verified"])
        self.assertTrue(first["durable_reopen_verified"])
        self.assertTrue(first["explicit_resume_verified"])
        self.assertFalse(first["semantic_validation_performed"])
        self.assertEqual(first["domains"]["financial"], {
            "documents": 1, "records": 2, "revisions": [3],
        })
        self.assertEqual(first["domains"]["support"], {
            "documents": 2, "records": 2, "revisions": [1, 1],
        })
        before = self._ledger_rows()
        with patch.object(ScriptedFixtureModel, "complete",
                          side_effect=AssertionError("rerun_must_not_call_model")):
            second = run_smoke(self.directory)
        self.assertEqual(second, dict(first, synthetic_model_calls=0))
        self.assertEqual(self._ledger_rows(), before)

    def _ledger_rows(self):
        with closing(sqlite3.connect(self.directory / DATABASE_NAME)) as connection:
            return {
                table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in ("jobs", "checkpoints", "requests", "claims")
            }

    def test_durable_fields_original_evidence_nullable_and_review_state(self):
        run_smoke(self.directory)
        store = SQLiteStore(self.directory / DATABASE_NAME)
        financial = store.read(FINANCIAL_JOB)
        self.assertEqual([c.record.to_dict()["value"] for c in financial.candidates], [120, 18])
        self.assertEqual(financial.status, Status.COMPLETED)
        self.assertEqual([attempt.failure_code for attempt in financial.attempts],
                         [None, "model_timeout", None])
        for job in (FINANCIAL_JOB, *SUPPORT_JOBS):
            snapshot = store.read(job)
            for candidate in snapshot.candidates:
                self.assertEqual(candidate.review_status, ReviewStatus.PENDING)
                self.assertIs(candidate.semantic_validation_performed, False)
                self.assertEqual(candidate.plan_fingerprint, snapshot.plan_fingerprint)
        lamp = store.read(SUPPORT_JOBS[0])
        chair = store.read(SUPPORT_JOBS[1])
        for snapshot in (lamp, chair):
            self.assertEqual(len(snapshot.plan.chunks), 1)
            for block in snapshot.plan.chunks[0].blocks:
                self.assertIsInstance(block, DialogueBlock)
                self.assertIn(block.speaker, ("customer", "agent"))
                self.assertNotIn("HIDDEN", block.text)
                self.assertNotIn("INTERNAL_METADATA", block.text)
        self.assertEqual([block.id for block in lamp.plan.chunks[0].blocks],
                         ["turn-1", "turn-2", "turn-3", "turn-5"])
        lamp_record = lamp.candidates[0]
        self.assertEqual(lamp_record.record.to_dict()["outcome_status"], "pending")
        lamp_evidence = {item.name: item.block_ids for item in lamp_record.field_evidence}
        self.assertEqual(lamp_evidence["attempted_action"], ("turn-3",))
        self.assertEqual(lamp_evidence["outcome_status"], ("turn-5",))
        chair_record = chair.candidates[0]
        self.assertIsNone(chair_record.record.to_dict()["attempted_action"])
        self.assertEqual(
            next(item.block_ids for item in chair_record.field_evidence
                 if item.name == "attempted_action"), (),
        )
        for candidate in lamp.candidates:
            for evidence in candidate.evidence:
                block = next(block for block in lamp.plan.chunks[0].blocks
                             if block.id == evidence.block_id)
                self.assertEqual((evidence.text, evidence.location), (block.text, block.location))

    def test_rejects_changed_existing_profile_without_mutating_ledger(self):
        plans = fixture_plans()
        plan = plans[SUPPORT_JOBS[0]]
        changed = replace(plan, profile=replace(plan.profile, instructions="Different frozen rules."))
        store = SQLiteStore(self.directory / DATABASE_NAME)
        store.create(SUPPORT_JOBS[0], changed, "other-config-create")
        before = self._ledger_rows()
        with self.assertRaisesRegex(Conflict, "incompatible_existing_fixture_configuration"):
            run_smoke(self.directory)
        self.assertEqual(self._ledger_rows(), before)

    def test_scripted_model_rejects_arbitrary_plan_and_request(self):
        plan = fixture_plans()[FINANCIAL_JOB]
        model = ScriptedFixtureModel()
        request = ModelRequest(
            FINANCIAL_JOB, f"{FINANCIAL_JOB}:advance:1", 0, plan.chunks[0], plan,
        )
        for changed in (
            replace(request, request_id="unknown"),
            replace(request, revision=9),
            replace(request, job_id="synthetic-job"),
            replace(request, plan=replace(plan, document_id="unsupported-document")),
            replace(request, chunk=plan.chunks[1]),
        ):
            with self.assertRaises(ExecutionError):
                model.complete(changed)
        self.assertEqual(model.calls, 0)

    def test_rejects_unresolved_claim_without_reset(self):
        plan = fixture_plans()[FINANCIAL_JOB]
        store = SQLiteStore(self.directory / DATABASE_NAME)
        store.create(FINANCIAL_JOB, plan, f"{FINANCIAL_JOB}:create")
        store.claim(FINANCIAL_JOB, 0, f"{FINANCIAL_JOB}:advance:1", Action.ADVANCE)
        before = self._ledger_rows()
        with self.assertRaisesRegex(Conflict, "incompatible_existing_fixture_history"):
            run_smoke(self.directory)
        self.assertEqual(self._ledger_rows(), before)

    def test_rejects_modified_source_before_creating_ledger(self):
        from scripts import configurable_smoke

        payload = json.loads(configurable_smoke.FIXTURE_PATH.read_bytes())
        payload[0]["original"][0][1] = "A different fixture must not receive canned answers."
        changed_path = self.directory / "changed-fixture.json"
        changed_path.write_text(json.dumps(payload), encoding="utf-8")
        with patch.object(configurable_smoke, "FIXTURE_PATH", changed_path):
            with self.assertRaisesRegex(ExecutionError, "abcd_fixture_source_changed"):
                run_smoke(self.directory)
        self.assertFalse((self.directory / DATABASE_NAME).exists())

    def test_partial_frozen_sequence_continues(self):
        plans = fixture_plans()
        model = ScriptedFixtureModel()
        execution = Execution(SQLiteStore(self.directory / DATABASE_NAME), model)
        execution.create(FINANCIAL_JOB, plans[FINANCIAL_JOB], f"{FINANCIAL_JOB}:create")
        execution.advance(FINANCIAL_JOB, 0, f"{FINANCIAL_JOB}:advance:1")
        failed = execution.advance(FINANCIAL_JOB, 1, f"{FINANCIAL_JOB}:timeout:2")
        self.assertEqual(failed.status, Status.FAILED)
        summary = run_smoke(self.directory)
        self.assertEqual(summary["synthetic_model_calls"], 3)
        self.assertEqual(summary["domains"]["financial"]["revisions"], [3])
        reopened = Execution(SQLiteStore(self.directory / DATABASE_NAME),
                             ScriptedFixtureModel(forbid_calls=True))
        self.assertEqual(
            reopened.advance(FINANCIAL_JOB, 1, f"{FINANCIAL_JOB}:timeout:2", action=Action.ADVANCE),
            failed,
        )

    def test_cli_entrypoint_safe_summary_and_explicit_error(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--state-dir", str(self.directory)])
        self.assertEqual(code, 0)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["synthetic_model_calls"], 5)
        self.assertNotIn("desk lamp", output.getvalue())
        self.assertNotIn("customer_issue_or_request", output.getvalue())
        bad_path = self.directory / "not-a-directory"
        bad_path.write_text("owned test sentinel", encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--state-dir", str(bad_path)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["error"], "fixture_source_or_storage_unavailable")
        self.assertEqual(bad_path.read_text(encoding="utf-8"), "owned test sentinel")

    def test_python_module_cli(self):
        result = subprocess.run(
            [sys.executable, "-m", "scripts.configurable_smoke", "--state-dir", str(self.directory)],
            check=False, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["real_model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
