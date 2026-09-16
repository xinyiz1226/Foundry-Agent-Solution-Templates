"""Local profile routing and durable, conservative provider-call admission."""

from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
import json
from typing import Callable, Iterator, Protocol, TYPE_CHECKING
from uuid import uuid4

from .codec import _hash, _json
from .contracts import (
    Action, Blocked, ConfiguredPlan, Conflict, ExtractionProfile, FailureCode,
    InvalidInput, Model, ModelFailure, ModelRequest, ModelResponse, Snapshot, TokenUsage,
    validate_identifier,
)
from .execution import Execution
from .sqlite_store import SQLiteStore

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential
    from .foundry_model import FoundrySettings


class ModelProvider(Protocol):
    enabled: bool
    description: str

    @property
    def remaining_calls(self) -> int: ...
    def binding(self, profile: ExtractionProfile) -> str: ...
    def open(self, profile: ExtractionProfile) -> AbstractContextManager[Model]: ...


class PrepareOnlyProvider:
    enabled = False
    description = "Prepare only - model execution disabled"
    remaining_calls = 0

    def binding(self, profile: ExtractionProfile) -> str:
        return "prepare-only-v1"

    def open(self, profile: ExtractionProfile) -> AbstractContextManager[Model]:
        raise InvalidInput("model_execution_disabled")


class _LazyModel:
    def __init__(self, provider: ModelProvider, profile: ExtractionProfile):
        self.provider, self.profile = provider, profile
        self.binding = provider.binding(profile)

    def complete(self, request: ModelRequest) -> ModelResponse:
        with self.provider.open(self.profile) as model:
            if model.binding != self.binding:
                raise Conflict("provider_binding_changed")
            return model.complete(request)


class ConfiguredExecution:
    def __init__(self, store: SQLiteStore, provider: ModelProvider):
        self.store, self.provider = store, provider

    def read(self, job_id: str) -> Snapshot:
        validate_identifier(job_id)
        result = self.store.read(job_id)
        if not isinstance(result.plan, ConfiguredPlan):
            raise Conflict("configured_workspace_requires_configured_jobs")
        return result

    def advance(
        self, job_id: str, expected_revision: int, request_id: str, *, action: Action = Action.ADVANCE,
    ) -> Snapshot:
        snapshot = self.read(job_id)
        if not isinstance(snapshot.plan, ConfiguredPlan):
            raise Conflict("configured_plan_required")
        return Execution(self.store, _LazyModel(self.provider, snapshot.plan.profile)).advance(
            job_id, expected_revision, request_id, action=action,
        )


class CallBudget:
    """Create-only slots count potential calls, including unknown outcomes."""

    def __init__(self, store: SQLiteStore, *, limit: int, configuration: str, budget_id: str = "initial"):
        if type(limit) is not int or not 1 <= limit <= 5:
            raise InvalidInput("model_call_limit_must_be_1_to_5")
        validate_identifier(budget_id)
        self.store, self.limit = store, limit
        self.prefix = "configured-budget-" + _hash(budget_id)
        body = _json({"limit": limit, "configuration": configuration, "version": 1, "budget_id": budget_id})
        saved = store.create_batch_record(self.prefix, body)
        if saved != body:
            raise Conflict("model_budget_configuration_changed")

    @property
    def remaining(self) -> int:
        return sum(self.store.read_batch_record(f"{self.prefix}-{index}") is None
                   for index in range(self.limit))

    def admit(self, request: ModelRequest) -> None:
        identity = {
            "job_id": request.job_id, "request_id": request.request_id,
            "model_binding": request.plan.model_binding,
        }
        body = _json({"identity": identity, "admission_id": uuid4().hex})
        for index in range(self.limit):
            key = f"{self.prefix}-{index}"
            existing = self.store.read_batch_record(key)
            if existing is not None and json.loads(existing)["identity"] == identity:
                raise Blocked("provider_call_already_admitted")
            if existing is not None:
                continue
            saved = self.store.create_batch_record(key, body)
            if saved == body:
                return
            if json.loads(saved)["identity"] == identity:
                raise Blocked("provider_call_already_admitted")
        raise ModelFailure(FailureCode.MODEL_REJECTED, TokenUsage(0, 0))


class _BudgetedModel:
    def __init__(self, model: Model, budget: CallBudget):
        self.model, self.budget, self.binding = model, budget, model.binding

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.budget.admit(request)
        return self.model.complete(request)


class FoundryProvider:
    enabled = True

    def __init__(
        self, store: SQLiteStore, settings: "FoundrySettings",
        credential_factory: Callable[[], AbstractContextManager["TokenCredential"]], *, call_limit: int = 5,
        budget_id: str = "initial",
    ):
        self.settings, self.credential_factory = settings, credential_factory
        self.description = f"Foundry deployment: {settings.deployment} (budget: {budget_id})"
        self.budget = CallBudget(store, limit=call_limit, configuration=settings.binding, budget_id=budget_id)

    @property
    def remaining_calls(self) -> int:
        return self.budget.remaining

    def _settings(self, profile: ExtractionProfile) -> "FoundrySettings":
        return replace(self.settings, profile_version=profile.version, profile=profile)

    def binding(self, profile: ExtractionProfile) -> str:
        return self._settings(profile).binding

    @contextmanager
    def open(self, profile: ExtractionProfile) -> Iterator[Model]:
        from .foundry_model import open_foundry_model

        with self.credential_factory() as credential:
            with open_foundry_model(self._settings(profile), credential) as model:
                yield _BudgetedModel(model, self.budget)
