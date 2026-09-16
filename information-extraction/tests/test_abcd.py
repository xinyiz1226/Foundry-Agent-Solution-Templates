from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from information_extraction.abcd import (
    MAX_CONVERSATIONS, MAX_INPUT_BYTES, MAX_TEXT_BYTES, MAX_TURNS, PARSER_VERSION, import_abcd,
)
from information_extraction.contracts import Block, InvalidInput


FIXTURE = Path(__file__).resolve().parents[1] / "samples" / "abcd-format-synthetic.json"


def encoded(value):
    return json.dumps(value).encode("utf-8")


class ABCDTests(unittest.TestCase):
    def setUp(self):
        self.rows = json.loads(FIXTURE.read_bytes())

    def test_original_dialogue_preserves_text_speakers_and_source_positions(self):
        with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            sources = import_abcd(FIXTURE.read_bytes(), split="train")
        self.assertEqual(len(sources), 2)
        first = sources[0]
        self.assertEqual(first.parser_version, PARSER_VERSION)
        self.assertEqual(first.conversation_id, 900001)
        self.assertEqual(first.split, "train")
        self.assertEqual(first.excluded_action_turns, 1)
        self.assertEqual([turn.source_index for turn in first.turns], [0, 1, 2, 4])
        self.assertEqual([turn.speaker for turn in first.turns], ["customer", "agent", "customer", "agent"])
        self.assertTrue(all(isinstance(block, Block) for block in first.blocks))
        self.assertEqual([block.id for block in first.blocks], ["turn-1", "turn-2", "turn-3", "turn-5"])
        self.assertEqual(first.blocks[-1].location, "abcd:train:conversation:900001:original[4]")
        self.assertEqual(first.blocks[-1].text, self.rows[0]["original"][4][1])

    def test_hidden_labels_and_action_text_never_change_visible_source_identity(self):
        before = import_abcd(encoded(self.rows), split="train")
        changed = deepcopy(self.rows)
        changed[0]["scenario"] = {"hidden_resolution": "Do not use this as evidence"}
        changed[0]["delexed"] = [{"text": "Another hidden answer"}]
        changed[0]["original"][3][1] = "Another hidden action result"
        after = import_abcd(encoded(changed), split="train")
        self.assertEqual(before, after)
        self.assertNotIn("HIDDEN_", repr(before))
        self.assertNotIn("Replacement approved", repr(before))

    def test_identity_depends_on_dialogue_and_split_not_json_formatting(self):
        before = import_abcd(encoded(self.rows), split="train")
        reordered = [{key: row[key] for key in reversed(row)} for row in self.rows]
        self.assertEqual(import_abcd(json.dumps(reordered, indent=4).encode(), split="train"), before)
        data = {"train": self.rows, "dev": self.rows, "test": []}
        self.assertEqual(import_abcd(encoded(data), split="train"), before)
        self.assertNotEqual(import_abcd(encoded(data), split="dev")[0].document_id, before[0].document_id)
        for change in ("text", "speaker", "id"):
            changed = deepcopy(self.rows)
            if change == "text":
                changed[0]["original"][0][1] += " An additional fact."
            elif change == "speaker":
                changed[0]["original"][0][0] = "agent"
            else:
                changed[0]["convo_id"] += 10
            with self.subTest(change=change):
                self.assertNotEqual(import_abcd(encoded(changed), split="train")[0].document_id,
                                    before[0].document_id)
        self.assertEqual(import_abcd(encoded(list(reversed(self.rows))), split="train")[1], before[0])

    def test_unicode_and_whitespace_are_preserved_verbatim(self):
        text = "  Caf\u00e9 support:\n\u8bf7\u68c0\u67e5\u7535\u6e90\u3002  "
        self.rows[0]["original"][0][1] = text
        result = import_abcd(encoded(self.rows), split="train")
        self.assertEqual(result[0].blocks[0].text, text)

    def test_malformed_inputs_are_rejected_without_echoing_source(self):
        for payload in (
            b"private-dialogue", b"\xff", b'{"train": NaN}',
            b'[{"convo_id":1,"convo_id":2,"original":[]}]',
            encoded({"unexpected": self.rows}),
            encoded({"train": self.rows, "dev": {}, "test": []}),
            encoded([]),
        ):
            with self.subTest(payload=payload), self.assertRaises(InvalidInput) as raised:
                import_abcd(payload, split="train")
            self.assertNotIn("private-dialogue", str(raised.exception))
        with self.assertRaisesRegex(InvalidInput, "sample_requires_train_split"):
            import_abcd(encoded(self.rows), split="test")
        with self.assertRaisesRegex(InvalidInput, "invalid_split"):
            import_abcd(encoded(self.rows), split="unknown")
        with self.assertRaises(InvalidInput):
            import_abcd("not-bytes", split="train")
        with self.assertRaises(InvalidInput):
            import_abcd(b" " * (MAX_INPUT_BYTES + 1), split="train")
        payload = encoded(self.rows)
        self.assertEqual(len(import_abcd(payload + b" " * (MAX_INPUT_BYTES - len(payload)), split="train")), 2)

    def test_invalid_conversations_fail_the_entire_selected_split(self):
        invalid = [
            {"convo_id": True, "original": [["customer", "hello"]]},
            {"convo_id": -1, "original": [["customer", "hello"]]},
            {"convo_id": 2**63, "original": [["customer", "hello"]]},
            {"convo_id": "1", "original": [["customer", "hello"]]},
            {"convo_id": 1, "original": []},
            {"convo_id": 1, "original": [["system", "private-dialogue"]]},
            {"convo_id": 1, "original": [["customer"]]},
            {"convo_id": 1, "original": [{"speaker": "customer", "text": "private-dialogue"}]},
            {"convo_id": 1, "original": [["customer", None]]},
            {"convo_id": 1, "original": [["customer", " \n "]]},
            {"convo_id": 1, "original": [["customer", "\ud800"]]},
            {"convo_id": 1, "original": [["action", "hidden"]]},
        ]
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(InvalidInput) as raised:
                import_abcd(encoded([self.rows[0], row]), split="train")
            self.assertNotIn("private-dialogue", str(raised.exception))
        with self.assertRaisesRegex(InvalidInput, "duplicate_conversation_id"):
            import_abcd(encoded([self.rows[0], self.rows[0]]), split="train")

    def test_limits_accept_exact_boundary_and_reject_one_over(self):
        self.rows[0]["original"] = [["customer", "x" * MAX_TEXT_BYTES]]
        self.assertEqual(len(import_abcd(encoded(self.rows), split="train")[0].blocks[0].text), MAX_TEXT_BYTES)
        self.rows[0]["original"][0][1] += "x"
        with self.assertRaisesRegex(InvalidInput, "turn_text_too_large"):
            import_abcd(encoded(self.rows), split="train")
        self.rows[0]["original"][0][1] = "\u00e9" * (MAX_TEXT_BYTES // 2)
        self.assertEqual(len(import_abcd(encoded(self.rows), split="train")[0].blocks[0].text.encode("utf-8")),
                         MAX_TEXT_BYTES)
        self.rows[0]["original"][0][1] += "x"
        with self.assertRaisesRegex(InvalidInput, "turn_text_too_large"):
            import_abcd(encoded(self.rows), split="train")
        self.rows[0]["original"] = [["customer", "x"]] * MAX_TURNS
        self.assertEqual(len(import_abcd(encoded(self.rows), split="train")[0].turns), MAX_TURNS)
        self.rows[0]["original"].append(["customer", "x"])
        with self.assertRaisesRegex(InvalidInput, "turn_count_out_of_range"):
            import_abcd(encoded(self.rows), split="train")
        rows = [{"convo_id": index, "original": [["customer", "x"]]} for index in range(MAX_CONVERSATIONS)]
        self.assertEqual(len(import_abcd(encoded(rows), split="train")), MAX_CONVERSATIONS)
        rows.append({"convo_id": MAX_CONVERSATIONS, "original": [["customer", "x"]]})
        with self.assertRaisesRegex(InvalidInput, "conversation_count_out_of_range"):
            import_abcd(encoded(rows), split="train")
