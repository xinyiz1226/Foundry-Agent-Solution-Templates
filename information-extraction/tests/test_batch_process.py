import asyncio
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from information_extraction import Execution, SQLiteStore
from information_extraction.batch import Batch, BatchLimits, BatchState
from information_extraction.sample import synthetic_plan
from tests.test_batch import QueueScheduler
from tests.test_execution import SyntheticModel


WORKER = """
import os
import sys
from information_extraction import Execution, SQLiteStore
from information_extraction.batch import Batch
from tests.test_batch import QueueScheduler
from tests.test_execution import SyntheticModel
mode, database, run_id = sys.argv[1:]

class Model(SyntheticModel):
    def complete(self, request):
        if mode == "model":
            os._exit(23)
        return super().complete(request)

class Store(SQLiteStore):
    def publish(self, claimed, result):
        super().publish(claimed, result)
        os._exit(23)

Batch(Execution(Store(database), Model()), SQLiteStore(database),
      QueueScheduler(), clock=lambda: 1000).run(run_id)
"""


class BatchProcessTests(unittest.TestCase):
    def test_fresh_process_restores_unknown_claim_or_known_commit_without_budget_reset(self):
        Path(".test-data").mkdir(exist_ok=True)
        for mode in ("model", "publication"):
            with self.subTest(mode=mode), TemporaryDirectory(dir=".test-data") as directory:
                database = Path(directory) / "batch.sqlite3"
                store = SQLiteStore(database)
                model = SyntheticModel()
                execution = Execution(store, model)
                execution.create("job", synthetic_plan(), "create")
                batch = Batch(execution, store, QueueScheduler(), clock=lambda: 1000)
                limits = BatchLimits(max_attempts=1, deadline=1060)
                run = asyncio.run(batch.start("job", 0, "start", limits))
                crashed = subprocess.run(
                    [sys.executable, "-c", WORKER, mode, str(database), run.run_id],
                    capture_output=True, text=True, timeout=10, check=False,
                )
                self.assertEqual(crashed.returncode, 23, crashed.stderr)
                restored = Batch(
                    Execution(SQLiteStore(database), model), SQLiteStore(database),
                    QueueScheduler(), clock=lambda: 1001,
                )
                restored.run(run.run_id)
                status = restored.status(run.run_id)
                self.assertEqual(
                    status.state, BatchState.BLOCKED if mode == "model" else BatchState.LIMITED,
                )
                self.assertEqual(status.attempts_reserved, 1)
                self.assertEqual(status.authorization.limits.deadline, 1060)
                self.assertEqual(model.calls, [])
