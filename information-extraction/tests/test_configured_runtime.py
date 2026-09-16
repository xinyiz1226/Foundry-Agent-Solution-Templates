from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest

from information_extraction import (
    Blocked, Conflict, InvalidInput, ModelFailure, ModelRequest, ModelResponse, SQLiteStore, Status,
)
from information_extraction.configured_inputs import prepare_plan
from information_extraction.configured_runtime import CallBudget, ConfiguredExecution, PrepareOnlyProvider
from information_extraction.profiles import FINANCIAL_PROFILE


class TestProvider:
    enabled = True
    description = "Explicit test fixture, not inference"
    remaining_calls = 5

    def __init__(self):
        self.opens = 0
        self.calls = []

    def binding(self, profile):
        return "lazy-fixture-v1"

    @contextmanager
    def open(self, profile):
        self.opens += 1
        owner = self

        class Model:
            binding = owner.binding(profile)

            def complete(self, request):
                owner.calls.append(request)
                return ModelResponse({"records": []})

        yield Model()


class ConfiguredRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "workspace.sqlite3"
        self.store = SQLiteStore(self.path)
        self.provider = TestProvider()
        self.plan = prepare_plan(b"Fictional text.", kind="text", profile=FINANCIAL_PROFILE,
                                 model_binding=self.provider.binding(FINANCIAL_PROFILE))

    def test_read_create_and_historical_replay_never_open_provider(self):
        self.store.create("job", self.plan, "create")
        execution = ConfiguredExecution(self.store, self.provider)
        execution.read("job")
        self.assertEqual(self.provider.opens, 0)
        completed = execution.advance("job", 0, "attempt")
        self.assertEqual(completed.status, Status.COMPLETED)
        self.assertEqual((self.provider.opens, len(self.provider.calls)), (1, 1))
        other = TestProvider()
        restored = ConfiguredExecution(SQLiteStore(self.path), other)
        self.assertEqual(restored.read("job"), completed)
        self.assertEqual(restored.advance("job", 0, "attempt"), completed)
        self.assertEqual((other.opens, other.calls), (0, []))

    def test_prepare_only_has_no_fake_model(self):
        provider = PrepareOnlyProvider()
        self.assertFalse(provider.enabled)
        self.assertEqual(provider.remaining_calls, 0)
        with self.assertRaisesRegex(InvalidInput, "model_execution_disabled"):
            provider.open(FINANCIAL_PROFILE)

    def test_budget_is_persistent_never_refunded_and_cannot_be_reset_by_restart(self):
        budget = CallBudget(self.store, limit=2, configuration="settings-v1")
        request = ModelRequest("job", "one", 0, self.plan.chunks[0], self.plan)
        budget.admit(request)
        self.assertEqual(budget.remaining, 1)
        with self.assertRaises(Blocked):
            budget.admit(request)
        restored = CallBudget(SQLiteStore(self.path), limit=2, configuration="settings-v1")
        self.assertEqual(restored.remaining, 1)
        restored.admit(replace(request, request_id="two"))
        with self.assertRaises(ModelFailure):
            restored.admit(replace(request, request_id="three"))
        self.assertEqual(restored.remaining, 0)
        for limit, config in ((3, "settings-v1"), (2, "changed")):
            with self.assertRaises(Conflict):
                CallBudget(self.store, limit=limit, configuration=config)
        fresh_grant = CallBudget(self.store, limit=2, configuration="settings-v1", budget_id="explicit-next-grant")
        self.assertEqual(fresh_grant.remaining, 2)
        self.assertEqual(restored.remaining, 0)

    def test_budget_arbitrates_concurrent_requests_and_identical_requests(self):
        for same_request in (False, True):
            path = Path(self.directory.name) / f"concurrent-{same_request}.sqlite3"
            store = SQLiteStore(path)
            budget = CallBudget(store, limit=1, configuration="settings")
            barrier = Barrier(2)

            def admit(index):
                barrier.wait(timeout=5)
                request = ModelRequest("job", "same" if same_request else f"request-{index}",
                                       0, self.plan.chunks[0], self.plan)
                try:
                    budget.admit(request)
                    return True
                except (Blocked, ModelFailure):
                    return False

            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(admit, range(2)))
            self.assertEqual(sum(outcomes), 1)
            self.assertEqual(budget.remaining, 0)
