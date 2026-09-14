from dataclasses import replace
import json
from pathlib import Path
import shutil
import unittest
import uuid

from information_extraction import Execution, FailureCode, SQLiteStore, Status
from information_extraction.contracts import (
    Blocked, Conflict, ExecutionError, InvalidInput, ModelRequest, TokenUsage,
)
from information_extraction.sample import synthetic_plan

try:
    import httpx
    from openai import OpenAI
    from azure.ai.projects import AIProjectClient
except ImportError:
    AZURE_AVAILABLE = False
else:
    AZURE_AVAILABLE = True
    from information_extraction.foundry_model import FoundryModel, FoundrySettings


def provider_response(text='{"records":[]}', **overrides):
    return {
        "id": "resp-placeholder", "object": "response", "created_at": 0,
        "model": "observed-placeholder-version", "status": "completed",
        "output": [{
            "id": "msg-placeholder", "type": "message", "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }],
        "usage": {"input_tokens": 17, "output_tokens": 9, "total_tokens": 26},
        **overrides,
    }


@unittest.skipUnless(AZURE_AVAILABLE, "optional Azure dependencies not installed")
class FoundryModelTests(unittest.TestCase):
    def adapter(self, handler, **settings):
        http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
        self.addCleanup(http.close)
        client = OpenAI(
            base_url="https://example.invalid/api/projects/placeholder/openai/v1",
            api_key="placeholder-not-a-real-token", max_retries=2, http_client=http,
        )
        self.addCleanup(client.close)
        return FoundryModel(FoundrySettings(
            project_endpoint="https://example.invalid/api/projects/placeholder",
            deployment="placeholder-deployment", **settings,
        ), client)

    def request(self, model):
        plan = replace(synthetic_plan(), model_binding=model.binding)
        return ModelRequest("job-1", "attempt-1", 0, plan.chunks[0], plan)

    def execution(self, model):
        directory = Path(".test-data") / uuid.uuid4().hex
        directory.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, directory)
        execution = Execution(SQLiteStore(directory / "ledger.sqlite3"), model)
        execution.create("job-1", self.request(model).plan, "create-1")
        return execution

    def test_request_sends_only_current_chunk_with_strict_schema_and_no_storage(self):
        captured = []

        def handler(request):
            captured.append(request)
            return httpx.Response(200, json=provider_response())

        model = self.adapter(handler, reasoning_effort="low", max_output_tokens=1500)
        response = model.complete(self.request(model))
        self.assertEqual(response.payload, {"records": []})
        self.assertEqual(response.usage, TokenUsage(17, 9))
        self.assertEqual(len(captured), 1)
        body = json.loads(captured[0].content)
        self.assertEqual(body["model"], "placeholder-deployment")
        self.assertFalse(body["store"])
        self.assertNotIn("tools", body)
        self.assertEqual(body["max_output_tokens"], 1500)
        self.assertEqual(body["reasoning"], {"effort": "low"})
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertTrue(body["text"]["format"]["strict"])
        record = body["text"]["format"]["schema"]["properties"]["records"]["items"]
        self.assertFalse(record["additionalProperties"])
        self.assertEqual(set(record["properties"]), {"metric", "value", "unit", "block_ids"})
        data = json.loads(body["input"][0]["content"])
        self.assertEqual([block["id"] for block in data["blocks"]], ["block-1", "block-2"])
        self.assertNotIn("block-3", captured[0].content.decode())
        self.assertNotIn("job-1", captured[0].content.decode())
        self.assertEqual(captured[0].headers["x-stainless-retry-count"], "0")

    def test_bad_outputs_commit_validation_failure_without_losing_usage(self):
        cases = [
            provider_response("not JSON"),
            provider_response('{"records":[],"records":[]}'),
            provider_response('{"records":[{"value":NaN}]}'),
            provider_response('{"records":[{"value":Infinity}]}'),
            provider_response('{"records":[{"value":1e999}]}'),
            provider_response('{"records":[{"value":' + "9" * 5000 + '}]}'),
            provider_response('{"records":[{"value":1,"value":2}]}'),
            provider_response('{"records":[]} trailing'),
            provider_response("[]"),
            provider_response(status="incomplete"),
            provider_response(status="failed"),
            provider_response(output=[{
                "id": "msg-placeholder", "type": "message", "role": "assistant",
                "status": "completed",
                "content": [{"type": "refusal", "refusal": "placeholder refusal"}],
            }]),
            provider_response(output=[]),
            provider_response(output=[{}]),
            provider_response(output=[{
                "id": "msg-placeholder", "type": "message", "role": "assistant",
                "status": "completed", "content": [{}],
            }]),
        ]
        for body in cases:
            with self.subTest(body=body):
                model = self.adapter(lambda _: httpx.Response(200, json=body))
                result = self.execution(model).advance("job-1", 0, "attempt-1")
                self.assertEqual(result.status, Status.FAILED)
                self.assertEqual(result.attempts[0].failure_code, FailureCode.MALFORMED_OUTPUT)
                self.assertEqual(result.attempts[0].usage, TokenUsage(17, 9))
                self.assertEqual(result.candidates, ())

    def test_unknown_usage_is_not_assumed_zero(self):
        for usage in (None, {}, {"input_tokens": 17}):
            with self.subTest(usage=usage):
                model = self.adapter(lambda _: httpx.Response(200, json=provider_response(usage=usage)))
                self.assertIsNone(model.complete(self.request(model)).usage)

    def test_unknown_python_error_propagates_without_resolving_claim(self):
        execution = self.execution(self.adapter(lambda _: httpx.Response(200, json=provider_response())))
        from unittest.mock import patch
        with patch("openai.resources.responses.Responses.create", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                execution.advance("job-1", 0, "attempt-1")
        self.assertEqual(execution.read("job-1").status, Status.IN_PROGRESS)

    def test_timeout_and_explicit_rejections_commit_once_without_sdk_retries(self):
        for outcome in ("timeout", 400, 401, 403, 404, 422, 429):
            with self.subTest(outcome=outcome):
                calls = []

                def handler(request):
                    calls.append(request)
                    if outcome == "timeout":
                        raise httpx.ReadTimeout("private-provider-body", request=request)
                    return httpx.Response(outcome, json={"error": {"message": "private-provider-body"}})

                model = self.adapter(handler)
                execution = self.execution(model)
                result = execution.advance("job-1", 0, "attempt-1")
                self.assertEqual(result.status, Status.FAILED)
                self.assertEqual(
                    result.attempts[0].failure_code,
                    FailureCode.MODEL_TIMEOUT if outcome == "timeout" else FailureCode.MODEL_REJECTED,
                )
                self.assertIsNone(result.attempts[0].usage)
                self.assertEqual(execution.advance("job-1", 0, "attempt-1"), result)
                self.assertEqual(len(calls), 1)

    def test_ambiguous_transport_outcomes_remain_unresolved_and_safe(self):
        for outcome in ("connection", 408, 500, 503, 302):
            with self.subTest(outcome=outcome):
                calls = []

                def handler(request):
                    calls.append(request)
                    if outcome == "connection":
                        raise httpx.ConnectError("private-provider-body", request=request)
                    return httpx.Response(
                        outcome, json={"error": {"message": "private-provider-body"}},
                        headers={"location": "https://example.invalid/redirect"},
                    )

                model = self.adapter(handler)
                execution = self.execution(model)
                with self.assertRaises(ExecutionError) as error:
                    execution.advance("job-1", 0, "attempt-1")
                self.assertEqual(str(error.exception), "provider_outcome_unknown")
                self.assertTrue(error.exception.__suppress_context__)
                result = execution.read("job-1")
                self.assertEqual((result.status, result.revision), (Status.IN_PROGRESS, 0))
                self.assertEqual(result.attempts, ())
                with self.assertRaises(Blocked):
                    execution.advance("job-1", 0, "attempt-2")
                self.assertEqual(len(calls), 1)

    def test_settings_reject_unsafe_values_and_binding_freezes_request_identity(self):
        settings = FoundrySettings("https://example.invalid/api/projects/placeholder", "placeholder")
        self.assertEqual(settings.binding, replace(settings).binding)
        self.assertNotIn("example.invalid", settings.binding)
        self.assertNotIn("example.invalid", repr(settings))
        for changes in (
            {"deployment": "different"}, {"profile_version": "different"},
            {"project_endpoint": "https://example.invalid/api/projects/different"},
            {"max_output_tokens": 1024}, {"timeout": 10}, {"reasoning_effort": "low"},
        ):
            with self.subTest(changes=changes):
                self.assertNotEqual(settings.binding, replace(settings, **changes).binding)
        for changes in (
            {"max_output_tokens": True}, {"max_output_tokens": 0},
            {"max_output_tokens": 32769}, {"max_output_tokens": 10.5},
            {"timeout": True}, {"timeout": 0}, {"timeout": float("inf")},
            {"timeout": float("nan")}, {"reasoning_effort": "unsupported"},
            {"deployment": ""}, {"deployment": " secret\n"},
            {"project_endpoint": "http://example.invalid"},
            {"project_endpoint": "https://user:secret@example.invalid/project"},
            {"project_endpoint": "https://example.invalid/project?token=secret"},
            {"project_endpoint": "https://example.invalid/project#secret"},
            {"profile_version": "bad profile"},
        ):
            with self.subTest(changes=changes), self.assertRaises(InvalidInput):
                replace(settings, **changes)

    def test_profile_mismatch_is_rejected_before_inference(self):
        calls = []
        model = self.adapter(lambda request: calls.append(request), profile_version="other-profile")
        with self.assertRaises(Conflict):
            model.complete(self.request(model))
        self.assertEqual(calls, [])

    def test_factory_uses_supplied_credential_and_closes_without_following_redirects(self):
        from azure.core.credentials import AccessToken
        from information_extraction.foundry_model import open_foundry_model

        class PlaceholderCredential:
            def __init__(self):
                self.scopes = []

            def get_token(self, *scopes, **kwargs):
                self.scopes.append(scopes)
                return AccessToken("placeholder-not-a-real-token", 4102444800)

        calls = []

        class Transport(httpx.MockTransport):
            closed = False

            def close(self):
                self.closed = True
                super().close()

        def handler(request):
            calls.append(request)
            return httpx.Response(302, headers={"location": "https://example.invalid/other"})

        transport = Transport(handler)
        credential = PlaceholderCredential()
        settings = FoundrySettings("https://example.invalid/api/projects/placeholder", "placeholder")
        with self.assertRaises(ExecutionError):
            with open_foundry_model(settings, credential, transport=transport) as model:
                model.complete(self.request(model))
        self.assertTrue(transport.closed)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].url.path, "/api/projects/placeholder/openai/v1/responses")
        self.assertEqual(credential.scopes, [("https://ai.azure.com/.default",)])
        self.assertEqual(calls[0].headers["authorization"], "Bearer placeholder-not-a-real-token")
