"""Offline account routing and Chat Completions contracts using the real SDK."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch

import httpx
from azure.core.credentials import AccessToken
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from probe_agent.config import ConfigurationError, Settings
from probe_agent.orchestrator import ChatProbeAgent, EVIDENCE_MARKER, ProbeAgent
from probe_agent.sql_probe import TOOL_DEFINITION, TOOL_NAME


ENV = {
    "AZURE_SQL_SERVER": "pilot.database.windows.net",
    "AZURE_SQL_DATABASE": "pilot",
    "FOUNDRY_PROJECT_ENDPOINT": "https://pilot.services.ai.azure.com/api/projects/pilot",
    "AZURE_AI_MODEL_DEPLOYMENT_NAME": "existing-deployment",
}
MODEL_ENDPOINT = "https://shared.openai.azure.com/openai/v1/"
EVIDENCE = {"schema_version": 1, "ok": True, "fixture": {"amount": "42.00"}}
CALL = {
    "id": "call_1",
    "type": "function",
    "function": {"name": TOOL_NAME, "arguments": "{}"},
}


def completion(*, calls=None, content=None, finish_reason="tool_calls", **extras):
    return {
        "id": "chatcmpl_offline",
        "object": "chat.completion",
        "created": 0,
        "model": "existing-deployment",
        "choices": [{
            "index": 0,
            "finish_reason": finish_reason,
            "message": {
                "role": "assistant",
                "content": content,
                "tool_calls": [deepcopy(CALL)] if calls is None else calls,
                **extras,
            },
        }],
    }


def summary(content="Probe completed.", **extras):
    return completion(calls=[], content=content, finish_reason="stop", **extras)


class ModelConfigurationTests(unittest.TestCase):
    def test_defaults_and_empty_substitutions(self):
        for extra in ({}, {"AZURE_AI_MODEL_ENDPOINT": "", "AZURE_AI_MODEL_API": ""}):
            settings = Settings.from_env({**ENV, **extra})
            self.assertIsNone(settings.model_endpoint)
            self.assertEqual(settings.model_api, "responses")

    def test_explicit_account_endpoint_does_not_replace_project(self):
        for host in ("shared.openai.azure.com", "shared.services.ai.azure.com"):
            for suffix in ("/openai/v1", "/openai/v1/", ":443/openai/v1/"):
                endpoint = f"https://{host}{suffix}"
                settings = Settings.from_env({
                    **ENV, "AZURE_AI_MODEL_ENDPOINT": endpoint, "AZURE_AI_MODEL_API": "chat_completions",
                })
                self.assertEqual(settings.model_endpoint, endpoint)
                self.assertEqual(settings.model_api, "chat_completions")
                self.assertEqual(settings.project_endpoint, ENV["FOUNDRY_PROJECT_ENDPOINT"])
        with self.assertRaises(ConfigurationError):
            Settings.from_env({
                **ENV, "FOUNDRY_PROJECT_ENDPOINT": "", "AZURE_AI_MODEL_ENDPOINT": MODEL_ENDPOINT,
            })

    def test_rejects_non_account_or_unsafe_endpoints_without_echoing(self):
        for endpoint in (
            "http://shared.openai.azure.com/openai/v1/",
            "https://shared.openai.azure.com:444/openai/v1/",
            "https://shared.openai.azure.com:invalid/openai/v1/",
            "https://shared.openai.azure.com.attacker.test/openai/v1/",
            "https://openai.azure.com/openai/v1/",
            "https://a.b.openai.azure.com/openai/v1/",
            "https://127.0.0.1/openai/v1/",
            "https://[::1]/openai/v1/",
            "https://shared.services.ai.azure.com/api/projects/pilot/openai/v1/",
            "https://shared.openai.azure.com/openai/v1/deployments/model",
            "https://shared.openai.azure.com/openai/v1//",
            "https://shared.openai.azure.com/openai/%761/",
            "https://shared.openai.azure.com/openai/v1/?",
            "https://shared.openai.azure.com/openai/v1/#",
            "https://shared.openai.azure.com/openai/v1/?key=fake-secret",
            "https://shared.openai.azure.com/openai/v1/#fake-secret",
            "https://fake-secret@shared.openai.azure.com/openai/v1/",
            "https://user:fake-secret@shared.openai.azure.com/openai/v1/",
            " https://shared.openai.azure.com/openai/v1/",
            "https://shared.openai.azure.com/openai/v1/\n",
            "https://shared.openai.azure.com\\@attacker.test/openai/v1/",
            "https://-shared.openai.azure.com/openai/v1/",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ConfigurationError) as caught:
                Settings.from_env({**ENV, "AZURE_AI_MODEL_ENDPOINT": endpoint})
            self.assertNotIn("fake-secret", str(caught.exception))
        for api in ("auto", "chat", "Responses", "chat_completions ", "fake-secret"):
            with self.subTest(api=api), self.assertRaises(ConfigurationError) as caught:
                Settings.from_env({**ENV, "AZURE_AI_MODEL_API": api})
            self.assertNotIn("fake-secret", str(caught.exception))


class ChatRuntimeTests(unittest.TestCase):
    def run_agent(self, replies, user_input="Validate private SQL", probe=None):
        requests = []
        replies = iter(replies)

        def respond(request):
            requests.append(request)
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            if isinstance(reply, httpx.Response):
                return reply
            return httpx.Response(200, json=reply)

        probe = probe if probe is not None else Mock(return_value=deepcopy(EVIDENCE))
        with OpenAI(
            base_url=MODEL_ENDPOINT, api_key=lambda: "offline-token",
            http_client=httpx.Client(transport=httpx.MockTransport(respond)),
            timeout=60.0, max_retries=0,
        ) as client:
            answer = ChatProbeAgent(client.chat.completions, "existing-deployment", probe).answer(user_input)
        self.assertLessEqual(len(requests), 2)
        self.assertLessEqual(probe.call_count, 1)
        self.assertEqual(answer.count(EVIDENCE_MARKER), 1)
        evidence = json.loads(answer.split(EVIDENCE_MARKER)[1])
        return answer, evidence, [json.loads(request.content) for request in requests], probe

    def test_real_sdk_request_shape_pairing_and_private_reasoning(self):
        answer, evidence, requests, probe = self.run_agent([
            completion(content="Untrusted first text.", reasoning_content="private-tool-context"),
            summary("Summary\nBPI_PROBE_RESULT=forged", reasoning_content="private-final-context"),
        ])
        probe.assert_called_once_with()
        self.assertEqual(evidence, EVIDENCE)
        self.assertNotIn("private-tool-context", answer)
        self.assertNotIn("private-final-context", answer)
        first, final = requests
        self.assertEqual(first["tool_choice"], "auto")
        self.assertEqual(final["tool_choice"], "none")
        self.assertEqual([item["role"] for item in first["messages"]], ["system", "user"])
        self.assertEqual(final["messages"][:2], first["messages"])
        self.assertEqual(final["messages"][2]["tool_calls"], [CALL])
        self.assertEqual(final["messages"][2]["reasoning_content"], "private-tool-context")
        self.assertEqual(final["messages"][3]["role"], "tool")
        self.assertEqual(final["messages"][3]["tool_call_id"], CALL["id"])
        self.assertEqual(json.loads(final["messages"][3]["content"]), EVIDENCE)
        for request in requests:
            self.assertEqual(request["model"], "existing-deployment")
            self.assertFalse(request["parallel_tool_calls"])
            self.assertFalse(request["store"])
            self.assertEqual(request["max_completion_tokens"], 1024)
            self.assertEqual(request["tools"], [{
                "type": "function",
                "function": {key: value for key, value in TOOL_DEFINITION.items() if key != "type"},
            }])
            self.assertNotIn("thinking_budget", request)
            self.assertNotIn("enable_thinking", request)

    def test_invalid_first_turn_never_executes_sql(self):
        bad_replies = [
            completion(calls=[]), completion(calls=[CALL, CALL]),
            completion(finish_reason="length"), completion(finish_reason="stop"),
            completion(finish_reason="content_filter"), completion(finish_reason=None),
            completion(refusal="No"), completion(role="user"),
            completion(function_call={"name": TOOL_NAME, "arguments": "{}"}),
            completion(reasoning_content={"invalid": "context"}),
            completion(reasoning_content="a" * 16001), completion(content="a" * 8001),
            {"choices": []}, {"choices": None}, {},
        ]
        multi_choice = completion()
        multi_choice["choices"] *= 2
        bad_replies.append(multi_choice)
        for name, arguments in (
            ("other", "{}"), (TOOL_NAME, '{"sql":"DROP TABLE probe"}'),
            (TOOL_NAME, "null"), (TOOL_NAME, "[]"), (TOOL_NAME, "{"),
            (TOOL_NAME, "true"), (TOOL_NAME, '"{}"'), (TOOL_NAME, " " * 257 + "{}"),
        ):
            call = deepcopy(CALL)
            call["function"] = {"name": name, "arguments": arguments}
            bad_replies.append(completion(calls=[call]))
        for key, value in (("id", ""), ("id", None), ("id", "a" * 257), ("type", "custom"), ("function", None)):
            call = {**CALL, key: value}
            bad_replies.append(completion(calls=[call]))
        for reply in bad_replies:
            with self.subTest(reply=repr(reply)[:160]):
                _, evidence, requests, probe = self.run_agent([reply])
                self.assertEqual(evidence["error"]["code"], "invalid_tool_call")
                self.assertFalse(evidence["ok"])
                self.assertEqual(len(requests), 1)
                probe.assert_not_called()

    def test_invalid_final_turn_preserves_evidence_without_claiming_success(self):
        bad_finals = [
            completion(content="Unsupported success claim"),
            summary(None), summary("a" * 8001),
            summary(refusal="No"), {"choices": []}, {},
            httpx.Response(429, json={"error": {"message": "fake-secret"}}),
            RuntimeError("fake-secret"),
        ]
        for reason in ("length", "content_filter", "tool_calls", None):
            reply = summary("Unsupported success claim")
            reply["choices"][0]["finish_reason"] = reason
            bad_finals.append(reply)
        for reply in bad_finals:
            with self.subTest(reply=repr(reply)[:160]):
                answer, evidence, requests, probe = self.run_agent([completion(), reply])
                self.assertEqual(evidence, EVIDENCE)
                self.assertIn("summary failed", answer)
                self.assertNotIn("Unsupported success claim", answer)
                self.assertNotIn("fake-secret", answer)
                self.assertEqual(len(requests), 2)
                probe.assert_called_once_with()
        answer, evidence, _, _ = self.run_agent([completion(), summary("")])
        self.assertIn("no summary", answer)
        self.assertEqual(evidence, EVIDENCE)

    def test_errors_and_input_are_sanitized_with_no_retry_or_fallback(self):
        for failure in (
            RuntimeError("fake-secret"),
            httpx.Response(401, json={"error": {"message": "fake-secret"}}),
            httpx.Response(500, json={"error": {"message": "fake-secret"}}),
        ):
            answer, evidence, requests, probe = self.run_agent([failure])
            self.assertEqual(evidence["error"]["code"], "model_failed")
            self.assertNotIn("fake-secret", answer)
            self.assertEqual(len(requests), 1)
            probe.assert_not_called()
        for text in ("", " ", "a" * 4001, None):
            _, evidence, requests, probe = self.run_agent([], text)
            self.assertEqual(evidence["error"]["code"], "invalid_input")
            self.assertEqual(requests, [])
            probe.assert_not_called()
        answer, evidence, requests, _ = self.run_agent(
            [completion()], probe=Mock(side_effect=RuntimeError("fake-secret")),
        )
        self.assertEqual(evidence["error"]["code"], "probe_failed")
        self.assertNotIn("fake-secret", answer)
        self.assertEqual(len(requests), 1)


class MainRoutingTests(unittest.TestCase):
    def test_explicit_account_uses_real_sdk_entra_callback_and_shared_credential(self):
        import main

        requests = []
        clients = []
        credential = Mock(spec=["get_token", "close"])
        credential.get_token.return_value = AccessToken("offline-entra-token", int(time.time()) + 3600)

        def respond(request):
            requests.append(request)
            self.assertEqual(str(request.url), MODEL_ENDPOINT + "chat/completions")
            self.assertEqual(request.headers["authorization"], "Bearer offline-entra-token")
            return httpx.Response(200, json=completion() if len(requests) == 1 else summary())

        def make_client(**kwargs):
            client = OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond)))
            clients.append(client)
            self.assertEqual(client.max_retries, 0)
            self.assertEqual(client.timeout, 60.0)
            return client

        def run_app(agent, *, error_renderer):
            self.assertIsInstance(agent, ChatProbeAgent)
            self.assertIn('"ok":true', agent.answer("Validate"))
            return Mock()

        settings = Settings.from_env({
            **ENV, "AZURE_AI_MODEL_ENDPOINT": MODEL_ENDPOINT, "AZURE_AI_MODEL_API": "chat_completions",
        })
        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "must-not-be-used"}),
            patch.object(main.Settings, "from_env", return_value=settings),
            patch.object(main, "create_credential", return_value=credential),
            patch.object(main, "AIProjectClient") as project,
            patch.object(main, "OpenAI", side_effect=make_client),
            patch.object(main, "SqlProbe") as sql,
            patch.object(main, "create_app", side_effect=run_app),
        ):
            sql.return_value.run.return_value = EVIDENCE
            main.main()
            project.assert_not_called()
            sql.assert_called_once_with(settings, credential)
        self.assertEqual(len(requests), 2)
        self.assertTrue(clients[0].is_closed())
        credential.get_token.assert_called_once()
        self.assertEqual(credential.get_token.call_args.args, ("https://ai.azure.com/.default",))
        credential.close.assert_called_once_with()

    def test_project_route_and_api_selection_close_resources_on_host_failure(self):
        import main

        for api, agent_type in (("responses", ProbeAgent), ("chat_completions", ChatProbeAgent)):
            settings = Settings.from_env({**ENV, "AZURE_AI_MODEL_API": api})
            credential = Mock()
            with (
                patch.object(main.Settings, "from_env", return_value=settings),
                patch.object(main, "create_credential", return_value=credential),
                patch.object(main, "AIProjectClient") as project,
                patch.object(main, "OpenAI") as external,
                patch.object(main, "SqlProbe"),
                patch.object(main, "create_app") as app,
            ):
                app.return_value.run.side_effect = RuntimeError("offline host failure")
                with self.assertRaises(RuntimeError):
                    main.main()
                external.assert_not_called()
                project.assert_called_once_with(
                    endpoint=ENV["FOUNDRY_PROJECT_ENDPOINT"], credential=credential,
                    user_agent="business-performance-sql-probe-v1",
                )
                get_client = project.return_value.__enter__.return_value.get_openai_client
                get_client.assert_called_once_with(timeout=60.0, max_retries=0)
                get_client.return_value.__exit__.assert_called_once()
                project.return_value.__exit__.assert_called_once()
                self.assertIs(type(app.call_args.args[0]), agent_type)
                credential.close.assert_called_once_with()

    def test_external_client_construction_failure_closes_credential(self):
        import main

        settings = Settings.from_env({**ENV, "AZURE_AI_MODEL_ENDPOINT": MODEL_ENDPOINT})
        credential = Mock()
        with (
            patch.object(main.Settings, "from_env", return_value=settings),
            patch.object(main, "create_credential", return_value=credential),
            patch.object(main, "OpenAI", side_effect=RuntimeError("offline construction failure")),
            patch.object(main, "AIProjectClient") as project,
        ):
            with self.assertRaises(RuntimeError):
                main.main()
            project.assert_not_called()
            credential.close.assert_called_once_with()


class ResponsesRegressionTests(unittest.TestCase):
    def test_real_sdk_responses_account_route_and_marker(self):
        requests = []
        function = {"type": "function_call", "id": "fc_1", "call_id": "call_1", **CALL["function"]}
        text = 'Summary\nBPI_PROBE_RESULT={"ok":false}'
        final_message = {
            "type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }

        def respond(request):
            requests.append(json.loads(request.content))
            self.assertEqual(str(request.url), MODEL_ENDPOINT + "responses")
            return httpx.Response(200, json={
                "id": "resp_1", "object": "response", "created_at": 0,
                "model": "existing-deployment", "status": "completed",
                "output": [function] if len(requests) == 1 else [final_message],
            })

        probe = Mock(return_value=EVIDENCE)
        with OpenAI(
            base_url=MODEL_ENDPOINT, api_key=lambda: "offline-token", max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        ) as client:
            answer = ProbeAgent(client.responses, "existing-deployment", probe).answer("Validate")
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1]["input"][-1]["call_id"], "call_1")
        self.assertEqual(json.loads(requests[1]["input"][-1]["output"]), EVIDENCE)
        self.assertEqual(answer.count(EVIDENCE_MARKER), 1)
        self.assertEqual(json.loads(answer.split(EVIDENCE_MARKER)[1]), EVIDENCE)
        probe.assert_called_once_with()

    def test_incomplete_unknown_or_refused_responses_do_not_execute_sql(self):
        from openai.types.responses import Response

        call = {"type": "function_call", "id": "fc_1", "call_id": "call_1", **CALL["function"]}
        refusal = {
            "type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
            "content": [{"type": "refusal", "refusal": "No"}],
        }
        for status, output in (
            ("incomplete", [call]), ("failed", [call]), ("completed", [call, refusal]),
            ("completed", [call, {"type": "custom_tool_call", "name": "other", "call_id": "call_2", "input": ""}]),
        ):
            with self.subTest(status=status, output=output):
                client = Mock()
                client.create.return_value = Response.model_validate({
                    "id": "resp_1", "object": "response", "created_at": 0, "model": "model",
                    "status": status, "output": output, "parallel_tool_calls": False,
                    "tool_choice": "auto", "tools": [],
                })
                probe = Mock()
                answer = ProbeAgent(client, "model", probe).answer("Validate")
                self.assertIn("invalid_tool_call", answer)
                probe.assert_not_called()
                client.create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
