"""Python 3.13 source entrypoint; start with `python main.py` (Responses/8088)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import ExitStack

from azure.ai.agentserver.responses import (
    CreateResponse,
    ResponseContext,
    ResponsesAgentServerHost,
    ResponsesServerOptions,
    TextResponse,
)
from azure.ai.projects import AIProjectClient
from azure.identity import get_bearer_token_provider
from openai import OpenAI

from probe_agent.config import ConfigurationError, Settings
from probe_agent.credentials import create_credential
from probe_agent.orchestrator import ChatProbeAgent, ProbeAgent, error_answer
from probe_agent.sql_probe import SqlProbe


def create_app(agent: ProbeAgent) -> ResponsesAgentServerHost:
    app = ResponsesAgentServerHost(
        options=ResponsesServerOptions(default_fetch_history_count=1),
        configure_observability=None,
        access_log=None,
    )
    active = asyncio.Lock()

    @app.response_handler
    async def handler(
        request: CreateResponse,
        context: ResponseContext,
        cancellation_signal: asyncio.Event,
    ) -> TextResponse:
        if cancellation_signal.is_set():
            return TextResponse(context, request, text=error_answer("cancelled", "The validation request was cancelled."))
        if active.locked():
            return TextResponse(context, request, text=error_answer("busy", "One validation probe is already active. Retry after it completes."))
        async with active:
            try:
                user_input = await context.get_input_text(resolve_references=False)
                answer = await asyncio.to_thread(agent.answer, user_input)
            except Exception:
                answer = error_answer("runtime_failed", "The validation request failed; raw exception details are omitted.")
        return TextResponse(context, request, text=answer)

    return app


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from None
    # Do not enable SDK wire/debug logging: it may contain credentials or SQL errors.
    for name in ("azure", "openai", "httpx", "httpcore", "pytds"):
        logger = logging.getLogger(name)
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
        logger.setLevel(logging.CRITICAL + 1)
    credential = create_credential(settings)
    try:
        with ExitStack() as clients:
            if settings.model_endpoint:
                openai = clients.enter_context(OpenAI(
                    base_url=settings.model_endpoint,
                    api_key=get_bearer_token_provider(credential, "https://ai.azure.com/.default"),
                    timeout=60.0,
                    max_retries=0,
                ))
            else:
                project = clients.enter_context(AIProjectClient(
                    endpoint=settings.project_endpoint,
                    credential=credential,
                    user_agent="business-performance-sql-probe-v1",
                ))
                openai = clients.enter_context(project.get_openai_client(timeout=60.0, max_retries=0))
            probe = SqlProbe(settings, credential)
            agent = (
                ChatProbeAgent(openai.chat.completions, settings.model, probe.run)
                if settings.model_api == "chat_completions"
                else ProbeAgent(openai.responses, settings.model, probe.run)
            )
            create_app(agent).run()
    finally:
        credential.close()


if __name__ == "__main__":
    main()
