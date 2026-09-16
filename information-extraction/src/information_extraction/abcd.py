"""Bounded ABCD-format dialogue import; hidden task labels are never evidence."""

from dataclasses import dataclass
import json

from .codec import _hash, _json
from .contracts import Block, InvalidInput


PARSER_VERSION = "abcd-original-v1"
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_CONVERSATIONS = 100
MAX_TURNS = 1000
MAX_TEXT_BYTES = 32 * 1024
SPLITS = ("train", "dev", "test")


@dataclass(frozen=True)
class DialogueTurn:
    source_index: int
    speaker: str
    block: Block


@dataclass(frozen=True)
class ConversationSource:
    document_id: str
    conversation_id: int
    split: str
    parser_version: str
    turns: tuple[DialogueTurn, ...]
    excluded_action_turns: int

    @property
    def blocks(self) -> tuple[Block, ...]:
        return tuple(turn.block for turn in self.turns)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidInput("abcd_duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(_):
    raise InvalidInput("abcd_nonfinite_json_number")


def _conversation(value: object, split: str) -> ConversationSource:
    if type(value) is not dict or not {"convo_id", "original"} <= value.keys():
        raise InvalidInput("abcd_conversation_fields_required")
    conversation_id = value["convo_id"]
    if type(conversation_id) is not int or not 0 <= conversation_id < 2**63:
        raise InvalidInput("abcd_invalid_conversation_id")
    original = value["original"]
    if type(original) is not list or not 1 <= len(original) <= MAX_TURNS:
        raise InvalidInput("abcd_turn_count_out_of_range")
    turns = []
    excluded = 0
    for index, item in enumerate(original):
        if type(item) is not list or len(item) != 2:
            raise InvalidInput("abcd_original_turn_must_be_pair")
        speaker, text = item
        if type(speaker) is not str or speaker not in ("customer", "agent", "action"):
            raise InvalidInput("abcd_unknown_speaker")
        if type(text) is not str:
            raise InvalidInput("abcd_turn_text_required")
        try:
            size = len(text.encode("utf-8"))
        except UnicodeError:
            raise InvalidInput("abcd_invalid_unicode") from None
        if size > MAX_TEXT_BYTES:
            raise InvalidInput("abcd_turn_text_too_large")
        if speaker == "action":
            excluded += 1
            continue
        if not text.strip():
            raise InvalidInput("abcd_empty_dialogue_turn")
        turns.append(DialogueTurn(
            index, speaker, Block(
                f"turn-{index + 1}",
                text,
                f"abcd:{split}:conversation:{conversation_id}:original[{index}]",
            ),
        ))
    if not turns:
        raise InvalidInput("abcd_no_dialogue_evidence")
    identity = {
        "parser_version": PARSER_VERSION, "split": split, "conversation_id": conversation_id,
        "turns": [[turn.source_index, turn.speaker, turn.block.text] for turn in turns],
    }
    return ConversationSource(
        "abcd-" + _hash(_json(identity)), conversation_id, split, PARSER_VERSION, tuple(turns), excluded,
    )


def import_abcd(payload: bytes, *, split: str) -> tuple[ConversationSource, ...]:
    """Import one explicit split, preserving original text and zero-based locations.

    A top-level list follows the official training-sample shape. A split map
    must contain exactly train/dev/test. Only the selected split is normalized;
    all selected conversations must be valid. No labels or actions are inferred.
    """
    if split not in SPLITS:
        raise InvalidInput("abcd_invalid_split")
    if type(payload) is not bytes or len(payload) > MAX_INPUT_BYTES:
        raise InvalidInput("abcd_input_size_or_type_invalid")
    try:
        data = json.loads(payload.decode("utf-8"), object_pairs_hook=_object, parse_constant=_nonfinite)
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidInput("abcd_invalid_json") from None
    if type(data) is list:
        if split != "train":
            raise InvalidInput("abcd_sample_requires_train_split")
        selected = data
    elif type(data) is dict and set(data) == set(SPLITS):
        if any(type(data[name]) is not list for name in SPLITS):
            raise InvalidInput("abcd_split_must_be_list")
        selected = data[split]
    else:
        raise InvalidInput("abcd_dataset_shape_invalid")
    if not 1 <= len(selected) <= MAX_CONVERSATIONS:
        raise InvalidInput("abcd_conversation_count_out_of_range")
    sources = tuple(_conversation(value, split) for value in selected)
    if len({source.conversation_id for source in sources}) != len(sources):
        raise InvalidInput("abcd_duplicate_conversation_id")
    return sources
