from dataclasses import asdict
from pathlib import Path
import unittest

from information_extraction import DialogueBlock, InvalidInput
from information_extraction.configured_inputs import (
    MAX_ABCD_BYTES, MAX_CHUNK_BYTES, MAX_TEXT_BYTES, prepare_plan,
)
from information_extraction.profiles import FINANCIAL_PROFILE, SUPPORT_PROFILE


class ConfiguredInputTests(unittest.TestCase):
    def text(self, value):
        return prepare_plan(value, kind="text", profile=FINANCIAL_PROFILE, model_binding="test-v1")

    def test_utf8_bom_blank_lines_and_line_endings_preserve_source_locations(self):
        raw = b"\xef\xbb\xbfRevenue 120.\r\n\r\nOperating income 18.\n"
        plan = self.text(raw)
        self.assertEqual([block.text for block in plan.chunks[0].blocks],
                         ["Revenue 120.\r\n", "Operating income 18.\n"])
        self.assertEqual([block.location for block in plan.chunks[0].blocks], ["utf8:line:1", "utf8:line:3"])
        self.assertEqual([block.id for block in plan.chunks[0].blocks], ["line-1", "line-3"])
        self.assertEqual(self.text(raw), plan)
        self.assertNotEqual(self.text(raw.replace(b"\r\n", b"\n")).document_id, plan.document_id)
        self.assertEqual(plan.profile, FINANCIAL_PROFILE)

    def test_exact_byte_limits_and_chunk_boundaries(self):
        line = b"x" * (MAX_CHUNK_BYTES - 1) + b"\n"
        plan = self.text(line * 4)
        self.assertEqual(len(plan.chunks), 4)
        self.assertEqual(len(line * 4), MAX_TEXT_BYTES)
        with self.assertRaisesRegex(InvalidInput, "text_upload_too_large"):
            self.text(line * 4 + b"x")
        with self.assertRaisesRegex(InvalidInput, "text_line_too_large"):
            self.text(b"x" * (MAX_CHUNK_BYTES + 1))
        plan = self.text(("\u00e9" * 4000 + "\n").encode("utf-8"))
        self.assertEqual(len(plan.chunks), 1)

    def test_invalid_text_and_unsupported_selectors_are_explicit(self):
        for raw in (b"", b"\r\n \t", b"\xff"):
            with self.subTest(raw=raw), self.assertRaises(InvalidInput):
                self.text(raw)
        with self.assertRaises(InvalidInput):
            prepare_plan(b"x", kind="pdf", profile=FINANCIAL_PROFILE, model_binding="test")
        with self.assertRaises(InvalidInput):
            prepare_plan(b"x", kind="text", profile=FINANCIAL_PROFILE, model_binding="test", conversation_id=1)

    def test_abcd_uses_selected_dialogue_only_with_speakers(self):
        raw = (Path(__file__).resolve().parents[1] / "samples" / "abcd-format-synthetic.json").read_bytes()
        plan = prepare_plan(raw, kind="abcd", profile=SUPPORT_PROFILE, model_binding="test-v1",
                            conversation_id=900001)
        self.assertEqual(len(plan.chunks), 1)
        self.assertEqual(len(plan.chunks[0].blocks), 4)
        self.assertTrue(all(isinstance(block, DialogueBlock) for block in plan.chunks[0].blocks))
        self.assertEqual([block.speaker for block in plan.chunks[0].blocks],
                         ["customer", "agent", "customer", "agent"])
        self.assertNotIn("HIDDEN_", str(asdict(plan)))
        self.assertNotIn("Replacement approved", str(asdict(plan)))
        self.assertNotIn("care instructions", str(asdict(plan)))
        for selection in (None, True, -1):
            with self.assertRaises(InvalidInput):
                prepare_plan(raw, kind="abcd", profile=SUPPORT_PROFILE, model_binding="test",
                             conversation_id=selection)
        with self.assertRaisesRegex(InvalidInput, "abcd_web_upload_too_large"):
            prepare_plan(b"x" * (MAX_ABCD_BYTES + 1), kind="abcd", profile=SUPPORT_PROFILE,
                         model_binding="test", conversation_id=1)
