"""Synthetic-only Invocations probe; gateway RBAC is the authorization boundary."""

import asyncio
from contextlib import ExitStack, asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass
import json
import logging
import os
import re
import time
from typing import Callable, Iterator, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from azure.ai.agentserver.core.tasks import resilient_tasks_enabled
from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .batch import BatchLimits, BatchRecords, BatchState, BatchStatus, RegistrationUnknown
from .codec import _hash, _json
from .contracts import (
    Conflict, ExecutionError, IntegrityError, InvalidInput, Model, ModelRequest, ModelResponse,
    NotFound, Snapshot, Store, TokenUsage, validate_identifier,
)
from .execution import Execution
from .native_batch import create_native_batch
from .sample import synthetic_plan


MAX_REQUEST_BYTES = 16 * 1024
logger = logging.getLogger(__name__)


@contextmanager
def _safe_sdk_logs() -> Iterator[None]:
    previous = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        if record.name.startswith("azure.") and record.levelno >= logging.WARNING:
            record.msg = "azure_sdk_error" if record.levelno >= logging.ERROR else "azure_sdk_warning"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return record

    logging.setLogRecordFactory(record_factory)
    try:
        yield
    finally:
        logging.setLogRecordFactory(previous)


class BatchStore(Store, BatchRecords, Protocol):
    pass


@dataclass(frozen=True)
class HostedConfig:
    account_url: str
    container: str
    prefix: str
    job_id: str

    @classmethod
    def from_environment(cls) -> "HostedConfig":
        _production_credentials()
        if (
            os.environ.get("AGENTSERVER_TASKS_BACKEND") != "hosted"
            or not os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT", "").strip()
        ):
            raise InvalidInput("explicit_hosted_tasks_required")
        endpoint_host, endpoint_path = _https_url(os.environ.get("FOUNDRY_PROJECT_ENDPOINT", ""))
        if not endpoint_host.endswith(".services.ai.azure.com") or not endpoint_path.startswith("/api/projects/"):
            raise InvalidInput("invalid_foundry_project_endpoint")
        account_url = os.environ.get("EXTRACTION_BLOB_ACCOUNT_URL", "")
        account_host, account_path = _https_url(account_url)
        if (
            re.fullmatch(r"[a-z0-9]{3,24}\.blob\.core\.windows\.net", account_host) is None
            or account_path not in ("", "/")
        ):
            raise InvalidInput("invalid_blob_account_url")
        container = os.environ.get("EXTRACTION_BLOB_CONTAINER", "")
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", container) is None or "--" in container:
            raise InvalidInput("invalid_blob_container")
        prefix = os.environ.get("EXTRACTION_BLOB_PREFIX", "")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", prefix) is None:
            raise InvalidInput("invalid_blob_prefix")
        job_id = os.environ.get("EXTRACTION_JOB_ID", "")
        validate_identifier(job_id)
        return cls(account_url.rstrip("/"), container, prefix, job_id)


def _production_credentials() -> None:
    if os.environ.get("AZURE_TOKEN_CREDENTIALS") != "prod":
        raise InvalidInput("explicit_production_credentials_required")


def _https_url(value: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        if (
            parsed.scheme != "https" or not hostname or parsed.username is not None
            or parsed.password is not None or parsed.port is not None or parsed.query or parsed.fragment
        ):
            raise ValueError
        return hostname, parsed.path
    except ValueError:
        raise InvalidInput("invalid_service_url") from None


class SyntheticFinancialModel:
    binding = "synthetic-model-v1"

    def complete(self, request: ModelRequest) -> ModelResponse:
        if request.plan != synthetic_plan():
            raise Conflict("non_synthetic_execution")
        metric, value = (
            ("revenue", 120) if request.chunk.id == "chunk-1" else ("operating_income", 18)
        )
        return ModelResponse({"records": [{
            "metric": metric, "value": value, "unit": "USD_millions",
            "block_ids": [request.chunk.blocks[0].id],
        }]}, TokenUsage(0, 0))


@dataclass(frozen=True)
class StartInput:
    job_id: str
    request_id: str
    expected_revision: int
    limits: BatchLimits


@dataclass(frozen=True)
class ResumeInput:
    run_id: str
    request_id: str
    expected_revision: int
    limits: BatchLimits


@dataclass(frozen=True)
class StatusInput:
    run_id: str


class RequestTooLarge(InvalidInput):
    pass


class UnsupportedMediaType(InvalidInput):
    pass


class JobNotOwned(Conflict):
    pass


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidInput("duplicate_json_field")
        result[key] = value
    return result


def _nonfinite(value):
    raise InvalidInput("nonfinite_json_number")


async def _input(request: Request) -> StartInput | ResumeInput | StatusInput:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise UnsupportedMediaType("json_required")
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isdecimal() or len(length) > 20:
            raise InvalidInput("invalid_content_length")
        if int(length) > MAX_REQUEST_BYTES:
            raise RequestTooLarge("request_too_large")
    body = bytearray()
    async for part in request.stream():
        if len(body) + len(part) > MAX_REQUEST_BYTES:
            raise RequestTooLarge("request_too_large")
        body.extend(part)
    try:
        data = json.loads(body.decode("utf-8"), object_pairs_hook=_object, parse_constant=_nonfinite)
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidInput("invalid_json") from None
    if type(data) is not dict:
        raise InvalidInput("object_required")
    action = data.get("action")
    if action == "status" and set(data) == {"action", "run_id"}:
        validate_identifier(data["run_id"])
        return StatusInput(data["run_id"])
    if action not in ("start", "resume"):
        raise InvalidInput("invalid_action")
    target = "job_id" if action == "start" else "run_id"
    if set(data) != {"action", target, "request_id", "expected_revision", "max_attempts", "deadline"}:
        raise InvalidInput("invalid_fields")
    validate_identifier(data[target])
    validate_identifier(data["request_id"])
    revision = data["expected_revision"]
    if type(revision) is not int or not 0 <= revision < 2**63:
        raise InvalidInput("invalid_revision")
    limits = BatchLimits(max_attempts=data["max_attempts"], deadline=data["deadline"])
    if action == "start":
        return StartInput(data["job_id"], data["request_id"], revision, limits)
    return ResumeInput(data["run_id"], data["request_id"], revision, limits)


async def _storage[T](operation: Callable[[], T]) -> T:
    try:
        return await asyncio.to_thread(operation)
    except ExecutionError:
        raise
    except Exception:
        raise ExecutionError("storage_unavailable") from None


async def _freeze_request(
    store: BatchRecords, data: StartInput | ResumeInput, clock: Callable[[], float],
) -> None:
    key = _hash(_json(["synthetic-invocation-v1", data.request_id]))
    payload = _json({
        "version": 1, "action": "start" if isinstance(data, StartInput) else "resume",
        "request": asdict(data),
    })
    saved = await _storage(lambda: store.read_batch_record(key))
    if saved is None:
        now = clock()
        if not now < data.limits.deadline <= now + 604800:
            raise InvalidInput("deadline_out_of_range")
        saved = await _storage(lambda: store.create_batch_record(key, payload))
    if saved != payload:
        raise Conflict("invocation_request_conflict")


def _fixture(snapshot: Snapshot) -> None:
    if snapshot.plan != synthetic_plan():
        raise Conflict("non_synthetic_execution")


def _owned(status: BatchStatus, job_id: str) -> None:
    if status.authorization.job_id != job_id or status.snapshot.job_id != job_id:
        raise JobNotOwned("job_not_owned")


def _status(status: BatchStatus) -> dict:
    _fixture(status.snapshot)
    return {
        "authorization": asdict(status.authorization),
        "state": status.state.value,
        "execution_state": status.snapshot.status.value,
        "revision": status.snapshot.revision,
        "completed_chunks": list(status.snapshot.completed_chunk_ids),
        "attempts_reserved": status.attempts_reserved,
        "committed_attempts": len(status.snapshot.attempts),
        "registration_confirmed": status.registration_confirmed,
        "usage": {
            "known_input_tokens": status.known_input_tokens,
            "known_output_tokens": status.known_output_tokens,
            "unknown_usage_attempts": status.unknown_usage_attempts,
        },
        "candidates": [asdict(candidate) for candidate in status.snapshot.candidates],
    }


def _build_app(
    store: BatchStore, model: Model, *, clock: Callable[[], float],
    backend: str, job_id: str, close_resources: Callable[[], None] | None = None,
) -> InvocationAgentServerHost:
    validate_identifier(job_id)
    execution = Execution(store, model)
    batch = create_native_batch(execution, store, clock=clock)
    app = InvocationAgentServerHost(configure_observability=None, graceful_shutdown_timeout=1, access_log=None)
    app_instance_id = str(uuid4())
    original_lifespan = app.router.lifespan_context
    if backend == "hosted":
        from .hosted_lifecycle import hosted_lifespan
        original_lifespan = hosted_lifespan

    def response(payload: dict, status_code: int = 200) -> JSONResponse:
        return JSONResponse(
            {"synthetic_only": True, "app_instance_id": app_instance_id, **payload},
            status_code=status_code,
        )

    def _error(code: str, status_code: int, **details) -> JSONResponse:
        return response({"error": {"code": code, **details}}, status_code)

    @asynccontextmanager
    async def lifespan(host):
        with _safe_sdk_logs():
            failure = None
            try:
                if backend == "hosted":
                    _production_credentials()
                if (
                    os.environ.get("AGENTSERVER_TASKS_BACKEND") != backend
                    or bool(os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT")) != (backend == "hosted")
                    or not resilient_tasks_enabled()
                ):
                    raise ExecutionError("resilient_host_configuration_changed")
                async with original_lifespan(host) as state:
                    try:
                        yield state
                    except BaseException as error:
                        # Exit the SDK 2.1.0 lifespan normally so its post-yield cleanup runs.
                        failure = error
            except BaseException as error:
                if failure is None:
                    failure = error
                else:
                    logger.error("synthetic_host_cleanup_failed")
            finally:
                if close_resources is not None:
                    try:
                        close_resources()
                    except Exception:
                        logger.error("synthetic_resource_cleanup_failed")
                        if failure is None:
                            failure = ExecutionError("synthetic_resource_cleanup_failed")
            if isinstance(failure, asyncio.CancelledError):
                raise failure
            if failure is not None:
                raise ExecutionError("synthetic_host_lifecycle_failed") from None

    app.router.lifespan_context = lifespan

    @app.invoke_handler
    async def invoke(request: Request) -> Response:
        try:
            data = await _input(request)
            if isinstance(data, StatusInput):
                status = await _storage(lambda: batch.status(data.run_id))
                _owned(status, job_id)
                return response(_status(status))
            if isinstance(data, StartInput):
                if data.job_id != job_id:
                    raise JobNotOwned("job_not_owned")
                if data.expected_revision != 0:
                    raise Conflict("start_requires_revision_zero")
                await _freeze_request(store, data, clock)
                create_id = "synthetic-create-" + _hash(_json([data.job_id, data.request_id]))
                await _storage(lambda: execution.create(data.job_id, synthetic_plan(), create_id))
                run = await batch.start(data.job_id, data.expected_revision, data.request_id, data.limits)
                return response({"authorization": asdict(run)}, 202)
            previous = await _storage(lambda: batch.status(data.run_id))
            _owned(previous, job_id)
            _fixture(previous.snapshot)
            if (
                previous.state not in (BatchState.FAILED, BatchState.LIMITED)
                or previous.snapshot.revision != data.expected_revision
            ):
                raise Conflict("resume_not_applicable")
            await _freeze_request(store, data, clock)
            run = await batch.resume(data.run_id, data.expected_revision, data.request_id, data.limits)
            return response({"authorization": asdict(run)}, 202)
        except RequestTooLarge:
            return _error("request_too_large", 413)
        except UnsupportedMediaType:
            return _error("unsupported_media_type", 415)
        except InvalidInput:
            return _error("invalid_request", 400)
        except RegistrationUnknown as error:
            return _error("batch_registration_unknown", 503, authorization=asdict(error.authorization))
        except JobNotOwned:
            return _error("job_not_owned", 409)
        except Conflict:
            return _error("execution_conflict", 409)
        except NotFound:
            return _error("not_found", 404)
        except IntegrityError:
            return _error("stored_state_invalid", 500)
        except ExecutionError:
            return _error("execution_unavailable", 503)
        except Exception:
            logger.error("synthetic_invocation_internal_error")
            return _error("internal_error", 500)

    return app


def create_offline_app(
    store: BatchStore, *, model: Model | None = None, clock: Callable[[], float] = time.time,
    close_resources: Callable[[], None] | None = None, job_id: str = "synthetic-job",
) -> InvocationAgentServerHost:
    """Explicit local-only test injection; never selected by the production factory."""
    if (
        os.environ.get("AGENTSERVER_TASKS_BACKEND") != "local"
        or os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT")
        or not os.environ.get("AGENTSERVER_STATE_ROOT")
    ):
        raise InvalidInput("explicit_offline_configuration_required")
    return _build_app(
        store, model if model is not None else SyntheticFinancialModel(), clock=clock,
        backend="local", close_resources=close_resources, job_id=job_id,
    )


@_safe_sdk_logs()
def create_app() -> InvocationAgentServerHost:
    """Production: fixed synthetic model, owned Blob client, explicit hosted tasks."""
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import ContainerClient
    from .blob_store import BlobStore

    config = HostedConfig.from_environment()
    resources = ExitStack()
    try:
        # Dedicated Foundry agent identities are not proven system-assigned MSI.
        # Preserve platform credential mechanisms without developer/user fallbacks.
        credential = DefaultAzureCredential(
            exclude_cli_credential=True,
            exclude_developer_cli_credential=True,
            exclude_powershell_credential=True,
            exclude_visual_studio_code_credential=True,
            exclude_shared_token_cache_credential=True,
            exclude_interactive_browser_credential=True,
            exclude_broker_credential=True,
        )
        resources.callback(credential.close)
        container = ContainerClient(
            account_url=config.account_url, container_name=config.container,
            credential=credential, retry_total=0, connection_timeout=10, read_timeout=30,
        )
        resources.callback(container.close)
        store = BlobStore(container, prefix=config.prefix)
        return _build_app(
            store, SyntheticFinancialModel(), clock=time.time,
            backend="hosted", close_resources=resources.close, job_id=config.job_id,
        )
    except Exception:
        try:
            resources.close()
        except Exception:
            logger.error("synthetic_resource_cleanup_failed")
        raise ExecutionError("synthetic_app_construction_failed") from None
