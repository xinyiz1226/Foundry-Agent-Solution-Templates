import json
import unittest

from information_extraction import Execution
from information_extraction.batch import BatchLimits, BatchState
from information_extraction.sample import synthetic_plan
from tests import test_batch as contract
from tests.test_blob_store import AZURE_AVAILABLE, Backend, FakeContainerClient
from tests.test_execution import SyntheticModel


@unittest.skipUnless(AZURE_AVAILABLE, "optional Azure dependencies not installed")
class BlobBatchTests(contract.BatchTests):
    def setUp(self):
        from information_extraction.blob_store import BlobStore
        self.backend = Backend()
        self.make_store = lambda: BlobStore(FakeContainerClient(self.backend), prefix="batch-fixture")
        self.model = SyntheticModel()
        self.scheduler = contract.QueueScheduler()
        self.now = 1000.0
        self.execution = Execution(self.make_store(), self.model)
        self.execution.create("job", synthetic_plan(), "create")
        self.batch = self.restore()
        self.limits = BatchLimits(max_attempts=5, deadline=1060.0)

    def tearDown(self):
        pass

    def test_blob_record_write_interruptions_replay_the_persisted_start_intent(self):
        stages = {
            "authorization": lambda value: "limits" in value,
            "owner": lambda value: set(value) == {"run_id"},
            "registration": lambda value: "confirmed" in value,
            "admission": lambda value: value.get("kind") == "attempt",
            "result": lambda value: "attempts" in value,
            "terminal": lambda value: value.get("kind") == "terminal",
        }
        for stage, matches in stages.items():
            for after in (False, True):
                with self.subTest(stage=stage, after=after):
                    self.setUp()

                    def interrupt(name, data):
                        if "/batch/" in name and matches(json.loads(json.loads(data)["payload"])):
                            raise SystemExit("synthetic_storage_process_loss")

                    setattr(self.backend, "after_write" if after else "before_write", interrupt)
                    with self.assertRaises(SystemExit):
                        run = self.start()
                        self.batch.run(run.run_id)
                    self.backend.before_write = self.backend.after_write = lambda name, data: None
                    run = self.start()
                    self.restore().run(run.run_id)
                    self.assertEqual(self.batch.status(run.run_id).state, BatchState.COMPLETED)
                    self.assertEqual(len(self.model.calls), 2)
                    self.assertEqual(self.batch.status(run.run_id).authorization.limits, self.limits)

    def test_blob_unknown_execution_publication_remains_blocked(self):
        run = self.start()

        def interrupt(name, data):
            if "/checkpoints/00000000000000000001.json" in name:
                raise SystemExit("synthetic_execution_publication_loss")

        self.backend.before_write = interrupt
        with self.assertRaises(SystemExit):
            self.batch.run(run.run_id)
        self.backend.before_write = lambda name, data: None
        self.restore().run(run.run_id)
        status = self.batch.status(run.run_id)
        self.assertEqual(status.state, BatchState.BLOCKED)
        self.assertEqual(status.unknown_usage_attempts, 1)
        self.assertEqual(len(self.model.calls), 1)
