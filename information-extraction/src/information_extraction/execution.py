"""Synchronous one-attempt execution, independent of any process host."""

from dataclasses import replace
from .contracts import (
    Action, Attempt, Conflict, FailureCode, InvalidInput, Model, ModelFailure,
    ModelRequest, ModelResponse, Plan, Snapshot, Status, Store, TokenUsage, ValidationFailure,
    validate_identifier,
)
from .outputs import resolve_candidates


def _usage(value: object) -> TokenUsage | None:
    if value is None:
        return None
    if not isinstance(value, TokenUsage) or any(
        type(count) is not int or count < 0 for count in (value.input_tokens, value.output_tokens)
    ):
        raise ValidationFailure(FailureCode.INVALID_USAGE)
    return value


class Execution:
    def __init__(self, store: Store, model: Model):
        self._store = store
        self._model = model

    def create(self, job_id: str, plan: Plan, request_id: str) -> Snapshot:
        """Persist the frozen plan without invoking the model."""
        validate_identifier(job_id)
        validate_identifier(request_id)
        if not isinstance(plan, Plan):
            raise InvalidInput("invalid_plan")
        return self._store.create(job_id, plan, request_id)

    def read(self, job_id: str) -> Snapshot:
        """Inspect only; IN_PROGRESS cannot distinguish active from interrupted."""
        validate_identifier(job_id)
        return self._store.read(job_id)

    def advance(
        self, job_id: str, expected_revision: int, request_id: str,
        *, action: Action = Action.ADVANCE,
    ) -> Snapshot:
        """At most one model attempt; a saved request returns its historical result."""
        validate_identifier(job_id)
        validate_identifier(request_id)
        if type(expected_revision) is not int or expected_revision < 0:
            raise InvalidInput("invalid_expected_revision")
        if not isinstance(action, Action):
            raise InvalidInput("invalid_action")
        if self._store.read(job_id).plan.model_binding != self._model.binding:
            raise Conflict("model_binding_mismatch")
        claimed = self._store.claim(job_id, expected_revision, request_id, action)
        if claimed.claim is None:
            return claimed
        chunk = claimed.plan.chunks[len(claimed.completed_chunk_ids)]
        usage = None
        failure = None
        candidates = ()
        try:
            response = self._model.complete(ModelRequest(
                job_id, request_id, expected_revision, chunk, claimed.plan,
            ))
            if not isinstance(response, ModelResponse):
                raise ValidationFailure(FailureCode.MALFORMED_OUTPUT)
            usage = _usage(response.usage)
            candidates = resolve_candidates(claimed, chunk, response.payload)
        except ModelFailure as error:
            failure = error.code
            try:
                usage = _usage(error.usage)
            except ValidationFailure as invalid:
                failure = invalid.code
        except ValidationFailure as error:
            failure = error.code
        completed = claimed.completed_chunk_ids
        if failure is None:
            completed = (*completed, chunk.id)
        result = replace(
            claimed,
            revision=expected_revision + 1,
            status=Status.FAILED if failure else (
                Status.COMPLETED if len(completed) == len(claimed.plan.chunks) else Status.READY
            ),
            completed_chunk_ids=completed,
            candidates=(*claimed.candidates, *candidates),
            attempts=(*claimed.attempts, Attempt(
                request_id, expected_revision + 1, chunk.id, failure, usage,
                tuple(block.id for block in chunk.blocks) if failure is None else (),
            )),
            claim=None,
        )
        return self._store.publish(claimed, result)
