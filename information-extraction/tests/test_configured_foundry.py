from dataclasses import asdict, replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from information_extraction import (
    ConfiguredPlan, Conflict, Execution, InvalidInput, ModelRequest, SQLiteStore, Status,
)
from information_extraction.sample import synthetic_plan
from information_extraction.schema import output_schema
from tests.test_configured_execution import payload, plan, profile
from tests import test_foundry_model as foundry

AZURE_AVAILABLE = foundry.AZURE_AVAILABLE
provider_response = foundry.provider_response

if AZURE_AVAILABLE:
    import httpx
    from information_extraction.foundry_model import FoundrySettings


@unittest.skipUnless(AZURE_AVAILABLE, "optional Azure dependencies not installed")
class ConfiguredFoundryTests(unittest.TestCase):
    adapter = foundry.FoundryModelTests.adapter

    def test_generic_profile_uses_same_adapter_with_field_evidence_and_speaker_data(self):
        captured = []

        def handler(request):
            captured.append(request)
            return httpx.Response(200, json=provider_response(json.dumps(payload())))

        selected = profile()
        model = self.adapter(handler, profile=selected, profile_version=selected.version)
        configured = plan(model.binding)
        with TemporaryDirectory() as directory:
            execution = Execution(SQLiteStore(Path(directory) / "ledger.sqlite3"), model)
            execution.create("job", configured, "create")
            self.assertEqual(captured, [])
            result = execution.advance("job", 0, "advance")
            self.assertEqual(result.status, Status.READY)
            self.assertEqual(result.candidates[0].record.to_dict(), payload()["records"][0]["fields"])
            self.assertEqual(execution.advance("job", 0, "advance"), result)
        self.assertEqual(len(captured), 1)
        body = json.loads(captured[0].content)
        self.assertFalse(body["store"])
        self.assertNotIn("tools", body)
        self.assertEqual(body["text"]["format"]["schema"], output_schema(selected.schema))
        self.assertEqual(body["text"]["format"]["name"], "extracted_records")
        self.assertTrue(body["text"]["format"]["strict"])
        data = json.loads(body["input"][0]["content"])
        self.assertEqual(data["blocks"], [asdict(configured.chunks[0].blocks[0])])
        self.assertEqual(data["blocks"][0]["speaker"], "customer")
        self.assertNotIn("b", [block["id"] for block in data["blocks"]])
        self.assertIn("untrusted data", body["instructions"])
        embedded = json.loads(body["instructions"].split("\nRequired output JSON Schema:\n", 1)[1])
        self.assertEqual(embedded, body["text"]["format"]["schema"])
        self.assertEqual(captured[0].headers["x-stainless-retry-count"], "0")

    def test_profile_content_changes_binding_even_when_version_label_is_reused(self):
        original = FoundrySettings(
            "https://example.invalid/api/projects/placeholder", "placeholder-deployment",
            profile_version=profile().version, profile=profile(),
        )
        self.assertNotEqual(original.binding,
                            replace(original, profile=replace(profile(), instructions="A changed rule.")).binding)
        updated_field = replace(profile().schema.fields[0], description="A different field meaning")
        updated = replace(profile(), schema=replace(profile().schema, fields=(
            updated_field, *profile().schema.fields[1:],
        )))
        self.assertNotEqual(original.binding, replace(original, profile=updated).binding)
        with self.assertRaises(InvalidInput):
            replace(original, profile_version="wrong")

    def test_mismatched_plan_or_forged_profile_is_rejected_before_transport(self):
        captured = []
        model = self.adapter(
            lambda request: captured.append(request),
            profile=profile(), profile_version=profile().version,
        )
        configured = plan(model.binding)
        changed = replace(configured, profile=replace(profile(), instructions="Different behavior."))
        legacy = replace(synthetic_plan(), model_binding=model.binding, profile_version=profile().version)
        for frozen in (changed, legacy):
            with self.subTest(plan_type=type(frozen).__name__), self.assertRaises(Conflict):
                model.complete(ModelRequest("job", "request", 0, frozen.chunks[0], frozen))
        self.assertEqual(captured, [])

    def test_legacy_binding_is_byte_compatible_and_cannot_be_used_for_configured_plan(self):
        expected = "foundry-v1:89fd24528c495c7a0679a9fbd37e25695a147cbc7de8eba031759b6847ad80df"
        model = self.adapter(lambda _: self.fail("transport must not be called"))
        self.assertEqual(model.binding, expected)
        selected = replace(profile(), version="synthetic-financial-v1")
        configured = ConfiguredPlan(
            document_id="test", chunks=synthetic_plan().chunks, profile_version=selected.version,
            schema_version=selected.schema.version, parser_version="v1", model_binding=model.binding,
            profile=selected,
        )
        with self.assertRaises(Conflict):
            model.complete(ModelRequest("job", "attempt", 0, configured.chunks[0], configured))

    def test_rejection_logs_only_safe_status_and_allowlisted_category(self):
        from information_extraction import ModelFailure
        model = self.adapter(lambda _: httpx.Response(400, json={"error": {
            "message": "Unsupported reasoning field; private-source-and-token-material",
        }}))
        request_plan = replace(synthetic_plan(), model_binding=model.binding)
        with self.assertLogs("information_extraction.foundry_model", level="WARNING") as logs:
            with self.assertRaises(ModelFailure):
                model.complete(ModelRequest("job", "attempt", 0, request_plan.chunks[0], request_plan))
        self.assertIn("status=400 category=reasoning_parameter", logs.output[0])
        self.assertNotIn("private-source", str(logs.output))
