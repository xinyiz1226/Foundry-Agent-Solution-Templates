"""Local page acceptance with an injected client; no network or extraction calls."""

from copy import deepcopy
from dataclasses import asdict
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from information_extraction.contracts import InvalidInput
from information_extraction.profiles import FINANCIAL_PROFILE, SUPPORT_PROFILE


def _page(client_scope):
    from information_extraction.configured_ui import render_configured_workbench

    render_configured_workbench(client_scope)


def snapshot(job_id="job-1"):
    return {
        "job_id": job_id,
        "plan": {
            "document_id": "source-1", "profile_version": SUPPORT_PROFILE.version,
            "profile": asdict(SUPPORT_PROFILE),
            "chunks": [{"id": "chunk-1", "blocks": [{
                "id": "turn-1", "speaker": "customer", "location": "original[0]",
                "text": "Please cancel my order. <script>not executable</script>",
            }]}],
        },
        "revision": 0, "status": "ready", "completed_chunk_ids": [],
        "attempts": [], "candidates": [], "claim": None,
    }


def round_view(state="limited"):
    return {
        "state": state, "attempts_reserved": 1, "registration_confirmed": True,
        "authorization": {
            "job_id": "job-1", "run_id": "run-1", "request_id": "request-1",
            "expected_revision": 0, "limits": {"max_attempts": 2, "deadline": 1234567890.5},
        },
    }


class FakeClient:
    def __init__(self):
        self.calls = []
        self.enabled = True
        self.remaining_calls = 5
        self.saved = {}
        self.failure = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def scope(self):
        return self

    def _call(self, method, *args, **kwargs):
        from information_extraction.configured_client import ConfiguredWorkbenchError

        self.calls.append((method, deepcopy(args), deepcopy(kwargs)))
        if self.failure == method:
            raise ConfiguredWorkbenchError("mutation_unconfirmed")

    def configuration(self):
        self._call("configuration")
        return {
            "enabled": self.enabled, "remaining_calls": self.remaining_calls,
            "model_description": "test configured provider",
            "profiles": {"financial": asdict(FINANCIAL_PROFILE), "support": asdict(SUPPORT_PROFILE)},
        }

    def jobs(self):
        self._call("jobs")
        return tuple({
            "job_id": key, "document_id": value["snapshot"]["plan"]["document_id"],
            "profile_version": value["snapshot"]["plan"]["profile_version"],
            "revision": value["snapshot"]["revision"], "status": value["snapshot"]["status"],
        } for key, value in self.saved.items())

    def current(self, job_id):
        self._call("current", job_id)
        return deepcopy(self.saved[job_id])

    def add_job(self, job_id="job-1", *, state=None):
        current = {
            "job_id": job_id, "snapshot": snapshot(job_id),
            "round": round_view(state) if state else None, "pending_request": None,
        }
        self.saved[job_id] = current
        return current

    def prepare(self, content, **kwargs):
        self._call("prepare", content, **kwargs)
        current = self.add_job(f"job-{len(self.saved) + 1}")
        current["snapshot"]["plan"]["profile"] = asdict(kwargs["profile"])
        current["snapshot"]["plan"]["profile_version"] = kwargs["profile"].version
        return deepcopy(current)

    def start(self, job_id, **kwargs):
        self._call("start", job_id, **kwargs)
        self.saved[job_id]["round"] = round_view("queued")
        return {}

    def resume(self, current, **kwargs):
        self._call("resume", current, **kwargs)
        self.saved[current["job_id"]]["round"] = round_view("queued")
        return {}

    def retry(self, job_id, pending):
        self._call("retry", job_id, pending)
        self.saved[job_id]["pending_request"] = None
        self.saved[job_id]["round"] = round_view("queued")
        return {}

    @property
    def mutations(self):
        return [item for item in self.calls if item[0] in ("prepare", "start", "resume", "retry")]


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "optional workbench dependencies unavailable")
class ConfiguredPageTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()

    def page(self):
        from streamlit.testing.v1 import AppTest

        page = AppTest.from_function(_page, args=(self.client.scope,), default_timeout=10).run()
        self.assertEqual(len(page.exception), 0)
        return page

    def check(self, page):
        self.assertEqual(len(page.exception), 0)
        return page

    def test_profile_switch_custom_schema_and_create_are_separate_from_start(self):
        page = self.page()
        financial = json.loads(page.text_area(key="configured_profile_json").value)
        self.assertEqual(financial["version"], FINANCIAL_PROFILE.version)
        page.selectbox(key="configured_profile").select("Customer support").run()
        support = json.loads(page.text_area(key="configured_profile_json").value)
        self.assertEqual(support["version"], SUPPORT_PROFILE.version)
        custom = {
            "version": "custom-v1", "instructions": "Extract the explicitly stated concern.",
            "schema": {"version": "custom-schema-v1", "fields": [{
                "name": "concern", "kind": "text", "description": "An explicit concern.",
            }]},
        }
        page.text_area(key="configured_profile_json").set_value(json.dumps(custom)).run()
        page.button(key="configured_refresh").click().run()
        self.assertEqual(json.loads(page.text_area(key="configured_profile_json").value), custom)
        page.text_area(key="configured_paste_text").set_value("Please cancel my order.").run()
        page.button(key="configured_create").click().run()
        self.check(page)
        self.assertEqual([call[0] for call in self.client.mutations], ["prepare"])
        self.assertEqual(self.client.mutations[0][1], (b"Please cancel my order.",))
        self.assertEqual(self.client.mutations[0][2]["profile"].schema.fields[0].name, "concern")
        self.assertEqual(page.number_input(key="configured_attempts").value, 1)
        self.assertEqual(page.number_input(key="configured_duration").value, 120)
        self.assertEqual(json.loads(page.text_area(key="configured_profile_json").value), custom)
        page.button(key="configured_start").click().run()
        self.check(page)
        self.assertEqual([call[0] for call in self.client.mutations], ["prepare", "start"])
        self.assertEqual(self.client.mutations[-1][2], {"max_attempts": 1, "duration_seconds": 120})
        self.assertTrue(page.button(key="configured_start").disabled)
        page.selectbox(key="configured_profile").select("Financial").run()
        self.assertEqual(json.loads(page.text_area(key="configured_profile_json").value), financial)
        self.assertEqual(self.client.saved["job-1"]["snapshot"]["plan"]["profile"]["version"], "custom-v1")

    def test_refresh_catalog_and_new_browser_only_read(self):
        self.client.add_job()
        self.client.add_job("job-2")
        page = self.page()
        page.button(key="configured_refresh").click().run()
        page.selectbox(key="configured_job").select("job-2").run()
        self.check(page)
        self.assertTrue(any("Job: job-2" in item.value for item in page.text))
        self.page()
        self.assertFalse(self.client.mutations)
        self.assertTrue(all(call[0] in ("configuration", "jobs", "current") for call in self.client.calls))

    def test_schema_and_empty_input_rejected_without_prepare(self):
        page = self.page()
        page.button(key="configured_create").click().run()
        self.assertTrue(page.error)
        page.text_area(key="configured_paste_text").set_value("A valid source.").run()
        for invalid in ('{"version":', '{"version":"one","version":"two"}', "{}"):
            page.text_area(key="configured_profile_json").set_value(invalid).run()
            page.button(key="configured_create").click().run()
            self.check(page)
            self.assertTrue(page.error)
        self.assertFalse(self.client.mutations)

    def test_invalid_utf8_upload_is_visible_and_never_prepared(self):
        with patch("streamlit.file_uploader", return_value=BytesIO(b"\xff")):
            page = self.page()
            page.button(key="configured_create").click().run()
            self.check(page)
            self.assertTrue(any("UTF-8" in item.value for item in page.error))
        self.assertFalse(self.client.mutations)

    def test_upload_takes_precedence_and_preserves_exact_bytes(self):
        content = b"Revenue was 120 USD millions.\r\n"
        with patch("streamlit.file_uploader", return_value=BytesIO(content)):
            page = self.page()
            page.text_area(key="configured_paste_text").set_value("Not the uploaded source.").run()
            page.button(key="configured_create").click().run()
            self.check(page)
        self.assertEqual(self.client.mutations[0][1], (content,))

    def test_web_byte_limits_before_prepare(self):
        page = self.page()
        page.text_area(key="configured_paste_text").set_value("é" * (16 * 1024 + 1)).run()
        page.button(key="configured_create").click().run()
        self.assertTrue(any("32768" in item.value for item in page.error))
        page.selectbox(key="configured_kind").select("ABCD conversations").run()
        page.text_area(key="configured_paste_abcd").set_value(" " * (128 * 1024 + 1)).run()
        page.button(key="configured_create").click().run()
        self.assertTrue(any("131072" in item.value for item in page.error))
        dialogue = json.dumps([{"convo_id": 1, "original": [["customer", "x" * (16 * 1024 + 1)]]}])
        page.text_area(key="configured_paste_abcd").set_value(dialogue).run()
        page.button(key="configured_create").click().run()
        self.check(page)
        self.assertTrue(any("16 KiB" in item.value for item in page.error))
        self.assertFalse(self.client.mutations)

    def test_abcd_selection_original_only_and_exact_source_submission(self):
        payload = json.dumps({
            "train": [{"convo_id": 1, "original": [["customer", "Training text."]]}],
            "dev": [
                {"convo_id": 21, "original": [["customer", "First conversation."]]},
                {"convo_id": 22, "scenario": {"hidden": "SCENARIO SECRET"},
                 "delexed": [["customer", "DELEXED SECRET"]],
                 "original": [["customer", "Please cancel."], ["action", "ACTION SECRET"],
                              ["agent", "Cancellation is pending."]]},
            ],
            "test": [],
        })
        page = self.page()
        page.selectbox(key="configured_kind").select("ABCD conversations").run()
        page.selectbox(key="configured_split").select("dev").run()
        page.text_area(key="configured_paste_abcd").set_value(payload).run()
        page.selectbox(key="configured_conversation").select(22).run()
        rendered = "\n".join(item.value for item in [*page.code, *page.text, *page.caption])
        self.assertIn("Please cancel.", rendered)
        self.assertIn("Cancellation is pending.", rendered)
        self.assertIn("agent", rendered)
        self.assertNotIn("SCENARIO SECRET", rendered)
        self.assertNotIn("DELEXED SECRET", rendered)
        self.assertNotIn("ACTION SECRET", rendered)
        page.button(key="configured_create").click().run()
        self.check(page)
        call = self.client.mutations[0]
        self.assertEqual(call[1], (payload.encode("utf-8"),))
        self.assertEqual((call[2]["kind"], call[2]["split"], call[2]["conversation_id"]), ("abcd", "dev", 22))

    def test_completed_generic_pending_fields_nullable_and_original_evidence(self):
        current = self.client.add_job(state="completed")
        current["snapshot"].update(
            status="completed", revision=1, completed_chunk_ids=["chunk-1"],
            attempts=[{"usage": {"input_tokens": 11, "output_tokens": 7}}],
            candidates=[{
                "id": "candidate-1",
                "record": {"fields": [
                    {"name": "customer_issue_or_request", "value": "Cancel the order"},
                    {"name": "product_or_service", "value": None},
                ]},
                "field_evidence": [
                    {"name": "customer_issue_or_request", "block_ids": ["turn-1"]},
                    {"name": "product_or_service", "block_ids": []},
                ],
                "evidence": [{
                    "document_id": "source-1", "chunk_id": "chunk-1", "block_id": "turn-1",
                    "location": "original[0]", "text": "Untrusted replacement quote must never display.",
                }],
            }],
        )
        page = self.page()
        table = page.table[0].value
        self.assertEqual(table["Field"].tolist(), ["customer_issue_or_request", "product_or_service"])
        self.assertEqual(table["Value"].tolist(), ['"Cancel the order"', "null"])
        self.assertEqual(table["Review"].tolist(), ["Pending", "Pending"])
        self.assertFalse({"configured_start", "configured_resume", "configured_retry"} & {b.key for b in page.button})
        self.assertTrue(any("Speaker: customer" in item.value for item in page.text))
        self.assertTrue(any("original[0]" in item.value for item in page.text))
        self.assertTrue(any("nullable missing fact" in item.value for item in page.caption))
        self.assertTrue(any("11 input / 7 output" in item.value for item in page.caption))
        self.assertTrue(any("<script>" in item.value for item in page.code))
        self.assertFalse(any("Untrusted replacement" in item.value for item in page.code))
        page.text_area(key="configured_profile_json").set_value("{}").run()
        self.assertEqual(page.table[0].value["Field"].tolist(), table["Field"].tolist())
        self.assertFalse(self.client.mutations)

    def test_disabled_and_exhausted_modes_cannot_start_but_can_prepare(self):
        self.client.enabled = False
        self.client.add_job()
        page = self.page()
        self.assertTrue(any("Prepare-only" in item.value for item in page.info))
        self.assertTrue(page.button(key="configured_start").disabled)
        self.assertTrue(page.button(key="configured_resume").disabled)
        page.text_area(key="configured_paste_text").set_value("New source.").run()
        page.button(key="configured_create").click().run()
        self.assertEqual([c[0] for c in self.client.mutations], ["prepare"])
        self.client.enabled = True
        self.client.remaining_calls = 0
        page.button(key="configured_refresh").click().run()
        self.check(page)
        self.assertTrue(page.button(key="configured_start").disabled)
        self.assertTrue(any("Remaining admitted calls: 0" in item.value for item in page.warning))
        self.assertTrue(any("policy maximum: 5 per named grant" in item.value for item in page.warning))
        self.assertFalse(any("named-grant cap: 5" in item.value for item in page.warning))

    def test_unknown_claim_and_unknown_round_are_inspection_only(self):
        current = self.client.add_job(state="in_progress_or_interrupted")
        current["pending_request"] = {"request_id": "saved-1", "deadline": 42}
        page = self.page()
        self.assertTrue(any("Inspection only" in item.value for item in page.error))
        self.assertFalse({"configured_start", "configured_resume", "configured_retry"} & {b.key for b in page.button})
        for state in ("future-state", "queued", "limited"):
            current["round"]["state"] = state
            current["snapshot"]["claim"] = {"request_id": "unknown-claim"}
            page.button(key="configured_refresh").click().run()
            self.check(page)
            self.assertFalse({"configured_start", "configured_resume", "configured_retry"} & {b.key for b in page.button})
        self.assertFalse(self.client.mutations)

    def test_attempt_allowance_is_capped_and_clamped_to_remaining_calls(self):
        self.client.add_job()
        page = self.page()
        page.number_input(key="configured_attempts").set_value(5).run()
        self.client.remaining_calls = 2
        page.button(key="configured_refresh").click().run()
        self.check(page)
        allowance = page.number_input(key="configured_attempts")
        self.assertEqual(allowance.max, 2)
        self.assertEqual(allowance.value, 2)
        page.button(key="configured_start").click().run()
        self.check(page)
        self.assertEqual(self.client.mutations[-1][2]["max_attempts"], 2)

    def test_running_queued_read_only_and_failed_limited_explicit_resume(self):
        current = self.client.add_job(state="running")
        page = self.page()
        for state in ("running", "queued"):
            current["round"]["state"] = state
            page.button(key="configured_refresh").click().run()
            self.assertTrue(page.button(key="configured_start").disabled)
            self.assertTrue(page.button(key="configured_resume").disabled)
        for state in ("limited", "failed"):
            current["round"]["state"] = state
            current["snapshot"]["status"] = "failed" if state == "failed" else "ready"
            page.button(key="configured_refresh").click().run()
            before = deepcopy(current)
            self.assertFalse(page.button(key="configured_resume").disabled)
            page.button(key="configured_resume").click().run()
            self.check(page)
            self.assertEqual(self.client.mutations[-1][0], "resume")
            self.assertEqual(self.client.mutations[-1][1], (before,))
        self.assertEqual(len(self.client.mutations), 2)

    def test_pending_retry_is_explicit_and_exact_even_after_refresh_and_reopen(self):
        current = self.client.add_job(state="queued")
        pending = {
            "action": "resume", "run_id": "saved-run", "request_id": "saved-request",
            "expected_revision": 2, "max_attempts": 3, "deadline": 1234567890.25,
        }
        current["pending_request"] = deepcopy(pending)
        page = self.page()
        page.button(key="configured_refresh").click().run()
        page = self.page()
        self.assertFalse(self.client.mutations)
        self.assertFalse({"configured_start", "configured_resume"} & {b.key for b in page.button})
        self.assertTrue(any("saved-request" in str(item.value) for item in page.json))
        page.button(key="configured_retry").click().run()
        self.check(page)
        self.assertEqual(self.client.mutations, [("retry", ("job-1", pending), {})])

    def test_mutation_error_clears_stale_success_and_refresh_does_not_retry(self):
        self.client.add_job()
        page = self.page()
        page.session_state["configured_notice"] = "Old success notice"
        self.client.failure = "start"
        page.button(key="configured_start").click().run()
        self.check(page)
        self.assertFalse(page.success)
        self.assertTrue(any("mutation_unconfirmed" in item.value for item in page.error))
        self.assertNotIn("configured_notice", page.session_state)
        self.client.failure = None
        page.button(key="configured_refresh").click().run()
        self.check(page)
        self.assertEqual([c[0] for c in self.client.mutations], ["start"])

    def test_pending_retry_error_preserves_request_and_removes_success(self):
        current = self.client.add_job(state="queued")
        pending = {
            "action": "start", "job_id": "job-1", "request_id": "original-request",
            "expected_revision": 0, "max_attempts": 2, "deadline": 987654321,
        }
        current["pending_request"] = deepcopy(pending)
        page = self.page()
        self.client.enabled = False
        page.button(key="configured_refresh").click().run()
        self.assertTrue(page.button(key="configured_retry").disabled)
        self.client.enabled = True
        self.client.failure = "retry"
        page.button(key="configured_refresh").click().run()
        page.session_state["configured_notice"] = "Old success"
        page.button(key="configured_retry").click().run()
        self.check(page)
        self.assertFalse(page.success)
        self.assertTrue(page.error)
        self.assertEqual(current["pending_request"], pending)
        self.client.failure = None
        page.button(key="configured_refresh").click().run()
        self.check(page)
        self.assertEqual(self.client.mutations, [("retry", ("job-1", pending), {})])
        self.assertFalse(page.button(key="configured_retry").disabled)

    def test_prepare_error_clears_stale_success(self):
        self.client.add_job()
        page = self.page()
        page.session_state["configured_notice"] = "Old success notice"
        self.client.failure = "prepare"
        page.text_area(key="configured_paste_text").set_value("A source.").run()
        page.session_state["configured_notice"] = "Old success notice"
        page.button(key="configured_create").click().run()
        self.check(page)
        self.assertFalse(page.success)
        self.assertTrue(any("mutation_unconfirmed" in item.value for item in page.error))

    def test_missing_connection_entry_is_safe_and_does_not_read_network(self):
        from streamlit.testing.v1 import AppTest

        entry = Path(__file__).resolve().parents[1] / "configured_workbench.py"
        with patch.dict(os.environ, {}, clear=True):
            page = AppTest.from_file(str(entry), default_timeout=10).run()
        self.check(page)
        self.assertTrue(any("connection is missing" in item.value for item in page.error))


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "optional workbench dependencies unavailable")
class WebInputTests(unittest.TestCase):
    def test_utf8_and_limits_include_boundaries(self):
        from information_extraction.configured_ui import validate_source

        self.assertEqual(validate_source(b"x" * (32 * 1024), "text"), ())
        for content in (b"", b" ", b"\xff", b"x" * (32 * 1024 + 1)):
            with self.subTest(content_length=len(content)), self.assertRaises(InvalidInput):
                validate_source(content, "text")

    def test_dialogue_limit_counts_original_evidence_only(self):
        from information_extraction.configured_ui import validate_dialogue, validate_source

        content = json.dumps([{
            "convo_id": 1,
            "original": [["customer", "x" * (16 * 1024)], ["action", "y" * (32 * 1024)]],
        }]).encode()
        source = validate_source(content, "abcd")[0]
        validate_dialogue(source)
        self.assertEqual(len(source.turns), 1)


if __name__ == "__main__":
    unittest.main()
