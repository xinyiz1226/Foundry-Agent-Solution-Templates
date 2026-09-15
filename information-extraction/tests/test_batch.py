import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
import json
import shutil
import unittest
import uuid
from threading import Barrier, Event

from information_extraction import (
    Conflict, Execution, ExecutionError, FailureCode, IntegrityError, InvalidInput, ModelFailure,
    SQLiteStore, Status,
)
from information_extraction.batch import Batch, BatchLimits, BatchState, RegistrationUnknown
from information_extraction.codec import _hash, _json
from information_extraction.sample import synthetic_plan
from tests.test_execution import SyntheticModel


class QueueScheduler:
    """External scheduler seam; delivery is independent of the caller."""

    def __init__(self):
        self.deliveries = []

    async def schedule(self, run_id):
        self.deliveries.append(run_id)


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(".test-data") / uuid.uuid4().hex
        self.directory.mkdir(parents=True)
        self.database = self.directory / "batch.sqlite3"
        self.make_store = lambda: SQLiteStore(self.database)
        self.model = SyntheticModel()
        self.scheduler = QueueScheduler()
        self.now = 1000.0
        self.execution = Execution(self.make_store(), self.model)
        self.execution.create("job", synthetic_plan(), "create")
        self.batch = self.restore()
        self.limits = BatchLimits(max_attempts=5, deadline=1060.0)

    def restore(self):
        return Batch(
            Execution(self.make_store(), self.model), self.make_store(),
            self.scheduler, clock=lambda: self.now,
        )

    def tearDown(self):
        shutil.rmtree(self.directory)

    def start(self, request="start", limits=None):
        return asyncio.run(self.batch.start("job", 0, request, limits or self.limits))

    def test_current_discovers_only_owned_rounds_and_follows_resume_after_restore(self):
        self.assertIsNone(self.restore().current("absent"))
        self.assertIsNone(self.restore().current("job"))
        first = self.start(limits=BatchLimits(max_attempts=1, deadline=1060))
        self.assertEqual(self.restore().current("job"), self.batch.status(first.run_id))
        self.batch.run(first.run_id)
        second = asyncio.run(self.batch.resume(first.run_id, 1, "resume", self.limits))
        deliveries = list(self.scheduler.deliveries)
        for _ in range(3):
            self.assertEqual(self.restore().current("job"), self.batch.status(second.run_id))
        self.assertEqual(self.scheduler.deliveries, deliveries)
        self.assertEqual(len(self.model.calls), 1)

    def test_current_rejects_corrupt_foreign_missing_and_cyclic_owned_references(self):
        run = self.start()
        root = _hash(_json(["root", "job"]))
        authorization = _hash(_json(["authorization", run.run_id]))
        successor = _hash(_json(["next", run.run_id]))
        cases = [
            {root: "null"},
            {root: "not-json"},
            {root: "[]"},
            {root: _json({"run_id": "missing"})},
            {root: _json({"run_id": run.run_id, "extra": True})},
            {authorization: _json({**asdict(run), "job_id": "foreign"})},
            {authorization: _json({**asdict(run), "run_id": "different"})},
            {authorization: _json({**asdict(run), "previous_run_id": "wrong"})},
            {authorization: _json({**asdict(run), "limits": {}})},
            {successor: _json({"run_id": "missing"})},
            {successor: _json({"run_id": run.run_id})},
        ]
        store = self.make_store()
        for overrides in cases:
            class DamagedRecords:
                def read_batch_record(self, key):
                    return overrides.get(key, store.read_batch_record(key))

                def create_batch_record(self, key, payload):
                    raise AssertionError("discovery_must_not_write")

            batch = Batch(self.execution, DamagedRecords(), self.scheduler, clock=lambda: self.now)
            with self.assertRaises(IntegrityError):
                batch.current("job")
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.scheduler.deliveries, [run.run_id])

    def test_current_has_an_explicit_traversal_limit_instead_of_returning_an_old_tip(self):
        snapshot = asdict(self.execution.read("job"))
        records = {}
        previous = None
        for index in range(1025):
            request_id = f"round-{index}"
            run_id = _hash(_json(["run", request_id]))
            records[_hash(_json(["authorization", run_id]))] = _json({
                "run_id": run_id, "job_id": "job", "request_id": request_id,
                "plan_fingerprint": snapshot["plan_fingerprint"], "expected_revision": 0,
                "limits": {"max_attempts": 1, "deadline": 1060}, "previous_run_id": previous,
            })
            owner = ["root", "job"] if previous is None else ["next", previous]
            records[_hash(_json(owner))] = _json({"run_id": run_id})
            records[_hash(_json(["step", run_id, 0]))] = _json({
                "kind": "terminal", "state": "limited", "snapshot": snapshot,
            })
            previous = run_id

        class ReadOnlyRecords:
            def read_batch_record(self, key):
                return records.get(key)

            def create_batch_record(self, key, payload):
                raise AssertionError("discovery_must_not_write")

        batch = Batch(self.execution, ReadOnlyRecords(), self.scheduler, clock=lambda: self.now)
        with self.assertRaisesRegex(IntegrityError, "batch_chain_traversal_limit"):
            batch.current("job")
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.scheduler.deliveries, [])

    def test_start_freezes_authorization_before_scheduling_and_replays_without_model(self):
        run = self.start()
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.scheduler.deliveries, [run.run_id])
        self.assertEqual(run.expected_revision, 0)
        self.assertEqual(run.plan_fingerprint, self.execution.read("job").plan_fingerprint)
        self.now = 1010.0
        self.batch = self.restore()
        self.assertEqual(self.start(), run)
        status = self.batch.status(run.run_id)
        self.assertEqual(status.authorization, run)
        self.assertEqual(status.state, BatchState.QUEUED)
        self.assertEqual(status.authorization.limits.deadline, 1060.0)
        self.assertEqual(self.model.calls, [])

    def test_one_start_runs_two_chunks_in_backend_while_status_is_read_only(self):
        entered, release = Event(), Event()
        complete = self.model.complete

        def slow(request):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("synthetic_worker_wait")
            return complete(request)

        self.model.complete = slow
        run = self.start()
        self.assertFalse(entered.is_set())
        with ThreadPoolExecutor() as workers:
            work = workers.submit(self.batch.run, self.scheduler.deliveries[0])
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(self.batch.status(run.run_id).state, BatchState.BLOCKED)
                self.assertEqual(self.start(), run)
                self.assertEqual(self.model.calls, [])
            finally:
                release.set()
            work.result(timeout=5)
        finished = self.restore().status(run.run_id)
        self.assertEqual(finished.state, BatchState.COMPLETED)
        self.assertEqual(finished.attempts_reserved, 2)
        self.assertEqual(finished.snapshot.completed_chunk_ids, ("chunk-1", "chunk-2"))
        self.assertEqual(len(finished.snapshot.candidates), 2)
        self.assertEqual(len(self.model.calls), 2)
        self.restore().run(run.run_id)
        self.assertEqual(self.start(), run)
        self.assertEqual(len(self.model.calls), 2)

    def test_limit_resume_opens_one_new_round_and_old_delivery_only_replays(self):
        run = self.start(limits=BatchLimits(max_attempts=1, deadline=1060.0))
        self.batch.run(run.run_id)
        limited = self.batch.status(run.run_id)
        self.assertEqual(limited.state, BatchState.LIMITED)
        self.assertEqual(limited.attempts_reserved, 1)
        resumed = asyncio.run(self.restore().resume(
            run.run_id, 1, "resume", self.limits,
        ))
        self.restore().run(run.run_id)
        self.assertEqual(len(self.model.calls), 1)
        self.restore().run(resumed.run_id)
        completed = self.batch.status(resumed.run_id)
        self.assertEqual(completed.state, BatchState.COMPLETED)
        self.assertEqual(completed.snapshot.candidates[0], limited.snapshot.candidates[0])
        self.assertEqual(self.batch.status(run.run_id), limited)
        self.assertEqual(asyncio.run(self.batch.resume(run.run_id, 1, "resume", self.limits)), resumed)
        with self.assertRaises(Conflict):
            asyncio.run(self.batch.resume(run.run_id, 1, "other-resume", self.limits))
        self.assertEqual(len(self.model.calls), 2)

    def test_absolute_deadline_stops_between_chunks_and_does_not_reset_on_redelivery(self):
        complete = self.model.complete

        def elapsed(request):
            response = complete(request)
            self.now = 1061.0
            return response

        self.model.complete = elapsed
        run = self.start()
        self.batch.run(run.run_id)
        for _ in range(3):
            self.restore().run(run.run_id)
            self.assertEqual(self.start(), run)
        status = self.batch.status(run.run_id)
        self.assertEqual(status.state, BatchState.LIMITED)
        self.assertEqual(status.attempts_reserved, 1)
        self.assertEqual(len(self.model.calls), 1)

    def test_default_five_attempt_cap_survives_commit_response_loss_and_worker_replacement(self):
        plan = synthetic_plan()
        chunks = tuple(
            replace(
                plan.chunks[0], id=f"chunk-{index}",
                blocks=(replace(plan.chunks[0].blocks[0], id=f"block-{index}"),),
            )
            for index in range(7)
        )
        self.execution.create("long-job", replace(plan, chunks=chunks), "create-long")
        run = asyncio.run(self.batch.start("long-job", 0, "long-start", self.limits))
        store = self.make_store()

        class LostPublicationResponse:
            read = store.read
            create = store.create
            claim = store.claim

            def publish(self, claimed, result):
                store.publish(claimed, result)
                raise SystemExit("synthetic_lost_commit_response")

        worker = Batch(
            Execution(LostPublicationResponse(), self.model), store,
            self.scheduler, clock=lambda: self.now,
        )
        with self.assertRaises(SystemExit):
            worker.run(run.run_id)
        self.assertEqual(len(self.model.calls), 1)
        for _ in range(3):
            self.restore().run(run.run_id)
        status = self.batch.status(run.run_id)
        self.assertEqual(status.state, BatchState.LIMITED)
        self.assertEqual(status.attempts_reserved, 5)
        self.assertEqual(status.snapshot.revision, 5)
        self.assertEqual(len(self.model.calls), 5)

    def test_unknown_model_interruption_never_retries_or_authorizes_resume(self):
        def interrupt(request):
            self.model.calls.append(request)
            raise SystemExit("synthetic_unknown_model_outcome")

        self.model.complete = interrupt
        run = self.start()
        with self.assertRaises(SystemExit):
            self.batch.run(run.run_id)
        self.restore().run(run.run_id)
        self.assertEqual(self.start(), run)
        status = self.batch.status(run.run_id)
        self.assertEqual(status.state, BatchState.BLOCKED)
        self.assertEqual(status.snapshot.status, Status.IN_PROGRESS)
        self.assertEqual(status.unknown_usage_attempts, 1)
        self.assertEqual(status.known_input_tokens, 0)
        with self.assertRaises(Conflict):
            asyncio.run(self.batch.resume(run.run_id, 0, "unsafe-resume", self.limits))
        self.assertEqual(len(self.model.calls), 1)

    def test_concurrent_start_and_resume_operators_share_only_one_authorization(self):
        barrier = Barrier(2)
        limits = BatchLimits(max_attempts=1, deadline=1060.0)

        def start(request):
            barrier.wait(timeout=5)
            try:
                return asyncio.run(self.restore().start("job", 0, request, limits))
            except Conflict:
                return None

        with ThreadPoolExecutor() as workers:
            results = list(workers.map(start, ("operator-a", "operator-b")))
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        run = winners[0]
        with ThreadPoolExecutor() as workers:
            list(workers.map(lambda _: self.restore().run(run.run_id), range(2)))
        self.assertEqual(len(self.model.calls), 1)
        self.assertEqual(self.batch.status(run.run_id).state, BatchState.LIMITED)
        barrier = Barrier(2)

        def resume(request):
            barrier.wait(timeout=5)
            try:
                return asyncio.run(self.restore().resume(run.run_id, 1, request, self.limits))
            except Conflict:
                return None

        with ThreadPoolExecutor() as workers:
            results = list(workers.map(resume, ("resume-a", "resume-b")))
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        with ThreadPoolExecutor() as workers:
            list(workers.map(lambda _: self.restore().run(winners[0].run_id), range(2)))
        self.restore().run(run.run_id)
        self.assertEqual(len(self.model.calls), 2)

    def test_conflicting_replays_and_invalid_limits_never_schedule_or_infer(self):
        run = self.start()
        for limits in (BatchLimits(max_attempts=1, deadline=1060), BatchLimits(deadline=1061)):
            with self.assertRaises(Conflict):
                self.start(limits=limits)
        for count in (0, 6, True, 1.5):
            with self.assertRaises(InvalidInput):
                BatchLimits(max_attempts=count, deadline=1060)
        for deadline in (0, -1, True, float("inf"), float("nan")):
            with self.assertRaises(InvalidInput):
                BatchLimits(deadline=deadline)
        with self.assertRaises(InvalidInput):
            asyncio.run(self.batch.start("job", False, "invalid", self.limits))
        self.assertEqual(self.scheduler.deliveries, [run.run_id])
        self.assertEqual(self.model.calls, [])

    def test_failure_stops_and_explicit_resume_preserves_candidates_and_unknown_usage(self):
        complete = self.model.complete

        def fail_second(request):
            if request.chunk.id == "chunk-2":
                self.model.calls.append(request)
                raise ModelFailure(FailureCode.MODEL_TIMEOUT)
            return complete(request)

        self.model.complete = fail_second
        run = self.start()
        self.batch.run(run.run_id)
        failed = self.batch.status(run.run_id)
        self.assertEqual(failed.state, BatchState.FAILED)
        self.assertEqual(failed.attempts_reserved, 2)
        self.assertIsNone(failed.snapshot.attempts[-1].usage)
        self.restore().run(run.run_id)
        self.model.complete = complete
        resumed = asyncio.run(self.batch.resume(run.run_id, 2, "resume", self.limits))
        self.batch.run(resumed.run_id)
        completed = self.batch.status(resumed.run_id)
        self.assertEqual(completed.state, BatchState.COMPLETED)
        self.assertEqual(completed.snapshot.candidates[0], failed.snapshot.candidates[0])
        self.assertEqual(len(self.model.calls), 3)

    def test_old_failed_round_cannot_spend_after_resume_leaves_ready_below_old_cap(self):
        plan = synthetic_plan()
        third = replace(
            plan.chunks[1], id="chunk-3",
            blocks=tuple(replace(block, id=f"third-{block.id}") for block in plan.chunks[1].blocks),
        )
        self.execution.create("three-chunks", replace(plan, chunks=(*plan.chunks, third)), "create-three")
        complete = self.model.complete

        def fail_second(request):
            if request.chunk.id == "chunk-2":
                self.model.calls.append(request)
                raise ModelFailure(FailureCode.MODEL_TIMEOUT)
            return complete(request)

        self.model.complete = fail_second
        old = asyncio.run(self.batch.start("three-chunks", 0, "old-round", self.limits))
        self.batch.run(old.run_id)
        failed = self.batch.status(old.run_id)
        self.assertEqual(failed.state, BatchState.FAILED)
        self.assertEqual(failed.attempts_reserved, 2)

        self.model.complete = complete
        new = asyncio.run(self.restore().resume(
            old.run_id, 2, "new-round", BatchLimits(max_attempts=1, deadline=1060),
        ))
        self.restore().run(new.run_id)
        limited = self.batch.status(new.run_id)
        self.assertEqual(limited.state, BatchState.LIMITED)
        self.assertEqual(limited.snapshot.status, Status.READY)
        self.assertEqual(limited.snapshot.revision, 3)
        self.assertLess(limited.snapshot.revision, old.limits.max_attempts)
        self.assertEqual(limited.snapshot.completed_chunk_ids, ("chunk-1", "chunk-2"))
        self.assertEqual(limited.snapshot.candidates[0], failed.snapshot.candidates[0])

        with ThreadPoolExecutor() as workers:
            list(workers.map(lambda _: self.restore().run(old.run_id), range(2)))
        self.assertEqual(self.batch.status(old.run_id), failed)
        self.assertEqual(self.batch.status(new.run_id), limited)
        self.assertEqual(self.execution.read("three-chunks"), limited.snapshot)
        self.assertEqual(len(self.model.calls), 3)

    def test_lost_registration_response_is_visible_and_retries_same_saved_identity(self):
        original = self.scheduler.schedule

        async def lose_response(run_id):
            await original(run_id)
            raise TimeoutError("secret_sdk_diagnostic")

        self.scheduler.schedule = lose_response
        with self.assertRaisesRegex(RegistrationUnknown, "^batch_registration_unknown$") as failure:
            self.start()
        run_id = failure.exception.authorization.run_id
        self.assertEqual(run_id, self.scheduler.deliveries[0])
        pending = self.restore().status(run_id)
        self.assertFalse(pending.registration_confirmed)
        self.assertEqual(pending.authorization.limits.deadline, 1060.0)
        self.now = 1010.0
        self.scheduler.schedule = original
        run = self.start()
        self.assertEqual(self.scheduler.deliveries, [run_id, run_id])
        self.assertEqual(run, pending.authorization)
        for delivery in self.scheduler.deliveries:
            self.restore().run(delivery)
        self.assertEqual(len(self.model.calls), 2)
        self.assertTrue(self.batch.status(run_id).registration_confirmed)

    def test_expired_admission_after_interruption_is_blocked_not_a_fresh_budget(self):
        records = self.make_store()

        class InterruptedRecords:
            read_batch_record = records.read_batch_record

            def create_batch_record(self, key, payload):
                result = records.create_batch_record(key, payload)
                if json.loads(payload).get("kind") == "attempt":
                    raise SystemExit("synthetic_process_loss")
                return result

        run = self.start()
        worker = Batch(self.execution, InterruptedRecords(), self.scheduler, clock=lambda: self.now)
        with self.assertRaises(SystemExit):
            worker.run(run.run_id)
        self.now = 1061.0
        restored = self.restore()
        restored.run(run.run_id)
        status = restored.status(run.run_id)
        self.assertEqual(status.state, BatchState.BLOCKED)
        self.assertEqual(status.attempts_reserved, 1)
        self.assertEqual(status.authorization.limits.deadline, 1060.0)
        with self.assertRaises(Conflict):
            asyncio.run(restored.resume(run.run_id, 0, "resume", BatchLimits(deadline=1120)))
        self.assertEqual(self.model.calls, [])

    def test_native_cooperative_stop_prevents_next_admission_and_preserves_usage(self):
        complete = self.model.complete
        stop = Event()

        def cancel_after_first(request):
            response = complete(request)
            stop.set()
            return response

        self.model.complete = cancel_after_first
        run = self.start()
        self.batch.run(run.run_id, cancelled=stop.is_set)
        status = self.batch.status(run.run_id)
        self.assertEqual(status.state, BatchState.LIMITED)
        self.assertEqual(status.attempts_reserved, 1)
        self.assertEqual(status.known_input_tokens, 10)
        self.assertEqual(status.known_output_tokens, 5)
        self.assertEqual(status.unknown_usage_attempts, 0)
        self.assertEqual(len(self.model.calls), 1)

    def test_cancellation_after_admission_does_not_abandon_a_registered_round(self):
        checks = iter((False, True, True))
        run = self.start()
        self.batch.run(run.run_id, cancelled=lambda: next(checks))
        status = self.batch.status(run.run_id)
        self.assertEqual(status.state, BatchState.LIMITED)
        self.assertEqual(status.snapshot.revision, 1)
        self.assertEqual(status.attempts_reserved, 1)
        self.assertEqual(len(self.model.calls), 1)

    def test_registration_receipt_write_failure_returns_safe_inspectable_uncertainty(self):
        records = self.make_store()

        class FailedAckWrite:
            read_batch_record = records.read_batch_record

            def create_batch_record(self, key, payload):
                if "confirmed" in json.loads(payload):
                    raise RuntimeError("secret_storage_diagnostic")
                return records.create_batch_record(key, payload)

        batch = Batch(self.execution, FailedAckWrite(), self.scheduler, clock=lambda: self.now)
        with self.assertRaisesRegex(RegistrationUnknown, "^batch_registration_unknown$") as failed:
            asyncio.run(batch.start("job", 0, "start", self.limits))
        run = failed.exception.authorization
        self.assertFalse(self.restore().status(run.run_id).registration_confirmed)
        self.assertEqual(self.start(), run)
        self.restore().run(run.run_id)
        self.assertEqual(len(self.model.calls), 2)

    def test_unknown_worker_exception_is_safe_and_preserves_unresolved_claim(self):
        def unexpected(request):
            raise RuntimeError("secret_model_diagnostic")

        self.model.complete = unexpected
        run = self.start()
        with self.assertRaisesRegex(ExecutionError, "^batch_execution_interrupted$"):
            self.batch.run(run.run_id)
        self.assertEqual(self.restore().status(run.run_id).state, BatchState.BLOCKED)

    def test_status_storage_errors_do_not_expose_sdk_diagnostics(self):
        run = self.start()

        class UnavailableRecords:
            def read_batch_record(self, key):
                raise RuntimeError("secret_storage_diagnostic")

        batch = Batch(self.execution, UnavailableRecords(), self.scheduler, clock=lambda: self.now)
        with self.assertRaisesRegex(ExecutionError, "^batch_storage_unavailable$"):
            batch.status(run.run_id)
        self.assertEqual(self.model.calls, [])

    def test_saved_start_redrives_same_intent_after_early_task_failure_without_new_budget(self):
        run = self.start()

        class TemporarilyUnavailableRecords:
            def read_batch_record(self, key):
                raise RuntimeError("synthetic_storage_unavailable")

        failed_worker = Batch(self.execution, TemporarilyUnavailableRecords(), self.scheduler)
        with self.assertRaises(ExecutionError):
            failed_worker.run(run.run_id)
        self.assertEqual(self.start(), run)
        self.assertEqual(self.scheduler.deliveries, [run.run_id, run.run_id])
        self.assertEqual(self.model.calls, [])
        self.restore().run(run.run_id)
        self.assertEqual(self.start(), run)
        self.assertEqual(self.scheduler.deliveries, [run.run_id, run.run_id])
        self.assertEqual(len(self.model.calls), 2)
