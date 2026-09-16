"""Authenticated, loopback-only configured workbench over the native task host."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import hmac
import json
import logging
import os
import time
from typing import Callable

from azure.ai.agentserver.core.tasks import resilient_tasks_enabled
from azure.ai.agentserver.core._middleware import InboundRequestLoggingMiddleware
from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .batch import Authorization, Batch, BatchState, RegistrationUnknown
from .codec import _hash, _json
from .configured_inputs import prepare_plan
from .configured_runtime import ConfiguredExecution, ModelProvider
from .contracts import (
    ConfiguredPlan, Conflict, ExecutionError, IntegrityError, InvalidInput, NotFound,
    Snapshot, Status, validate_identifier,
)
from .hosted_app import (
    RequestTooLarge, ResumeInput, SavedRequestExpired, StartInput, UnsupportedMediaType,
    _authorized_request, _decode_input, _freeze_request, _nonfinite, _object,
    _owned, _read_intent, _safe_sdk_logs, _storage,
)
from .native_batch import create_native_batch
from .profiles import FINANCIAL_PROFILE, SUPPORT_PROFILE
from .schema import load_profile
from .sqlite_store import SQLiteStore


MAX_REQUEST_BYTES = 512 * 1024
logger = logging.getLogger(__name__)


def validate_token(token: str) -> None:
    if type(token) is not str or not 32 <= len(token) <= 4096 or any(
        not 33 <= ord(character) <= 126 for character in token
    ):
        raise InvalidInput("invalid_workbench_token")


async def _body(request: Request) -> dict:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise UnsupportedMediaType("json_required")
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isdecimal() or len(length) > 20:
            raise InvalidInput("invalid_content_length")
        if int(length) > MAX_REQUEST_BYTES:
            raise RequestTooLarge("request_too_large")
    payload = bytearray()
    async for part in request.stream():
        if len(payload) + len(part) > MAX_REQUEST_BYTES:
            raise RequestTooLarge("request_too_large")
        payload.extend(part)
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_object, parse_constant=_nonfinite)
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidInput("invalid_json") from None
    if type(value) is not dict:
        raise InvalidInput("object_required")
    return value


def _configured(snapshot: Snapshot, job_id: str) -> None:
    if (
        not isinstance(snapshot.plan, ConfiguredPlan) or snapshot.job_id != job_id
        or job_id != "configured-" + _hash(_json(asdict(snapshot.plan)))
    ):
        raise IntegrityError("configured_job_ownership_invalid")


def _existing_round(batch: Batch, data: StartInput | ResumeInput, job_id: str) -> Authorization | None:
    current = batch.current(job_id)
    predecessor = data.run_id if isinstance(data, ResumeInput) else None
    if current is None:
        if predecessor is not None:
            raise Conflict("resume_not_current")
        return None
    if current.authorization.run_id == predecessor:
        return None
    for _ in range(1024):
        _owned(current, job_id)
        _configured(current.snapshot, job_id)
        run = current.authorization
        if run.previous_run_id == predecessor:
            return run
        if run.previous_run_id is None:
            raise Conflict("resume_not_owned")
        current = batch.status(run.previous_run_id)
    raise IntegrityError("batch_chain_traversal_limit")


async def _pending(store, job_id, current):
    if current is None:
        return await _read_intent(store, job_id, None)
    if current.state in (BatchState.FAILED, BatchState.LIMITED):
        pending = await _read_intent(store, job_id, current.authorization.run_id)
        if pending is not None and pending["expected_revision"] != current.snapshot.revision:
            raise IntegrityError("invocation_intent_revision_invalid")
        if pending is not None or current.registration_confirmed:
            return pending
    if current.state != BatchState.COMPLETED or not current.registration_confirmed:
        run = current.authorization
        pending = await _read_intent(store, job_id, run.previous_run_id)
        original = _authorized_request(run)
        if pending is not None and pending != original:
            raise IntegrityError("invocation_intent_authorization_invalid")
        return original if pending is None else pending
    return None


def create_configured_app(
    store: SQLiteStore, provider: ModelProvider, *, token: str,
    clock: Callable[[], float] = time.time,
) -> InvocationAgentServerHost:
    """The caller must bind this same-user development server to 127.0.0.1."""
    validate_token(token)
    if (
        os.environ.get("AGENTSERVER_TASKS_BACKEND") != "local"
        or os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT")
        or not os.environ.get("AGENTSERVER_STATE_ROOT")
    ):
        raise InvalidInput("explicit_offline_configuration_required")
    execution = ConfiguredExecution(store, provider)
    batch = create_native_batch(execution, store, clock=clock)
    app = InvocationAgentServerHost(
        configure_observability=None, graceful_shutdown_timeout=1, access_log=None,
    )
    app.user_middleware[:] = [
        middleware for middleware in app.user_middleware
        if middleware.cls is not InboundRequestLoggingMiddleware
    ]
    original_lifespan = app.router.lifespan_context
    ready = False

    @asynccontextmanager
    async def lifespan(host):
        nonlocal ready
        with _safe_sdk_logs():
            failure = None
            try:
                if (
                    os.environ.get("AGENTSERVER_TASKS_BACKEND") != "local"
                    or os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT")
                    or not os.environ.get("AGENTSERVER_STATE_ROOT")
                    or not resilient_tasks_enabled()
                ):
                    raise ExecutionError("resilient_host_configuration_changed")
                async with original_lifespan(host) as state:
                    ready = True
                    try:
                        yield state
                    except BaseException as error:
                        # Let the SDK's post-yield cleanup execute even on cancellation.
                        failure = error
                    finally:
                        ready = False
            except BaseException as error:
                failure = failure or error
            if isinstance(failure, asyncio.CancelledError):
                raise failure
            if failure is not None:
                raise ExecutionError("configured_host_lifecycle_failed") from None

    app.router.lifespan_context = lifespan

    def error(code, status, **details):
        return JSONResponse({"error": {"code": code, **details}}, status_code=status)

    async def boundary(request, call_next):
        if "origin" in request.headers:
            return error("origin_not_allowed", 403)
        if request.url.query:
            return error("query_not_allowed", 400)
        if request.url.path != "/health":
            values = request.headers.getlist("authorization")
            supplied = values[0] if len(values) == 1 else ""
            if not hmac.compare_digest(supplied.encode("utf-8"), ("Bearer " + token).encode("ascii")):
                return error("unauthorized", 401)
        try:
            response = await call_next(request)
        except RequestTooLarge:
            return error("request_too_large", 413)
        except UnsupportedMediaType:
            return error("unsupported_media_type", 415)
        except InvalidInput:
            return error("invalid_request", 400)
        except SavedRequestExpired:
            return error("saved_request_expired", 409)
        except RegistrationUnknown as failure:
            return error("batch_registration_unknown", 503, authorization=asdict(failure.authorization))
        except Conflict:
            return error("execution_conflict", 409)
        except NotFound:
            return error("not_found", 404)
        except IntegrityError:
            return error("stored_state_invalid", 500)
        except ExecutionError:
            return error("execution_unavailable", 503)
        except Exception:
            logger.error("configured_request_failed")
            return error("internal_error", 500)
        response.headers["Cache-Control"] = "no-store"
        return response

    async def health(request):
        return JSONResponse({"ready": ready}, status_code=200 if ready else 503)

    async def configuration(request):
        return JSONResponse({
            "enabled": provider.enabled, "model_description": provider.description,
            "remaining_calls": provider.remaining_calls,
            "profiles": {"financial": asdict(FINANCIAL_PROFILE), "support": asdict(SUPPORT_PROFILE)},
        })

    async def jobs(request):
        if request.method == "GET":
            snapshots = await _storage(store.list_jobs)
            result = []
            for snapshot in snapshots:
                _configured(snapshot, snapshot.job_id)
                result.append({
                    "job_id": snapshot.job_id, "document_id": snapshot.plan.document_id,
                    "profile_version": snapshot.plan.profile_version, "revision": snapshot.revision,
                    "status": snapshot.status.value,
                })
            return JSONResponse({"jobs": result})
        data = await _body(request)
        if (
            set(data) != {"kind", "content", "profile", "split", "conversation_id"}
            or type(data["kind"]) is not str or data["kind"] not in ("text", "abcd")
            or type(data["content"]) is not str
            or type(data["split"]) is not str or data["split"] not in ("train", "dev", "test")
            or (data["conversation_id"] is not None and (
                type(data["conversation_id"]) is not int or data["conversation_id"] < 0
            ))
        ):
            raise InvalidInput("invalid_prepare_fields")
        try:
            content = data["content"].encode("utf-8")
            profile = load_profile(_json(data["profile"]).encode("utf-8"))
        except (ValueError, UnicodeError, TypeError):
            raise InvalidInput("invalid_prepare_content") from None
        plan = prepare_plan(
            content, kind=data["kind"], profile=profile, model_binding=provider.binding(profile),
            split=data["split"], conversation_id=data["conversation_id"],
        )
        job_id = "configured-" + _hash(_json(asdict(plan)))
        create_id = "configured-create-" + _hash(_json([job_id, asdict(plan)]))
        validate_identifier(job_id)
        validate_identifier(create_id)
        snapshot = await _storage(lambda: store.create(job_id, plan, create_id))
        _configured(snapshot, job_id)
        return JSONResponse({"job_id": job_id, "snapshot": asdict(snapshot)})

    async def current(request):
        job_id = request.path_params["job_id"]
        validate_identifier(job_id)
        snapshot = await _storage(lambda: execution.read(job_id))
        _configured(snapshot, job_id)
        status = await _storage(lambda: batch.current(job_id))
        if status is not None:
            _owned(status, job_id)
            _configured(status.snapshot, job_id)
            # Native progress can commit between these reads; return the latest ledger.
            snapshot = await _storage(lambda: execution.read(job_id))
            _configured(snapshot, job_id)
        return JSONResponse({
            "job_id": job_id, "snapshot": asdict(snapshot),
            "round": None if status is None else {
                "authorization": asdict(status.authorization), "state": status.state.value,
                "attempts_reserved": status.attempts_reserved,
                "registration_confirmed": status.registration_confirmed,
            },
            "pending_request": await _pending(store, job_id, status),
        })

    async def submit(request):
        job_id = request.path_params["job_id"]
        validate_identifier(job_id)
        data = _decode_input(await _body(request))
        if not isinstance(data, (StartInput, ResumeInput)):
            raise InvalidInput("invalid_round_action")
        snapshot = await _storage(lambda: execution.read(job_id))
        _configured(snapshot, job_id)
        if not provider.enabled:
            return error("model_disabled", 409)
        if provider.remaining_calls <= 0:
            return error("model_budget_exhausted", 409)
        if isinstance(data, StartInput):
            if data.job_id != job_id or data.expected_revision != 0:
                raise Conflict("start_requires_owned_revision_zero")
        else:
            previous = await _storage(lambda: batch.status(data.run_id))
            _owned(previous, job_id)
            _configured(previous.snapshot, job_id)
            if (
                previous.state not in (BatchState.FAILED, BatchState.LIMITED)
                or previous.snapshot.revision != data.expected_revision
            ):
                raise Conflict("resume_not_applicable")
        committed = await _storage(lambda: _existing_round(batch, data, job_id))
        if committed is None:
            if snapshot.plan.model_binding != provider.binding(snapshot.plan.profile):
                raise Conflict("configured_model_binding_changed")
            if isinstance(data, StartInput) and (snapshot.revision != 0 or snapshot.status != Status.READY):
                raise Conflict("start_requires_ready_revision_zero")
            if data.limits.deadline > clock() + 300:
                raise InvalidInput("deadline_out_of_range")
        await _freeze_request(store, data, clock, job_id, committed)
        if isinstance(data, StartInput):
            run = await batch.start(job_id, data.expected_revision, data.request_id, data.limits)
        else:
            run = await batch.resume(data.run_id, data.expected_revision, data.request_id, data.limits)
        return JSONResponse({"authorization": asdict(run)}, status_code=202)

    app.add_route("/health", health, methods=["GET"])
    app.add_route("/configuration", configuration, methods=["GET"])
    app.add_route("/jobs", jobs, methods=["GET", "POST"])
    app.add_route("/jobs/{job_id}", current, methods=["GET"])
    app.add_route("/jobs/{job_id}/round", submit, methods=["POST"])
    app.add_middleware(BaseHTTPMiddleware, dispatch=boundary)
    return app
