"""Strict configuration for the isolated Azure public-cloud SQL pilot."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit
from uuid import UUID


class ConfigurationError(ValueError):
    """Configuration is absent or unsafe; messages never echo supplied values."""


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "")
    if not value or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ConfigurationError(f"{key} must be a nonempty value without control characters.")
    return value


def _timeout(env: Mapping[str, str], key: str) -> int:
    value = env.get(key, "15")
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 30:
        raise ConfigurationError(f"{key} must be an integer from 1 to 30.")
    return int(value)


@dataclass(frozen=True)
class Settings:
    server: str
    database: str
    project_endpoint: str
    model: str
    query_timeout: int = 15
    connect_timeout: int = 15
    local_development: bool = False
    client_id: str | None = None
    model_endpoint: str | None = None
    model_api: str = "responses"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        server = _required(env, "AZURE_SQL_SERVER").lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.database\.windows\.net", server):
            raise ConfigurationError("AZURE_SQL_SERVER must be the ordinary Azure SQL FQDN, never an IP or privatelink alias.")
        database = _required(env, "AZURE_SQL_DATABASE")
        if len(database) > 128:
            raise ConfigurationError("AZURE_SQL_DATABASE must be at most 128 characters.")
        endpoint = _required(env, "FOUNDRY_PROJECT_ENDPOINT")
        try:
            parsed = urlsplit(endpoint)
            valid_endpoint = (
                parsed.scheme == "https"
                and parsed.hostname is not None
                and parsed.hostname.endswith(".services.ai.azure.com")
                and parsed.port in (None, 443)
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment
                and re.fullmatch(r"/api/projects/[A-Za-z0-9._-]+/?", parsed.path)
            )
        except ValueError:
            valid_endpoint = False
        if not valid_endpoint:
            raise ConfigurationError("FOUNDRY_PROJECT_ENDPOINT must be an HTTPS Azure AI project endpoint.")
        model = _required(env, "AZURE_AI_MODEL_DEPLOYMENT_NAME")
        if len(model) > 128:
            raise ConfigurationError("AZURE_AI_MODEL_DEPLOYMENT_NAME must be at most 128 characters.")
        model_endpoint = env.get("AZURE_AI_MODEL_ENDPOINT") or None
        if model_endpoint is not None:
            model_endpoint = _required(env, "AZURE_AI_MODEL_ENDPOINT")
            try:
                parsed_model = urlsplit(model_endpoint)
                valid_model_endpoint = (
                    parsed_model.scheme == "https"
                    and re.fullmatch(
                        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.(?:openai|services\.ai)\.azure\.com",
                        parsed_model.hostname or "",
                    )
                    and parsed_model.port in (None, 443)
                    and parsed_model.username is None
                    and parsed_model.password is None
                    and "?" not in model_endpoint
                    and "#" not in model_endpoint
                    and "\x7f" not in model_endpoint
                    and parsed_model.path in ("/openai/v1", "/openai/v1/")
                )
            except ValueError:
                valid_model_endpoint = False
            if not valid_model_endpoint:
                raise ConfigurationError("AZURE_AI_MODEL_ENDPOINT must be an HTTPS Azure account-level /openai/v1 endpoint.")
        # Empty manifest substitutions preserve the original Responses route.
        model_api = env.get("AZURE_AI_MODEL_API") or "responses"
        if model_api not in ("responses", "chat_completions"):
            raise ConfigurationError("AZURE_AI_MODEL_API must be responses or chat_completions.")
        local = env.get("APP_LOCAL_DEVELOPMENT", "false").lower()
        if local not in ("true", "false"):
            raise ConfigurationError("APP_LOCAL_DEVELOPMENT must be true or false.")
        client_id = env.get("AZURE_CLIENT_ID") or None
        if client_id:
            try:
                UUID(client_id)
            except ValueError:
                raise ConfigurationError("AZURE_CLIENT_ID must be a UUID.") from None
        return cls(
            server=server,
            database=database,
            project_endpoint=endpoint,
            model=model,
            query_timeout=_timeout(env, "AZURE_SQL_QUERY_TIMEOUT_SECONDS"),
            connect_timeout=_timeout(env, "AZURE_SQL_CONNECT_TIMEOUT_SECONDS"),
            local_development=local == "true",
            client_id=client_id,
            model_endpoint=model_endpoint,
            model_api=model_api,
        )
