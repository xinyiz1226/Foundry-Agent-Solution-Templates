"""Optional synchronous Foundry Responses adapter; import requires the Azure extra."""

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import hashlib
import json
import logging
import math
import re
from urllib.parse import urlsplit
from typing import Iterator

from azure.ai.projects import AIProjectClient
from azure.core.credentials import TokenCredential
import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from openai.types.responses import Response

from .contracts import (
    ConfiguredPlan, Conflict, ExecutionError, ExtractionProfile, FailureCode, InvalidInput, ModelFailure,
    ModelRequest, ModelResponse, SCHEMA_VERSION, TokenUsage, validate_identifier,
)
from .legacy_financial import (
    INSTRUCTIONS as _INSTRUCTIONS, PROMPT_VERSION as _PROMPT_VERSION, SCHEMA as _SCHEMA,
)
from .schema import PROMPT_VERSION as _FLAT_PROMPT_VERSION, instructions, output_schema


class _InvalidJSON(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidJSON()
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise _InvalidJSON()


def _integer(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise _InvalidJSON() from None


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise _InvalidJSON()
    return result


def _payload(response: Response) -> object:
    if response.status != "completed" or not isinstance(response.output, list):
        return None
    texts = []
    for item in response.output:
        if getattr(item, "type", None) == "reasoning":
            continue
        if (
            getattr(item, "type", None) != "message"
            or getattr(item, "status", None) != "completed"
            or not isinstance(getattr(item, "content", None), list)
        ):
            return None
        for part in item.content:
            if getattr(part, "type", None) != "output_text" or type(getattr(part, "text", None)) is not str:
                return None
            texts.append(part.text)
    if len(texts) != 1:
        return None
    try:
        return json.loads(
            texts[0], object_pairs_hook=_unique_object, parse_constant=_reject_constant,
            parse_int=_integer, parse_float=_finite_float,
        )
    except (json.JSONDecodeError, _InvalidJSON, RecursionError):
        return None


@dataclass(frozen=True)
class FoundrySettings:
    project_endpoint: str = field(repr=False)
    deployment: str = field(repr=False)
    profile_version: str = "synthetic-financial-v1"
    max_output_tokens: int = 2048
    timeout: float = 180.0
    reasoning_effort: str | None = None
    profile: ExtractionProfile | None = field(default=None, repr=False)

    def __post_init__(self):
        if type(self.project_endpoint) is not str:
            raise InvalidInput("invalid_project_endpoint")
        try:
            endpoint = urlsplit(self.project_endpoint)
            valid = (
                endpoint.scheme == "https" and endpoint.hostname
                and not endpoint.username and not endpoint.password
                and not endpoint.query and not endpoint.fragment
                and not re.search(r"\s", self.project_endpoint)
                and endpoint.port in (None, 443)
            )
        except ValueError:
            raise InvalidInput("invalid_project_endpoint") from None
        if not valid:
            raise InvalidInput("invalid_project_endpoint")
        if type(self.deployment) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", self.deployment):
            raise InvalidInput("invalid_deployment")
        validate_identifier(self.profile_version)
        if self.profile is not None and (
            not isinstance(self.profile, ExtractionProfile) or self.profile.version != self.profile_version
        ):
            raise InvalidInput("model_profile_version_mismatch")
        if type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 32768:
            raise InvalidInput("invalid_max_output_tokens")
        if type(self.timeout) not in (int, float) or not math.isfinite(self.timeout) or self.timeout <= 0:
            raise InvalidInput("invalid_model_timeout")
        if self.reasoning_effort is not None and (
            type(self.reasoning_effort) is not str
            or self.reasoning_effort not in ("none", "minimal", "low", "medium", "high", "xhigh")
        ):
            raise InvalidInput("invalid_reasoning_effort")

    @property
    def binding(self) -> str:
        settings = {
            "endpoint": self.project_endpoint, "deployment": self.deployment,
            "profile_version": self.profile_version, "schema_version": SCHEMA_VERSION,
            "prompt_version": _PROMPT_VERSION, "instructions": _INSTRUCTIONS,
            "schema": _SCHEMA, "max_output_tokens": self.max_output_tokens,
            "timeout": self.timeout, "reasoning_effort": self.reasoning_effort,
            "store": False, "max_retries": 0, "adapter_version": "foundry-responses-v1",
        }
        if self.profile is not None:
            settings.update(
                profile=asdict(self.profile), schema_version=self.profile.schema.version,
                prompt_version=_FLAT_PROMPT_VERSION, instructions=instructions(self.profile),
                schema=output_schema(self.profile.schema), adapter_version="foundry-responses-flat-v1",
            )
        encoded = json.dumps(settings, sort_keys=True, separators=(",", ":"), allow_nan=False)
        prefix = "foundry-v1:" if self.profile is None else "foundry-flat-v1:"
        return prefix + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ProviderOutcomeUnknown(ExecutionError):
    """Ambiguous provider outcome: keep the durable claim unresolved."""

    def __init__(self):
        super().__init__("provider_outcome_unknown")


def _rejection_category(body: object) -> str:
    if type(body) is not dict:
        return "unclassified"
    details = body.get("error", body)
    if type(details) is not dict or type(details.get("message")) is not str:
        return "unclassified"
    message = details["message"].lower()
    for keyword, category in (
        ("reasoning", "reasoning_parameter"),
        ("maxitems", "schema_max_items"), ("maxlength", "schema_max_length"),
        ("schema", "schema"), ("quota", "quota"), ("rate limit", "rate_limit"),
        ("permission", "permission"), ("access denied", "permission"),
    ):
        if keyword in message:
            return category
    return "unclassified"


class FoundryModel:
    """Injected clients are caller-owned; each request overrides retry/timeout settings."""

    def __init__(self, settings: FoundrySettings, client: OpenAI):
        self._settings = settings
        self._binding = settings.binding
        self._client = client.with_options(max_retries=0, timeout=settings.timeout)

    @property
    def settings(self) -> FoundrySettings:
        return self._settings

    @property
    def binding(self) -> str:
        return self._binding

    def complete(self, request: ModelRequest) -> ModelResponse:
        if (
            request.plan.model_binding != self.binding
            or request.plan.profile_version != self.settings.profile_version
        ):
            raise Conflict("model_binding_or_profile_mismatch")
        profile = self.settings.profile
        if profile is None:
            if isinstance(request.plan, ConfiguredPlan):
                raise Conflict("model_plan_format_mismatch")
        elif (
            not isinstance(request.plan, ConfiguredPlan) or request.plan.profile != profile
            or request.chunk not in request.plan.chunks
        ):
            raise Conflict("model_plan_profile_mismatch")
        schema = _SCHEMA if profile is None else output_schema(profile.schema)
        prompt = _INSTRUCTIONS if profile is None else instructions(profile)
        data = {
            "profile_version": request.plan.profile_version,
            "schema_version": request.plan.schema_version,
            "chunk_id": request.chunk.id,
            "blocks": [
                asdict(block)
                for block in request.chunk.blocks
            ],
        }
        options = {}
        if self.settings.reasoning_effort is not None:
            options["reasoning"] = {"effort": self.settings.reasoning_effort}
        try:
            response = self._client.responses.create(
                model=self.settings.deployment,
                instructions=prompt,
                input=[{"role": "user", "content": json.dumps(data, allow_nan=False)}],
                text={"format": {
                    "type": "json_schema", "name": "financial_metrics" if profile is None else "extracted_records",
                    "strict": True, "schema": schema,
                }},
                store=False,
                max_output_tokens=self.settings.max_output_tokens,
                **options,
            )
        except APITimeoutError:
            raise ModelFailure(FailureCode.MODEL_TIMEOUT) from None
        except APIConnectionError:
            raise ProviderOutcomeUnknown() from None
        except APIStatusError as error:
            if error.status_code in (400, 401, 403, 404, 405, 413, 415, 422, 429):
                logging.getLogger(__name__).warning(
                    "provider_request_rejected status=%d category=%s",
                    error.status_code, _rejection_category(error.body),
                )
                raise ModelFailure(FailureCode.MODEL_REJECTED) from None
            raise ProviderOutcomeUnknown() from None
        input_tokens = getattr(response.usage, "input_tokens", None)
        output_tokens = getattr(response.usage, "output_tokens", None)
        usage = (
            None if input_tokens is None or output_tokens is None
            else TokenUsage(input_tokens, output_tokens)
        )
        return ModelResponse(_payload(response), usage)


@contextmanager
def open_foundry_model(
    settings: FoundrySettings, credential: TokenCredential,
    *, transport: httpx.BaseTransport | None = None,
) -> Iterator[FoundryModel]:
    """Own SDK/HTTP resources, but not the caller's credential. No key authentication."""
    with AIProjectClient(
        endpoint=settings.project_endpoint, credential=credential, logging_enable=False,
    ) as project:
        with httpx.Client(
            transport=transport, follow_redirects=False, trust_env=False, timeout=settings.timeout,
        ) as http:
            with project.get_openai_client(
                http_client=http, max_retries=0, timeout=settings.timeout,
            ) as client:
                yield FoundryModel(settings, client)
