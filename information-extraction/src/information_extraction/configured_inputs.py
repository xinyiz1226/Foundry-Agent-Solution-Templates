"""Deterministic bounded upload preparation; no files, models or ledger writes."""

import hashlib

from .abcd import import_abcd
from .contracts import Block, Chunk, ConfiguredPlan, DialogueBlock, ExtractionProfile, InvalidInput


MAX_TEXT_BYTES = 32 * 1024
MAX_ABCD_BYTES = 128 * 1024
MAX_CHUNK_BYTES = 8 * 1024
MAX_DIALOGUE_BYTES = 16 * 1024
TEXT_PARSER_VERSION = "utf8-lines-v1"


def prepare_plan(
    content: bytes, *, kind: str, profile: ExtractionProfile, model_binding: str,
    split: str = "train", conversation_id: int | None = None,
) -> ConfiguredPlan:
    if type(content) is not bytes or not isinstance(profile, ExtractionProfile):
        raise InvalidInput("invalid_upload")
    if kind == "text":
        if len(content) > MAX_TEXT_BYTES:
            raise InvalidInput("text_upload_too_large")
        if split != "train" or conversation_id is not None:
            raise InvalidInput("text_upload_has_dialogue_selectors")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeError:
            raise InvalidInput("text_upload_requires_utf8") from None
        chunks = []
        current = []
        size = 0
        for index, line in enumerate(text.splitlines(keepends=True), 1):
            line_size = len(line.encode("utf-8"))
            if line_size > MAX_CHUNK_BYTES:
                raise InvalidInput("text_line_too_large")
            if not line.strip():
                continue
            if current and size + line_size > MAX_CHUNK_BYTES:
                chunks.append(Chunk(f"chunk-{len(chunks) + 1}", tuple(current)))
                current, size = [], 0
            current.append(Block(f"line-{index}", line, f"utf8:line:{index}"))
            size += line_size
        if current:
            chunks.append(Chunk(f"chunk-{len(chunks) + 1}", tuple(current)))
        if not chunks:
            raise InvalidInput("empty_text_upload")
        document_id = "utf8-" + hashlib.sha256(content).hexdigest()
        parser_version = TEXT_PARSER_VERSION
    elif kind == "abcd":
        if len(content) > MAX_ABCD_BYTES:
            raise InvalidInput("abcd_web_upload_too_large")
        if type(conversation_id) is not int:
            raise InvalidInput("abcd_conversation_selection_required")
        sources = import_abcd(content, split=split)
        selected = next((source for source in sources if source.conversation_id == conversation_id), None)
        if selected is None:
            raise InvalidInput("abcd_conversation_not_found")
        blocks = tuple(DialogueBlock(
            turn.block.id, turn.block.text, turn.block.location, turn.speaker,
        ) for turn in selected.turns)
        if sum(len(block.text.encode("utf-8")) for block in blocks) > MAX_DIALOGUE_BYTES:
            raise InvalidInput("abcd_dialogue_too_large_for_one_chunk")
        chunks = [Chunk("conversation", blocks)]
        document_id, parser_version = selected.document_id, selected.parser_version
    else:
        raise InvalidInput("unsupported_upload_kind")
    return ConfiguredPlan(
        document_id, tuple(chunks), profile.version, profile.schema.version,
        parser_version, model_binding, profile,
    )
