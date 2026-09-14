from dataclasses import replace
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

from information_extraction import (
    Execution, FailureCode, ModelFailure, SQLiteStore,
)
from information_extraction.sample import synthetic_plan
from tests.test_foundry_model import AZURE_AVAILABLE, provider_response


class ModelSmokeTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(".test-data") / uuid.uuid4().hex
        self.directory.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.directory)
        self.ledger = self.directory / "smoke.sqlite3"

    def cli(self, *args):
        environment = {
            key: value for key, value in os.environ.items()
            if key not in ("FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_MODEL_DEPLOYMENT")
        }
        result = subprocess.run(
            [sys.executable, str(Path("scripts") / "model_smoke.py"), "--ledger", str(self.ledger),
             "--job-id", "job-1", *args],
            capture_output=True, text=True, env=environment, check=False,
        )
        self.assertEqual(result.stderr, "")
        return result.returncode, json.loads(result.stdout)

    def test_inspect_needs_no_optional_dependencies_or_identity(self):
        SQLiteStore(self.ledger).create("job-1", synthetic_plan(), "create-1")
        code, result = self.cli("--action", "inspect")
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["revision"], 0)
        self.assertEqual(result["attempt_count"], 0)

    def test_invalid_arguments_do_not_echo_resource_values(self):
        code, result = self.cli("--action", "private-endpoint-and-token")
        self.assertEqual(code, 2)
        self.assertEqual(result, {"error": "invalid_arguments"})

    def test_inspect_missing_ledger_does_not_create_it(self):
        code, result = self.cli("--action", "inspect")
        self.assertEqual(code, 2)
        self.assertEqual(result, {"error": "ledger_not_found"})
        self.assertFalse(self.ledger.exists())

    def test_failed_and_unresolved_inspection_exit_nonzero(self):
        class FailingModel:
            binding = "synthetic-model-v1"

            def complete(self, request):
                raise ModelFailure(FailureCode.MODEL_TIMEOUT)

        execution = Execution(SQLiteStore(self.ledger), FailingModel())
        execution.create("job-1", synthetic_plan(), "create-1")
        execution.advance("job-1", 0, "attempt-1")
        code, result = self.cli("--action", "inspect")
        self.assertEqual(code, 1)
        self.assertEqual(result["failure_code"], "model_timeout")
        self.assertEqual(result["usage"]["unknown_attempts"], 1)

        from information_extraction import Action
        SQLiteStore(self.ledger).claim("job-1", 1, "resume-1", Action.RESUME)
        code, result = self.cli("--action", "inspect")
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "in_progress_or_interrupted")

    def test_nonfictional_ledger_is_not_printed(self):
        plan = replace(synthetic_plan(), document_id="private-document")
        SQLiteStore(self.ledger).create("job-1", plan, "create-1")
        code, result = self.cli("--action", "inspect")
        self.assertEqual(code, 2)
        self.assertEqual(result, {"error": "non_synthetic_plan"})

    @unittest.skipUnless(AZURE_AVAILABLE, "optional Azure dependencies not installed")
    def test_create_freezes_model_binding_without_authentication(self):
        code, result = self.cli(
            "--action", "create", "--request-id", "create-1",
            "--project-endpoint", "https://example.invalid/api/projects/placeholder",
            "--deployment", "placeholder-deployment",
        )
        self.assertEqual(code, 0)
        self.assertEqual((result["status"], result["revision"]), ("ready", 0))
        self.assertEqual(result["attempt_count"], 0)
        plan = SQLiteStore(self.ledger).read("job-1").plan
        self.assertTrue(plan.model_binding.startswith("foundry-v1:"))
        self.assertNotIn("example.invalid", json.dumps(result))

    @unittest.skipUnless(AZURE_AVAILABLE, "optional Azure dependencies not installed")
    def test_missing_authentication_does_not_claim_an_attempt(self):
        from azure.core.exceptions import ClientAuthenticationError
        from scripts.model_smoke import main
        from unittest.mock import patch

        from information_extraction.foundry_model import FoundrySettings
        settings = FoundrySettings(
            "https://example.invalid/api/projects/placeholder", "placeholder",
        )
        store = SQLiteStore(self.ledger)
        initial = store.create(
            "job-1", replace(synthetic_plan(), model_binding=settings.binding), "create-1",
        )
        output = io.StringIO()
        with patch("azure.identity.AzureCliCredential") as credential, redirect_stdout(output):
            credential.return_value.__enter__.return_value.get_token.side_effect = (
                ClientAuthenticationError("private authentication details")
            )
            code = main([
                "--ledger", str(self.ledger), "--job-id", "job-1",
                "--project-endpoint", settings.project_endpoint,
                "--deployment", settings.deployment,
                "--action", "advance", "--request-id", "advance-1", "--expected-revision", "0",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue()), {"error": "azure_login_required_or_denied"})
        self.assertEqual(store.read("job-1"), initial)

    @unittest.skipUnless(AZURE_AVAILABLE, "optional Azure dependencies not installed")
    def test_one_step_cli_replay_and_explicit_resume_use_real_sdk_without_network(self):
        import httpx
        from azure.core.credentials import AccessToken
        from scripts.model_smoke import main
        from unittest.mock import patch

        class PlaceholderCredential:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def get_token(self, *scopes, **kwargs):
                return AccessToken("placeholder-not-a-real-token", 4102444800)

        calls = []

        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(429, json={"error": {"message": "private-placeholder"}})
            return httpx.Response(200, json=provider_response(
                '{"records":[{"metric":"revenue","value":120,'
                '"unit":"USD_millions","block_ids":["block-1"]}]}',
            ))

        def invoke(*args):
            output = io.StringIO()
            with redirect_stdout(output):
                code = main([
                    "--ledger", str(self.ledger), "--job-id", "job-1",
                    "--project-endpoint", "https://example.invalid/api/projects/placeholder",
                    "--deployment", "placeholder", *args,
                ])
            return code, json.loads(output.getvalue())

        with httpx.MockTransport(handler) as transport:
            with patch("azure.identity.AzureCliCredential", PlaceholderCredential), patch(
                "httpx.HTTPTransport.handle_request",
                lambda _, request: transport.handle_request(request),
            ):
                self.assertEqual(invoke("--action", "create", "--request-id", "create-1")[0], 0)
                self.assertEqual(calls, [])
                failed = invoke(
                    "--action", "advance", "--request-id", "attempt-1", "--expected-revision", "0",
                )
                self.assertEqual((failed[0], failed[1]["status"]), (1, "failed"))
                replayed = invoke(
                    "--action", "advance", "--request-id", "attempt-1", "--expected-revision", "0",
                )
                self.assertEqual(replayed, failed)
                self.assertEqual(len(calls), 1)
                code, resumed = invoke(
                    "--action", "resume", "--request-id", "resume-1", "--expected-revision", "1",
                )
                self.assertEqual((code, resumed["status"], resumed["revision"]), (0, "ready", 2))
                self.assertEqual(resumed["completed_chunk_count"], 1)
                self.assertEqual(resumed["candidates"][0]["record"]["value"], 120)
                self.assertEqual(len(calls), 2)
                self.assertNotIn("block-3", calls[1].content.decode())
