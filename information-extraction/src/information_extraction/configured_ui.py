"""Local presentation only: reads inspect; explicit clicks request bounded work."""

from collections.abc import Callable
from contextlib import AbstractContextManager
import json
from typing import Any

import streamlit as st

from .abcd import SPLITS, ConversationSource, import_abcd
from .configured_client import ConfiguredWorkbenchError
from .contracts import InvalidInput
from .schema import load_profile


MAX_TEXT_BYTES = 32 * 1024
MAX_ABCD_BYTES = 128 * 1024
MAX_DIALOGUE_BYTES = 16 * 1024
PROFILE_NAMES = {"Financial": "financial", "Customer support": "support"}
SOURCE_KINDS = {"UTF-8 text": "text", "ABCD conversations": "abcd"}


def validate_source(content: bytes, kind: str, split: str = "train") -> tuple[ConversationSource, ...]:
    """Apply the narrower web bounds before decoding or importing anything."""
    limit = MAX_TEXT_BYTES if kind == "text" else MAX_ABCD_BYTES
    if kind not in ("text", "abcd") or not content or len(content) > limit:
        raise InvalidInput(f"Source must contain 1–{limit} bytes.")
    try:
        text = content.decode("utf-8")
    except UnicodeError:
        raise InvalidInput("Source must be valid UTF-8.") from None
    if not text.strip():
        raise InvalidInput("Source must not be blank.")
    return import_abcd(content, split=split) if kind == "abcd" else ()


def validate_dialogue(source: ConversationSource) -> None:
    if sum(len(turn.block.text.encode("utf-8")) for turn in source.turns) > MAX_DIALOGUE_BYTES:
        raise InvalidInput("Selected original dialogue exceeds the 16 KiB web limit.")


def _banner(configuration: dict) -> None:
    if configuration["enabled"]:
        st.warning(
            f"Real-model mode | {configuration['model_description']} | "
            f"Remaining admitted calls: {configuration['remaining_calls']} (policy maximum: 5 per named grant). "
            "Calls can incur charges; admission limits are not a token or cost guarantee."
        )
    else:
        st.info(
            "Prepare-only mode: create and inspect frozen jobs; extraction is disabled. "
            f"Remaining admitted calls: {configuration['remaining_calls']}."
        )


def _show_snapshot(current: dict) -> None:
    snapshot = current["snapshot"]
    plan = snapshot["plan"]
    chunks = plan["chunks"]
    st.subheader("Current job")
    st.text(f"Job: {current['job_id']}")
    status, revision, attempts = st.columns(3)
    status.metric("Status", snapshot["status"])
    revision.metric("Committed revision", snapshot["revision"])
    attempts.metric("Committed attempts", len(snapshot["attempts"]))
    completed = len(snapshot["completed_chunk_ids"])
    st.progress(completed / len(chunks) if chunks else 0.0)
    st.caption(f"{completed} / {len(chunks)} chunks committed")
    usages = [item["usage"] for item in snapshot["attempts"] if item.get("usage") is not None]
    st.caption(
        f"Known tokens: {sum(item['input_tokens'] for item in usages)} input / "
        f"{sum(item['output_tokens'] for item in usages)} output | "
        f"Committed attempts with unknown usage: {len(snapshot['attempts']) - len(usages)}. "
        "Usage is not a billing total."
    )
    round_view = current.get("round")
    if round_view:
        authorization = round_view["authorization"]
        limits = authorization["limits"]
        st.text(
            f"Round: {round_view['state']} | Run: {authorization['run_id']} | "
            f"Request: {authorization['request_id']}"
        )
        st.caption(
            f"Attempts reserved: {round_view['attempts_reserved']} / {limits['max_attempts']} | "
            f"Remaining round allowance: {max(0, limits['max_attempts'] - round_view['attempts_reserved'])} | "
            f"Saved deadline (Unix seconds): {limits['deadline']} | "
            f"Native registration confirmed: {round_view['registration_confirmed']}"
        )
    with st.expander("Frozen job profile (editor changes apply only to new jobs)"):
        st.json(plan["profile"])
    blocks = {
        (chunk["id"], block["id"]): block
        for chunk in chunks for block in chunk["blocks"]
    }
    with st.expander("Frozen original source"):
        for (chunk_id, block_id), block in blocks.items():
            st.text(f"{chunk_id} | {block_id} | {block['location']} | {block.get('speaker') or 'text'}")
            st.code(block["text"], language=None)
    st.subheader("Candidate records")
    st.warning(
        "Pending review. Structural validation is not semantic validation, accuracy, "
        "human approval, or permission to export."
    )
    if not snapshot["candidates"]:
        st.caption("No committed candidate records yet.")
    for candidate in snapshot["candidates"]:
        st.text(f"Candidate: {candidate['id']} | Review: Pending | Semantic validation performed: False")
        st.table([{
            "Field": field["name"],
            "Value": json.dumps(field["value"], ensure_ascii=False),
            "Review": "Pending",
        } for field in candidate["record"]["fields"]])
        evidence = {item["block_id"]: item for item in candidate["evidence"]}
        with st.expander(f"Field evidence — {candidate['id']}"):
            for field in candidate["field_evidence"]:
                st.text(f"Field: {field['name']}")
                if not field["block_ids"]:
                    st.caption("No source evidence (nullable missing fact).")
                for block_id in field["block_ids"]:
                    reference = evidence.get(block_id)
                    block = blocks.get((reference["chunk_id"], block_id)) if reference else None
                    if block is None or reference["document_id"] != plan["document_id"]:
                        st.warning("Original source reference unavailable; no quotation is displayed.")
                        continue
                    st.text(
                        f"{reference['document_id']} | {reference['chunk_id']} | {block_id} | "
                        f"{block['location']} | Speaker: {block.get('speaker') or 'text'}"
                    )
                    st.code(block["text"], language=None)


def render_configured_workbench(
    client_scope: Callable[[], AbstractContextManager[Any]], *, poll_seconds: int = 2,
) -> None:
    st.warning(
        "LOCAL ONLY — single-user loopback workbench, not a hosted or multi-user service. "
        "Do not expose its ports. No PDF/OCR, URL fetching, or arbitrary server file paths."
    )
    try:
        with client_scope() as client:
            configuration = client.configuration()
    except ConfiguredWorkbenchError as error:
        st.session_state.pop("configured_notice", None)
        st.error(str(error))
        return

    st.subheader("Prepare a new job")
    st.caption("Inputs and profile edits freeze into a NEW job only; they never mutate the selected job.")
    selected_profile = st.selectbox("Extraction profile", list(PROFILE_NAMES), key="configured_profile")
    if st.session_state.get("configured_profile_previous") != selected_profile:
        st.session_state["configured_profile_json"] = json.dumps(
            configuration["profiles"][PROFILE_NAMES[selected_profile]], ensure_ascii=False, indent=2,
        )
        st.session_state["configured_profile_previous"] = selected_profile
    profile_text = st.text_area(
        "Profile JSON (schema and extraction instructions)", height=260, key="configured_profile_json",
    )
    label = st.selectbox("Source kind", list(SOURCE_KINDS), key="configured_kind")
    kind = SOURCE_KINDS[label]
    uploaded = st.file_uploader(
        "Upload UTF-8 source (.txt or .json; no gzip)", type=["txt"] if kind == "text" else ["json"],
        key=f"configured_upload_{kind}",
    )
    pasted = st.text_area(
        "Or paste UTF-8 text" if kind == "text" else "Or paste ABCD JSON",
        key=f"configured_paste_{kind}",
    )
    st.caption("Upload takes precedence over paste. Text ≤32 KiB; ABCD JSON ≤128 KiB; selected dialogue ≤16 KiB.")
    split = st.selectbox("ABCD split", SPLITS, key="configured_split") if kind == "abcd" else "train"
    content = b""
    conversation_id = None
    input_error = None
    try:
        content = uploaded.getvalue() if uploaded is not None else pasted.encode("utf-8")
        sources = validate_source(content, kind, split)
        if sources:
            conversation_id = st.selectbox(
                "Conversation", [source.conversation_id for source in sources], key="configured_conversation",
            )
            source = next(source for source in sources if source.conversation_id == conversation_id)
            validate_dialogue(source)
            with st.expander("Selected original dialogue", expanded=True):
                for turn in source.turns:
                    st.text(f"{turn.speaker} | {turn.block.location}")
                    st.code(turn.block.text, language=None)
                st.caption("Only original customer/agent turns are evidence. Action turns and hidden labels are excluded.")
        else:
            with st.expander("Input preview"):
                st.code(content.decode("utf-8"), language=None)
    except (InvalidInput, UnicodeError) as error:
        input_error = str(error) if isinstance(error, InvalidInput) else "Source must be valid UTF-8."
        if content or pasted or uploaded is not None:
            st.error(input_error)

    if st.button("Create job (no model call)", key="configured_create"):
        st.session_state.pop("configured_notice", None)
        try:
            if input_error:
                raise InvalidInput(input_error)
            profile = load_profile(profile_text.encode("utf-8"))
            with client_scope() as client:
                created = client.prepare(
                    content, kind=kind, profile=profile, split=split, conversation_id=conversation_id,
                )
            st.session_state["configured_job"] = created["job_id"]
            st.session_state["configured_notice"] = "Job created and frozen. No model call was authorized."
            st.rerun()
        except (ConfiguredWorkbenchError, InvalidInput, UnicodeError) as error:
            st.error(str(error) if not isinstance(error, UnicodeError) else "Profile must be valid UTF-8.")

    @st.fragment(run_every=poll_seconds)
    def job_panel() -> None:
        st.button("Refresh status (read only)", key="configured_refresh")
        st.caption(
            f"Status polls every {poll_seconds} seconds while connected, using reads only. "
            "Closing the browser does not stop an authorized backend round."
        )
        protected = st.empty()
        try:
            with client_scope() as client:
                live_configuration = client.configuration()
                catalog = client.jobs()
                with protected.container():
                    _banner(live_configuration)
                    ids = [row["job_id"] for row in catalog]
                    if not ids:
                        st.info("No saved jobs. Create a job to freeze source and profile without extraction.")
                        return
                    if st.session_state.get("configured_job") not in ids:
                        st.session_state["configured_job"] = ids[0]
                    rows = {row["job_id"]: row for row in catalog}
                    job_id = st.selectbox(
                        "Saved jobs", ids, key="configured_job",
                        format_func=lambda value: (
                            f"{value} | {rows[value]['document_id']} | {rows[value]['profile_version']} | "
                            f"revision {rows[value]['revision']} | {rows[value]['status']}"
                        ),
                    )
                    current = client.current(job_id)
                    _show_snapshot(current)
                    snapshot = current["snapshot"]
                    round_view = current.get("round")
                    state = round_view["state"] if round_view else None
                    pending = current.get("pending_request")
                    enabled = live_configuration["enabled"] and live_configuration["remaining_calls"] > 0
                    blocked = (
                        snapshot.get("claim") is not None
                        or snapshot["status"] not in ("ready", "completed", "failed")
                        or state not in (None, "queued", "running", "completed", "failed", "limited")
                    )
                    if pending is not None:
                        st.warning(
                            "A saved request owns this transition. Reads never retry it. Explicit retry sends "
                            "the exact saved request, including its original ID, allowance, and deadline."
                        )
                        st.json({key: pending[key] for key in (
                            "action", "job_id", "request_id", "expected_revision", "max_attempts", "deadline",
                            "previous_run_id", "run_id",
                        ) if key in pending})
                    if blocked:
                        st.error(
                            "Inspection only: unknown or interrupted claim/state. No new work or retry is safe. "
                            "Inspect the backend; do not delete claims."
                        )
                    elif snapshot["status"] == "completed" or state == "completed":
                        st.success("Extraction completed. Read only; all candidates remain Pending.")
                    elif pending is not None:
                        if st.button("Retry saved request", key="configured_retry", disabled=not enabled):
                            st.session_state.pop("configured_notice", None)
                            client.retry(job_id, pending)
                            st.session_state["configured_notice"] = "Saved request acknowledged; no replacement authorization created."
                            st.rerun()
                    else:
                        attempt_limit = max(1, min(5, live_configuration["remaining_calls"]))
                        if st.session_state.get("configured_attempts", 1) > attempt_limit:
                            st.session_state["configured_attempts"] = attempt_limit
                        maximum = st.number_input(
                            "Attempt allowance", min_value=1, max_value=attempt_limit,
                            key="configured_attempts", disabled=not enabled,
                        )
                        duration = st.number_input(
                            "Round time limit (seconds)", min_value=10, max_value=300, value=120,
                            key="configured_duration",
                        )
                        st.caption("Only an explicit Start/Resume click authorizes a bounded round. Reads never renew its deadline.")
                        if state in ("queued", "running"):
                            st.info("The independent backend owns this round. No new authorization is available.")
                        can_start = state is None and snapshot["status"] == "ready"
                        can_resume = state in ("failed", "limited")
                        if st.button(
                            "Start extraction", key="configured_start", disabled=not (enabled and can_start),
                        ):
                            st.session_state.pop("configured_notice", None)
                            client.start(job_id, max_attempts=int(maximum), duration_seconds=int(duration))
                            st.session_state["configured_notice"] = "Start accepted by the independent backend."
                            st.rerun()
                        if st.button(
                            "Resume with a new bounded round", key="configured_resume",
                            disabled=not (enabled and can_resume),
                        ):
                            st.session_state.pop("configured_notice", None)
                            client.resume(current, max_attempts=int(maximum), duration_seconds=int(duration))
                            st.session_state["configured_notice"] = "Resume accepted; earlier committed records are preserved."
                            st.rerun()
                    if notice := st.session_state.pop("configured_notice", None):
                        st.success(notice)
        except ConfiguredWorkbenchError as error:
            protected.empty()
            st.session_state.pop("configured_notice", None)
            st.error(str(error))

    job_panel()
