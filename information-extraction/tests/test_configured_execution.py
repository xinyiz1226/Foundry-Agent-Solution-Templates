from copy import deepcopy
from contextlib import closing
from dataclasses import FrozenInstanceError, asdict, replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from information_extraction import (
    Action, Block, Blocked, Chunk, ConfiguredCandidate, ConfiguredPlan, Conflict, DialogueBlock,
    Execution, ExtractionProfile, FailureCode, FieldEvidence, FieldSpec, FieldType, FlatRecord,
    InvalidInput, ModelFailure, ModelResponse, Plan, RecordSchema, SQLiteStore, Status, TokenUsage,
)
from information_extraction.codec import _hash, _json, _snapshot
from information_extraction.sample import synthetic_plan
from information_extraction.schema import load_profile, output_schema
from tests.test_blob_store import AZURE_AVAILABLE, Backend, FakeContainerClient


LEGACY_PLAN = (
    '{"chunks":[{"blocks":[{"id":"block-1","location":"synthetic:line:1",'
    '"text":"ExampleCo revenue was USD 120 million."},{"id":"block-2","location":"synthetic:line:2",'
    '"text":"These figures are entirely fictional."}],"id":"chunk-1"},'
    '{"blocks":[{"id":"block-3","location":"synthetic:line:3","text":"ExampleCo operating income was USD 18 million."},'
    '{"id":"block-4","location":"synthetic:line:4","text":"This sample is not investment information."}],"id":"chunk-2"}],'
    '"document_id":"synthetic-exampleco","model_binding":"synthetic-model-v1","parser_version":"pre-normalized-v1",'
    '"profile_version":"synthetic-financial-v1","schema_version":"financial-metrics-v1"}'
)
LEGACY_FINGERPRINT = "84cff48e73daeba8c094ef05c33045cb643449541fe66b115c7dd884fc1ff858"


def profile():
    return ExtractionProfile("test-profile-v1", RecordSchema("test-flat-v1", (
        FieldSpec("name", FieldType.TEXT, "Explicit name"),
        FieldSpec("amount", FieldType.NUMBER, "Explicit amount"),
        FieldSpec("count", FieldType.INTEGER, "Explicit count"),
        FieldSpec("active", FieldType.BOOLEAN, "Explicit active flag"),
        FieldSpec("stage", FieldType.ENUM, "Explicit stage", choices=("pending", "resolved")),
        FieldSpec("day", FieldType.DATE, "Explicit date", date_format="YYYY-MM-DD"),
        FieldSpec("note", FieldType.TEXT, "Explicit optional note", nullable=True),
    )), "Extract only explicitly stated facts.")


def plan(binding="fixture-generic-v1"):
    selected = profile()
    return ConfiguredPlan(
        "fixture-source", (
            Chunk("first", (DialogueBlock(
                "a", "Example: amount 1.5, count 2, active, pending, on 2024-02-29.",
                "fixture:original[0]", "customer",
            ),)),
            Chunk("second", (Block("b", "A separate source statement.", "fixture:original[1]"),)),
        ),
        selected.version, selected.schema.version, "fixture-parser-v1", binding, selected,
    )


def payload(block_id="a"):
    fields = {"name": "Example", "amount": 1.5, "count": 2, "active": True,
              "stage": "pending", "day": "2024-02-29", "note": None}
    return {"records": [{
        "fields": fields,
        "evidence": {name: [] if value is None else [block_id] for name, value in fields.items()},
    }]}


class FixtureModel:
    binding = "fixture-generic-v1"

    def __init__(self):
        self.calls = []
        self.response = payload()
        self.error = None

    def complete(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return ModelResponse(deepcopy(self.response), TokenUsage(9, 3))


class SchemaTests(unittest.TestCase):
    def test_json_configuration_roundtrips_and_is_deeply_immutable(self):
        selected = profile()
        self.assertEqual(load_profile(_json(asdict(selected)).encode()), selected)
        with self.assertRaises(FrozenInstanceError):
            selected.schema.fields[0].description = "changed"
        schema = output_schema(selected.schema)
        record = schema["properties"]["records"]["items"]["properties"]
        self.assertEqual(set(record["fields"]["required"]), {item.name for item in selected.schema.fields})
        self.assertEqual(record["fields"]["properties"]["note"]["type"], ["string", "null"])
        self.assertEqual(record["fields"]["properties"]["day"]["pattern"], r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
        self.assertFalse(record["fields"]["additionalProperties"])

    def test_invalid_operator_configuration_is_rejected_explicitly(self):
        base = json.loads(_json(asdict(profile())))
        invalid = []
        for field in (
            {"name": "review_status"}, {"kind": "object"}, {"kind": "array"},
            {"nullable": "true"}, {"choices": ["unrelated"]}, {"minimum": 0},
            {"description": ""}, {"name": "bad-name"}, {"description": "\ud800"},
        ):
            changed = deepcopy(base)
            changed["schema"]["fields"][0].update(field)
            invalid.append(changed)
        for limit in (0, 101, True):
            changed = deepcopy(base)
            changed["schema"]["max_records"] = limit
            invalid.append(changed)
        changed = deepcopy(base)
        changed["schema"]["fields"].append(changed["schema"]["fields"][0])
        invalid.append(changed)
        changed = deepcopy(base)
        changed["schema"]["fields"][5]["date_format"] = "MM/DD/YYYY"
        invalid.append(changed)
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(InvalidInput):
                load_profile(_json(item).encode())
        for raw in (b'{"version":1,"version":2}', b'{"version":NaN}', b"\xff", b"[]" * 200000):
            with self.assertRaises(InvalidInput):
                load_profile(raw)
        with self.assertRaises(InvalidInput):
            FieldEvidence("name", ([],))

    def test_configuration_contents_and_speakers_are_part_of_plan_identity(self):
        original = plan()
        updated = replace(original.profile, instructions=original.profile.instructions + " Another rule.")
        self.assertNotEqual(_hash(_json(asdict(original))),
                            _hash(_json(asdict(replace(original, profile=updated)))))
        changed_block = replace(original.chunks[0].blocks[0], speaker="agent")
        changed = replace(original, chunks=(Chunk("first", (changed_block,)), original.chunks[1]))
        self.assertNotEqual(_hash(_json(asdict(original))), _hash(_json(asdict(changed))))
        for changes in ({"profile_version": "wrong"}, {"schema_version": "wrong"}, {"format_version": "v2"}):
            with self.assertRaises(InvalidInput):
                replace(original, **changes)

    def test_bounded_fields_records_text_and_plan_sizes(self):
        fields = tuple(FieldSpec(f"field_{i}", FieldType.TEXT, "Fact") for i in range(32))
        self.assertEqual(len(RecordSchema("v1", fields, 100).fields), 32)
        with self.assertRaises(InvalidInput):
            RecordSchema("v1", (*fields, FieldSpec("overflow", FieldType.TEXT, "Fact")))
        chunks = tuple(Chunk(f"chunk-{i}", (Block(f"block-{i}", "Text", "fixture"),)) for i in range(16))
        self.assertEqual(len(replace(plan(), chunks=chunks).chunks), 16)
        with self.assertRaisesRegex(InvalidInput, "size_limit"):
            replace(plan(), chunks=(*chunks, Chunk("extra", (Block("extra", "Text", "fixture"),))))
        with self.assertRaisesRegex(InvalidInput, "size_limit"):
            replace(plan(), chunks=(Chunk("huge", (Block("huge", "x" * (256 * 1024), "fixture"),)),))


class ConfiguredExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "ledger.sqlite3"
        self.make_store = lambda: SQLiteStore(self.path)
        self.model = FixtureModel()
        self.execution = Execution(self.make_store(), self.model)

    def test_shared_execution_handles_failure_resume_replay_and_frozen_field_evidence(self):
        initial = self.execution.create("job", plan(), "create")
        self.assertEqual(self.model.calls, [])
        first = self.execution.advance("job", 0, "first")
        candidate = first.candidates[0]
        self.assertIsInstance(candidate, ConfiguredCandidate)
        self.assertIsInstance(candidate.record, FlatRecord)
        self.assertEqual(candidate.record.to_dict(), payload()["records"][0]["fields"])
        self.assertEqual(candidate.field_evidence[-1], FieldEvidence("note", ()))
        self.assertEqual(candidate.evidence[0].text, plan().chunks[0].blocks[0].text)
        self.assertFalse(candidate.semantic_validation_performed)
        self.assertEqual(candidate.review_status, "pending")
        self.model.error = ModelFailure(FailureCode.MODEL_TIMEOUT, TokenUsage(2, 0))
        failed = self.execution.advance("job", 1, "fail")
        self.assertEqual(failed.candidates, first.candidates)
        self.assertEqual(failed.status, Status.FAILED)
        with self.assertRaises(Conflict):
            self.execution.advance("job", 2, "not-resume")
        self.model.error = None
        self.model.response = {"records": []}
        done = self.execution.advance("job", 2, "resume", action=Action.RESUME)
        self.assertEqual((done.status, len(done.attempts)), (Status.COMPLETED, 3))
        self.assertEqual(len(done.candidates), 1)
        restored = Execution(self.make_store(), self.model)
        self.assertEqual(restored.read("job"), done)
        self.assertEqual(restored.create("job", plan(), "create"), initial)
        self.assertEqual(restored.advance("job", 0, "first"), first)
        self.assertEqual(restored.advance("job", 1, "fail"), failed)
        self.assertEqual(restored.advance("job", 2, "resume", action=Action.RESUME), done)
        self.assertEqual(len(self.model.calls), 3)
        self.assertEqual(_snapshot(_json(asdict(done)), _hash(_json(asdict(done)))), done)
        changed = replace(plan(), profile=replace(profile(), instructions="A different frozen rule."))
        with self.assertRaises(Conflict):
            restored.create("job", changed, "new-config")

    def test_invalid_values_and_evidence_commit_failure_without_partial_records(self):
        cases = []
        for name, value in (
            ("amount", True), ("amount", float("inf")), ("amount", 2**63), ("count", 2.0),
            ("active", "true"), ("stage", "invented"), ("day", "2023-02-29"), ("day", "20240229"),
            ("name", None), ("name", ["nested"]), ("name", ""), ("name", " " * 10),
            ("name", "x" * 4097), ("name", "\ud800"),
        ):
            changed = payload()
            changed["records"][0]["fields"][name] = value
            cases.append((changed, FailureCode.MALFORMED_OUTPUT))
        changed = payload()
        changed["records"][0]["fields"]["review_status"] = "approved"
        cases.append((changed, FailureCode.MALFORMED_OUTPUT))
        for name, references in (("name", []), ("name", ["b"]), ("name", ["a", "a"]), ("note", ["a"])):
            changed = payload()
            changed["records"][0]["evidence"][name] = references
            cases.append((changed, FailureCode.INVALID_EVIDENCE))
        changed = payload()
        del changed["records"][0]["evidence"]["note"]
        cases.append((changed, FailureCode.INVALID_EVIDENCE))
        for index, (bad, code) in enumerate(cases):
            with self.subTest(index=index):
                job = f"invalid-{index}"
                self.execution.create(job, plan(), f"{job}-create")
                self.model.response = {"records": [payload()["records"][0], *bad["records"]]}
                failed = self.execution.advance(job, 0, f"{job}-advance")
                self.assertEqual((failed.status, failed.candidates), (Status.FAILED, ()))
                self.assertEqual(failed.attempts[-1].failure_code, code)
                self.assertEqual(failed.attempts[-1].usage, TokenUsage(9, 3))
                self.assertIsNone(failed.claim)

    def test_empty_results_multiple_records_and_numeric_boundaries(self):
        for index, records in enumerate(([], [payload()["records"][0]] * 2)):
            job = f"case-{index}"
            self.execution.create(job, plan(), job + "-create")
            self.model.response = {"records": records}
            result = self.execution.advance(job, 0, job + "-advance")
            self.assertEqual(len(result.candidates), len(records))
            self.assertEqual(result.completed_chunk_ids, ("first",))
        for number in (-(2**63), 2**63 - 1):
            job = f"integer-{number}"
            self.execution.create(job, plan(), job + "-create")
            self.model.response = payload()
            self.model.response["records"][0]["fields"].update(count=number, amount=number, name="x" * 4096)
            self.assertEqual(self.execution.advance(job, 0, job + "-advance").status, Status.READY)

    def test_output_limits_and_all_null_records_fail_without_unresolved_claim(self):
        selected = ExtractionProfile("nullable-v1", RecordSchema("nullable-schema-v1", (
            FieldSpec("fact", FieldType.TEXT, "Optional fact", nullable=True),
        ), 100), "Only explicit facts.")
        changed = replace(plan(), profile_version=selected.version, schema_version=selected.schema.version,
                          profile=selected)
        cases = [
            {"records": [{"fields": {"fact": None}, "evidence": {"fact": []}}]},
            {"records": [{"fields": {"fact": "x"}, "evidence": {"fact": ["a"]}}] * 101},
            {"records": [{"fields": {"fact": "x" * 4096}, "evidence": {"fact": ["a"]}}] * 100},
        ]
        for index, case in enumerate(cases):
            job = f"limit-{index}"
            self.execution.create(job, changed, job + "-create")
            self.model.response = case
            result = self.execution.advance(job, 0, job + "-advance")
            self.assertEqual((result.status, result.candidates, result.claim), (Status.FAILED, (), None))

    def test_unknown_model_failure_remains_blocked_after_restart(self):
        self.execution.create("job", plan(), "create")
        self.model.error = RuntimeError("ambiguous")
        with self.assertRaises(RuntimeError):
            self.execution.advance("job", 0, "attempt")
        restored = Execution(self.make_store(), self.model)
        self.assertEqual(restored.read("job").status, Status.IN_PROGRESS)
        with self.assertRaises(Blocked):
            restored.advance("job", 0, "attempt")
        self.assertEqual(len(self.model.calls), 1)


class LegacyIdentityTests(unittest.TestCase):
    def test_prechange_serialized_plan_and_existing_sqlite_receipt_are_unchanged(self):
        self.assertEqual(_json(asdict(synthetic_plan())), LEGACY_PLAN)
        self.assertEqual(_hash(LEGACY_PLAN), LEGACY_FINGERPRINT)
        document = {
            "job_id": "old-job", "plan": json.loads(LEGACY_PLAN), "plan_fingerprint": LEGACY_FINGERPRINT,
            "revision": 0, "status": "ready", "completed_chunk_ids": [], "attempts": [], "candidates": [], "claim": None,
        }
        encoded = _json(document)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            store = SQLiteStore(path)
            identity = _hash(_json(["create", "old-job", LEGACY_FINGERPRINT]))
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("INSERT INTO jobs VALUES (?, ?, ?, 0)", ("old-job", LEGACY_PLAN, LEGACY_FINGERPRINT))
                connection.execute("INSERT INTO checkpoints VALUES (?, 0, ?, ?)", ("old-job", encoded, _hash(encoded)))
                connection.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
                                   ("old-create", "old-job", identity, encoded, _hash(encoded)))
            result = store.create("old-job", synthetic_plan(), "old-create")
            self.assertIs(type(result.plan), Plan)
            self.assertEqual(_json(asdict(result)), encoded)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT payload FROM checkpoints").fetchone()[0], encoded)


@unittest.skipUnless(AZURE_AVAILABLE, "optional Azure dependencies not installed")
class ConfiguredBlobTests(ConfiguredExecutionTests):
    def setUp(self):
        from information_extraction.blob_store import BlobStore
        self.backend = Backend()
        self.make_store = lambda: BlobStore(FakeContainerClient(self.backend), prefix="configured-test-v1")
        self.model = FixtureModel()
        self.execution = Execution(self.make_store(), self.model)

    def test_forged_field_evidence_is_rejected_before_blob_publication(self):
        self.execution.create("job", plan(), "create")
        result = self.execution.advance("job", 0, "first")
        from information_extraction.contracts import Claim
        claimed = replace(result, revision=0, candidates=(), attempts=(), completed_chunk_ids=(),
                          status=Status.IN_PROGRESS, claim=Claim("first", 0, Action.ADVANCE, "first"))
        wrong = replace(result.candidates[0], field_evidence=(
            FieldEvidence("name", ("b",)), *result.candidates[0].field_evidence[1:],
        ))
        with self.assertRaises(Conflict):
            self.make_store().publish(claimed, replace(result, candidates=(wrong,)))
