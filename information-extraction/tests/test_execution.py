from pathlib import Path
from dataclasses import FrozenInstanceError, replace
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing
import json
import shutil
import sqlite3
import subprocess
import sys
from threading import Barrier, Event
import unittest
import uuid

from information_extraction import (
    Action,
    Block,
    Blocked,
    Chunk,
    Conflict,
    Execution,
    FailureCode,
    IntegrityError,
    InvalidInput,
    ModelFailure,
    ModelResponse,
    ReviewStatus,
    SQLiteStore,
    Status,
    StaleRevision,
    TokenUsage,
)
from information_extraction.sample import synthetic_plan


class SyntheticModel:
    binding = "synthetic-model-v1"

    def __init__(self):
        self.calls = []

    def complete(self, request):
        self.calls.append(request)
        metric, value = (
            ("revenue", 120) if request.chunk.id == "chunk-1"
            else ("operating_income", 18)
        )
        return ModelResponse(
            {"records": [{
                "metric": metric,
                "value": value,
                "unit": "USD_millions",
                "block_ids": [request.chunk.blocks[0].id],
                "quote": "Untrusted model quote, never use as evidence.",
            }]},
            TokenUsage(10, 5),
        )


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(".test-data") / uuid.uuid4().hex
        self.directory.mkdir(parents=True)
        self.database = self.directory / "ledger.sqlite3"
        self.model = SyntheticModel()
        self.execution = Execution(SQLiteStore(self.database), self.model)

    def tearDown(self):
        shutil.rmtree(self.directory)
        try:
            self.directory.parent.rmdir()
        except OSError:
            pass

    def test_two_chunks_commit_once_with_original_evidence_and_pending_review(self):
        initial = self.execution.create("job-1", synthetic_plan(), "start-1")
        self.assertEqual((initial.revision, initial.status), (0, Status.READY))
        self.assertEqual(self.execution.read("job-1"), initial)
        self.assertEqual(len(self.model.calls), 0)

        first = self.execution.advance("job-1", 0, "advance-1")
        self.assertEqual((first.revision, first.status), (1, Status.READY))
        self.assertEqual(first.completed_chunk_ids, ("chunk-1",))
        finished = self.execution.advance("job-1", 1, "advance-2")

        self.assertEqual((finished.revision, finished.status), (2, Status.COMPLETED))
        self.assertEqual(finished.completed_chunk_ids, ("chunk-1", "chunk-2"))
        self.assertEqual(len(finished.attempts), 2)
        self.assertEqual(len(finished.candidates), 2)
        self.assertEqual(len(self.model.calls), 2)
        self.assertEqual(
            [attempt.covered_block_ids for attempt in finished.attempts],
            [("block-1", "block-2"), ("block-3", "block-4")],
        )
        self.assertEqual(
            [attempt.usage for attempt in finished.attempts],
            [TokenUsage(10, 5), TokenUsage(10, 5)],
        )
        candidate = finished.candidates[0]
        self.assertEqual(candidate.record.value, 120)
        self.assertEqual(candidate.review_status, ReviewStatus.PENDING)
        self.assertFalse(candidate.semantic_validation_performed)
        self.assertEqual(candidate.evidence[0].text, "ExampleCo revenue was USD 120 million.")
        self.assertEqual(candidate.evidence[0].location, "synthetic:line:1")
        self.assertEqual(candidate.job_id, "job-1")
        self.assertEqual(candidate.revision, 1)
        self.assertEqual(candidate.plan_fingerprint, initial.plan_fingerprint)
        self.assertEqual(self.execution.read("job-1"), finished)
        self.assertEqual(len(self.model.calls), 2)

    def test_handled_failure_requires_explicit_resume_preserves_progress_and_replays(self):
        initial = self.execution.create("job-1", synthetic_plan(), "start-1")
        first = self.execution.advance("job-1", 0, "advance-1")
        complete = self.model.complete

        def fail(request):
            self.model.calls.append(request)
            raise ModelFailure(FailureCode.MODEL_TIMEOUT, TokenUsage(12, 0))

        self.model.complete = fail
        failed = self.execution.advance("job-1", 1, "failure-1")
        self.assertEqual((failed.revision, failed.status), (2, Status.FAILED))
        self.assertEqual(failed.completed_chunk_ids, ("chunk-1",))
        self.assertEqual(failed.candidates, first.candidates)
        self.assertEqual(failed.attempts[-1].failure_code, FailureCode.MODEL_TIMEOUT)
        self.assertEqual(failed.attempts[-1].usage, TokenUsage(12, 0))
        self.assertEqual(failed.attempts[-1].covered_block_ids, ())
        self.assertEqual(self.execution.advance("job-1", 1, "failure-1"), failed)
        with self.assertRaises(Conflict):
            self.execution.advance("job-1", 2, "not-a-resume")
        self.assertEqual(len(self.model.calls), 2)
        self.model.complete = complete
        finished = self.execution.advance("job-1", 2, "resume-1", action=Action.RESUME)
        self.assertEqual((finished.revision, finished.status), (3, Status.COMPLETED))
        self.assertEqual(len(finished.candidates), 2)
        self.assertEqual(len(finished.attempts), 3)
        self.assertEqual(finished.candidates[0], first.candidates[0])
        self.execution = Execution(SQLiteStore(self.database), self.model)
        self.assertEqual(self.execution.advance("job-1", 1, "failure-1"), failed)
        self.assertEqual(self.execution.advance("job-1", 0, "advance-1"), first)
        self.assertEqual(self.execution.create("job-1", synthetic_plan(), "start-1"), initial)
        self.assertEqual(self.execution.create("job-1", synthetic_plan(), "start-2"), finished)
        self.assertEqual(
            self.execution.advance("job-1", 2, "resume-1", action=Action.RESUME), finished
        )
        self.assertEqual(len(self.model.calls), 3)

    def test_malformed_outputs_commit_safe_failure_with_known_usage(self):
        valid = {
            "metric": "revenue", "value": 120, "unit": "USD_millions",
            "block_ids": ["block-1"],
        }
        cases = (
            (None, FailureCode.MALFORMED_OUTPUT),
            ("secret=not-json", FailureCode.MALFORMED_OUTPUT),
            ({}, FailureCode.MALFORMED_OUTPUT),
            ({"records": {}}, FailureCode.MALFORMED_OUTPUT),
            ({"records": [None]}, FailureCode.MALFORMED_OUTPUT),
            ({"records": [{**valid, "extra": "secret"}]}, FailureCode.MALFORMED_OUTPUT),
            ({"records": [{**valid, "metric": "unknown"}]}, FailureCode.MALFORMED_OUTPUT),
            ({"records": [{**valid, "value": True}]}, FailureCode.MALFORMED_OUTPUT),
            ({"records": [{**valid, "value": float("nan")}]}, FailureCode.MALFORMED_OUTPUT),
            ({"records": [{**valid, "value": float("inf")}]}, FailureCode.MALFORMED_OUTPUT),
            ({"records": [{**valid, "unit": "EUR"}]}, FailureCode.MALFORMED_OUTPUT),
            ({"records": [{**valid, "block_ids": ["block-3"]}]}, FailureCode.INVALID_EVIDENCE),
            ({"records": [{**valid, "block_ids": []}]}, FailureCode.INVALID_EVIDENCE),
            ({"records": [{**valid, "block_ids": [""]}]}, FailureCode.INVALID_EVIDENCE),
            ({"records": [{**valid, "block_ids": [True]}]}, FailureCode.INVALID_EVIDENCE),
            ({"records": [{**valid, "block_ids": ["block-1", "block-1"]}]},
             FailureCode.INVALID_EVIDENCE),
            ({"records": [{**valid, "block_ids": [["block-1"]]}]}, FailureCode.INVALID_EVIDENCE),
        )
        for index, (payload, code) in enumerate(cases):
            with self.subTest(index=index):
                job_id = f"invalid-{index}"
                self.execution.create(job_id, synthetic_plan(), f"create-invalid-{index}")
                self.model.complete = lambda request: ModelResponse(payload, TokenUsage(10, 5))
                failed = self.execution.advance(job_id, 0, f"invalid-output-{index}")
                self.assertEqual((failed.revision, failed.status), (1, Status.FAILED))
                self.assertEqual(failed.attempts[-1].failure_code, code)
                self.assertEqual(failed.attempts[-1].usage, TokenUsage(10, 5))
                self.assertEqual(failed.candidates, ())
                self.assertEqual(failed.completed_chunk_ids, ())
                self.assertNotIn("secret", repr(failed))

    def test_invalid_inputs_reject_before_persistence_or_inference(self):
        plan = synthetic_plan()
        invalid = (
            lambda: Block("", "text", "location"),
            lambda: Block("block", " \n", "location"),
            lambda: Block("block", "text", ""),
            lambda: Block(True, "text", "location"),
            lambda: Chunk("chunk", ()),
            lambda: Chunk("chunk", [plan.chunks[0].blocks[0]]),
            lambda: Chunk("chunk", (plan.chunks[0].blocks[0],) * 2),
            lambda: replace(plan, document_id=""),
            lambda: replace(plan, chunks=()),
            lambda: replace(plan, chunks=list(plan.chunks)),
            lambda: replace(plan, chunks=(plan.chunks[0],) * 2),
            lambda: replace(plan, chunks=(plan.chunks[0], replace(plan.chunks[0], id="other"))),
            lambda: replace(plan, profile_version=""),
            lambda: replace(plan, schema_version="unsupported"),
            lambda: replace(plan, parser_version=""),
            lambda: replace(plan, model_binding=" "),
            lambda: self.execution.create("", plan, "start"),
            lambda: self.execution.create("job", plan, ""),
            lambda: self.execution.create("job", None, "start"),
            lambda: self.execution.read(" "),
            lambda: self.execution.advance("job", True, "attempt"),
            lambda: self.execution.advance("job", -1, "attempt"),
            lambda: self.execution.advance("job", 0.0, "attempt"),
            lambda: self.execution.advance("job", 0, ""),
            lambda: self.execution.advance("job", 0, "attempt", action="resume"),
        )
        for index, operation in enumerate(invalid):
            with self.subTest(index=index):
                with self.assertRaises(InvalidInput):
                    operation()
        with self.assertRaises(FrozenInstanceError):
            plan.chunks[0].blocks[0].text = "changed"
        self.assertEqual(len(self.model.calls), 0)

    def test_identity_conflicts_stale_revisions_and_binding_mismatch_do_not_call_model(self):
        plan = synthetic_plan()
        initial = self.execution.create("job", plan, "create")
        changed_plans = (
            replace(plan, document_id="different-document"),
            replace(plan, profile_version="different-profile"),
            replace(plan, parser_version="different-parser"),
            replace(plan, model_binding="different-model"),
            replace(plan, chunks=(replace(plan.chunks[0], blocks=(
                replace(plan.chunks[0].blocks[0], text="Changed original source."),
                plan.chunks[0].blocks[1],
            )), plan.chunks[1])),
        )
        for index, changed in enumerate(changed_plans):
            with self.subTest(index=index):
                with self.assertRaises(Conflict):
                    self.execution.create("job", changed, f"changed-{index}")
                with self.assertRaises(Conflict):
                    self.execution.create("job", changed, "create")
        with self.assertRaises(Conflict):
            self.execution.create("other-job", plan, "create")
        self.model.binding = "different-model"
        with self.assertRaises(Conflict):
            self.execution.advance("job", 0, "binding-mismatch")
        self.assertEqual(self.execution.read("job"), initial)
        self.model.binding = plan.model_binding
        with self.assertRaises(StaleRevision):
            self.execution.advance("job", 1, "future")
        with self.assertRaises(Conflict):
            self.execution.advance("job", 0, "resume-ready", action=Action.RESUME)
        first = self.execution.advance("job", 0, "advance")
        with self.assertRaises(StaleRevision):
            self.execution.advance("job", 0, "stale")
        with self.assertRaises(Conflict):
            self.execution.advance("job", 1, "advance")
        with self.assertRaises(Conflict):
            self.execution.advance("job", 0, "advance", action=Action.RESUME)
        with self.assertRaises(Conflict):
            self.execution.advance("job", 1, "create")
        self.assertEqual(self.execution.read("job"), first)
        self.assertEqual(len(self.model.calls), 1)

    def test_token_usage_keeps_unknown_distinct_from_zero_and_rejects_sdk_shapes(self):
        cases = (
            (None, None, None),
            (TokenUsage(0, 0), TokenUsage(0, 0), None),
            (TokenUsage(True, 1), None, FailureCode.INVALID_USAGE),
            (TokenUsage(1, False), None, FailureCode.INVALID_USAGE),
            (TokenUsage(-1, 1), None, FailureCode.INVALID_USAGE),
            (TokenUsage(1, 1.5), None, FailureCode.INVALID_USAGE),
            ({"input_tokens": 10, "output_tokens": 5}, None, FailureCode.INVALID_USAGE),
        )
        for index, (usage, expected, code) in enumerate(cases):
            with self.subTest(index=index):
                job_id = f"usage-{index}"
                self.execution.create(job_id, synthetic_plan(), f"create-usage-{index}")
                self.model.complete = lambda request: ModelResponse({"records": []}, usage)
                result = self.execution.advance(job_id, 0, f"usage-request-{index}")
                self.assertEqual(result.attempts[-1].usage, expected)
                self.assertEqual(result.attempts[-1].failure_code, code)
                self.assertEqual(result.status, Status.FAILED if code else Status.READY)

    def test_invalid_provider_usage_is_handled_without_persisting_raw_values(self):
        self.execution.create("job", synthetic_plan(), "create")

        def malformed_usage(request):
            raise ModelFailure(FailureCode.MODEL_REJECTED, {"secret": "private-value"})

        self.model.complete = malformed_usage
        result = self.execution.advance("job", 0, "malformed-usage")
        self.assertEqual(result.attempts[-1].failure_code, FailureCode.INVALID_USAGE)
        self.assertIsNone(result.attempts[-1].usage)
        self.assertNotIn("private-value", repr(result))

    def test_zero_candidates_still_commits_chunk_coverage_without_claiming_review(self):
        self.execution.create("job", synthetic_plan(), "create")
        self.model.complete = lambda request: ModelResponse({"records": []})
        first = self.execution.advance("job", 0, "advance-1")
        final = self.execution.advance("job", 1, "advance-2")
        self.assertEqual(first.completed_chunk_ids, ("chunk-1",))
        self.assertEqual(final.status, Status.COMPLETED)
        self.assertEqual(final.candidates, ())
        self.assertEqual(
            [attempt.covered_block_ids for attempt in final.attempts],
            [("block-1", "block-2"), ("block-3", "block-4")],
        )
        with self.assertRaises(Conflict):
            self.execution.advance("job", 2, "after-completion")

    def test_malformed_response_envelope_and_later_record_do_not_publish_partial_candidates(self):
        valid = {
            "metric": "revenue", "value": 120, "unit": "USD_millions",
            "block_ids": ["block-1"],
        }
        for index, response in enumerate((
            None,
            {"records": [valid]},
            ModelResponse({"records": [valid, {**valid, "block_ids": ["block-3"]}]}, TokenUsage(3, 4)),
        )):
            with self.subTest(index=index):
                job_id = f"envelope-{index}"
                self.execution.create(job_id, synthetic_plan(), f"create-envelope-{index}")
                self.model.complete = lambda request: response
                failed = self.execution.advance(job_id, 0, f"envelope-request-{index}")
                self.assertEqual(failed.status, Status.FAILED)
                self.assertEqual(failed.candidates, ())
                self.assertEqual(failed.completed_chunk_ids, ())
                self.assertEqual(
                    failed.attempts[-1].failure_code,
                    FailureCode.INVALID_EVIDENCE if index == 2 else FailureCode.MALFORMED_OUTPUT,
                )

    def test_storage_requires_a_persistent_path(self):
        for path in ("", ":memory:"):
            with self.subTest(path=path):
                with self.assertRaises(InvalidInput):
                    SQLiteStore(path)

    def test_corrupted_plan_or_checkpoint_blocks_read_and_new_inference(self):
        for index, target in enumerate(("plan", "checkpoint")):
            with self.subTest(target=target):
                job_id = f"corrupted-{index}"
                self.execution.create(job_id, synthetic_plan(), f"create-corrupted-{index}")
                with closing(sqlite3.connect(self.database)) as connection, connection:
                    if target == "plan":
                        connection.execute(
                            "UPDATE jobs SET plan = '{}' WHERE job_id = ?", (job_id,),
                        )
                    else:
                        connection.execute(
                            "UPDATE checkpoints SET payload = '{}' WHERE job_id = ?", (job_id,),
                        )
                restored = Execution(SQLiteStore(self.database), self.model)
                with self.assertRaises(IntegrityError):
                    restored.read(job_id)
                with self.assertRaises(IntegrityError):
                    restored.advance(job_id, 0, f"advance-corrupted-{index}")
        self.assertEqual(len(self.model.calls), 0)

    def test_handled_provider_failure_does_not_assume_unknown_usage_is_zero(self):
        self.execution.create("job", synthetic_plan(), "create")

        def timeout(request):
            raise ModelFailure(FailureCode.MODEL_TIMEOUT)

        self.model.complete = timeout
        result = self.execution.advance("job", 0, "timeout")
        self.assertIsNone(result.attempts[-1].usage)
        self.assertEqual(result.attempts[-1].failure_code, FailureCode.MODEL_TIMEOUT)

    def test_reopened_adapter_and_new_process_continue_only_remaining_chunk(self):
        self.execution.create("job", synthetic_plan(), "create")
        first = self.execution.advance("job", 0, "advance-1")
        restored_model = SyntheticModel()
        restored = Execution(SQLiteStore(self.database), restored_model)
        self.assertEqual(restored.read("job"), first)
        self.assertEqual(restored.advance("job", 0, "advance-1"), first)
        self.assertEqual(len(restored_model.calls), 0)
        child = subprocess.run(
            [sys.executable, "-c", """
import json
import sys
from information_extraction import Execution, SQLiteStore
from tests.test_execution import SyntheticModel
model = SyntheticModel()
execution = Execution(SQLiteStore(sys.argv[1]), model)
before = execution.read("job")
result = execution.advance("job", 1, "advance-2")
print(json.dumps({
    "before": before.revision, "revision": result.revision,
    "attempts": len(result.attempts), "chunks": [r.chunk.id for r in model.calls],
}))
""", str(self.database)],
            check=True, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(json.loads(child.stdout), {
            "before": 1, "revision": 2, "attempts": 2, "chunks": ["chunk-2"],
        })
        finished = restored.read("job")
        self.assertEqual(finished.status, Status.COMPLETED)
        self.assertEqual(finished.candidates[0], first.candidates[0])
        self.assertEqual(restored.advance("job", 0, "advance-1"), first)
        self.assertEqual(restored.advance("job", 1, "advance-2"), finished)
        self.assertEqual(len(self.model.calls), 1)
        self.assertEqual(len(restored_model.calls), 0)

    def test_two_workers_own_one_revision_without_holding_lock_during_inference(self):
        self.execution.create("job", synthetic_plan(), "create")
        entered, release = Event(), Event()
        start = Barrier(2)
        complete = self.model.complete

        def slow(request):
            response = complete(request)
            entered.set()
            if not release.wait(10):
                raise RuntimeError("test_model_wait_expired")
            return response

        self.model.complete = slow
        workers = [
            Execution(SQLiteStore(self.database), self.model),
            Execution(SQLiteStore(self.database), self.model),
        ]

        def advance(index):
            start.wait(timeout=10)
            return workers[index].advance("job", 0, f"worker-{index}")

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(advance, index) for index in range(2)]
            try:
                self.assertTrue(entered.wait(10))
                done, _ = wait(futures, timeout=3, return_when=FIRST_COMPLETED)
                self.assertEqual(len(done), 1, "loser must not wait for the model's DB lock")
                loser = next(iter(done))
                with self.assertRaises(Blocked):
                    loser.result()
                claimed = self.execution.read("job")
                self.assertEqual((claimed.revision, claimed.status), (0, Status.IN_PROGRESS))
                self.assertEqual(claimed.attempts, ())
                self.assertIsNotNone(claimed.claim)
                self.assertEqual(len(self.model.calls), 1)
                with self.assertRaises(Blocked):
                    self.execution.advance("job", 0, claimed.claim.request_id)
                duplicate_create = self.execution.create("job", synthetic_plan(), "create-active")
                self.assertEqual(duplicate_create, claimed)
            finally:
                release.set()
            winner = next(future for future in futures if future is not loser)
            result = winner.result(timeout=10)
        self.assertEqual(result.revision, 1)
        self.assertEqual(len(result.attempts), 1)
        self.assertEqual(len(self.model.calls), 1)

    def test_unknown_exception_or_cancellation_propagates_and_retains_claim(self):
        for index, error in enumerate((RuntimeError("private-detail"), KeyboardInterrupt())):
            with self.subTest(index=index):
                job_id = f"interrupted-{index}"
                self.execution.create(job_id, synthetic_plan(), f"create-{index}")

                def interrupt(request):
                    self.model.calls.append(request)
                    raise error

                self.model.complete = interrupt
                with self.assertRaises(type(error)):
                    self.execution.advance(job_id, 0, f"interrupt-{index}")
                restored = Execution(SQLiteStore(self.database), self.model)
                state = restored.read(job_id)
                self.assertEqual((state.revision, state.status), (0, Status.IN_PROGRESS))
                self.assertEqual(state.claim.request_id, f"interrupt-{index}")
                self.assertEqual(state.attempts, ())
                self.assertEqual(state.candidates, ())
                self.assertNotIn("private-detail", repr(state))
                for request_id, action in (
                    (f"interrupt-{index}", Action.ADVANCE),
                    (f"retry-{index}", Action.ADVANCE),
                    (f"resume-{index}", Action.RESUME),
                ):
                    with self.assertRaises(Blocked):
                        restored.advance(job_id, 0, request_id, action=action)
        self.assertEqual(len(self.model.calls), 2)

    def test_process_exit_inside_model_leaves_durable_blocking_claim(self):
        self.execution.create("job", synthetic_plan(), "create")
        child = subprocess.run(
            [sys.executable, "-c", """
import os
import sys
from information_extraction import Execution, SQLiteStore
class InterruptedModel:
    binding = "synthetic-model-v1"
    def complete(self, request):
        os._exit(23)
Execution(SQLiteStore(sys.argv[1]), InterruptedModel()).advance("job", 0, "killed")
""", str(self.database)],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(child.returncode, 23, child.stderr)
        state = self.execution.read("job")
        self.assertEqual((state.revision, state.status), (0, Status.IN_PROGRESS))
        self.assertEqual(state.claim.request_id, "killed")
        self.assertEqual(state.attempts, ())
        with self.assertRaises(Blocked):
            self.execution.advance("job", 0, "killed")
        with self.assertRaises(Blocked):
            self.execution.advance("job", 0, "resume", action=Action.RESUME)
        self.assertEqual(len(self.model.calls), 0)

    def test_sqlite_publication_lock_failure_rolls_back_result_but_retains_claim(self):
        execution = Execution(SQLiteStore(self.database, timeout=0.05), self.model)
        execution.create("job", synthetic_plan(), "create")
        complete = self.model.complete
        reader = sqlite3.connect(self.database)

        def hold_database_read_lock(request):
            response = complete(request)
            reader.execute("BEGIN")
            reader.execute("SELECT name FROM sqlite_master").fetchall()
            return response

        self.model.complete = hold_database_read_lock
        try:
            with self.assertRaises(sqlite3.OperationalError):
                execution.advance("job", 0, "publication-fails")
        finally:
            reader.rollback()
            reader.close()
        state = Execution(SQLiteStore(self.database), self.model).read("job")
        self.assertEqual((state.revision, state.status), (0, Status.IN_PROGRESS))
        self.assertEqual(state.claim.request_id, "publication-fails")
        self.assertEqual(state.attempts, ())
        self.assertEqual(state.candidates, ())
        with self.assertRaises(Blocked):
            execution.advance("job", 0, "publication-fails")
        with self.assertRaises(Blocked):
            execution.advance("job", 0, "try-again", action=Action.RESUME)
        self.assertEqual(len(self.model.calls), 1)


if __name__ == "__main__":
    unittest.main()
