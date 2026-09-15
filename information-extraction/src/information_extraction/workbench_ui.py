"""Shared presentation; all protected content belongs to the guarded fragment."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import streamlit as st

from information_extraction.batch import BatchState
from information_extraction.sample import synthetic_plan
from information_extraction.workbench_client import RoundView, WorkbenchError

if TYPE_CHECKING:
    from information_extraction.workbench_client import Workbench

plan = synthetic_plan()


def show_round(current: RoundView) -> None:
    st.subheader("Current job")
    state, revision, attempts = st.columns(3)
    state.metric("Round state", current.state.value)
    revision.metric("Committed revision", current.revision)
    attempts.metric("Attempts reserved this round", f"{current.attempts_reserved} / {current.max_attempts}")
    st.progress(len(current.completed_chunks) / len(plan.chunks))
    st.caption(
        f"{len(current.completed_chunks)} / {len(plan.chunks)} chunks committed | "
        f"{current.committed_attempts} committed attempts overall | "
        f"Execution: {current.execution_state.value}"
    )
    st.caption(
        f"Run: {current.run_id} | Deadline (UTC): "
        f"{datetime.fromtimestamp(current.deadline, timezone.utc).isoformat()} | "
        f"Native registration confirmed: {current.registration_confirmed}"
    )
    st.caption(
        f"Known tokens: {current.known_input_tokens} input / {current.known_output_tokens} output | "
        f"Attempts with unknown usage: {current.unknown_usage_attempts}. Synthetic counts, not billing."
    )
    if current.candidates:
        st.subheader("Candidate records")
        st.warning("Pending review. Structural validation is not semantic correctness or human approval.")
        st.table([{
            "Metric": candidate.metric, "Value": candidate.value,
            "Unit": candidate.unit, "Review": "Pending",
        } for candidate in current.candidates])
        for candidate in current.candidates:
            with st.expander(f"Evidence: {candidate.metric} = {candidate.value} {candidate.unit}"):
                st.caption(f"Candidate: {candidate.id}")
                for evidence in candidate.evidence:
                    st.caption(f"{evidence.block_id} | {evidence.location}")
                    st.code(evidence.text, language=None)
    else:
        st.caption("No committed candidate records yet.")


def render_workbench(
    client_scope: Callable[[], AbstractContextManager["Workbench"]], *,
    authorize: Callable[[], None] | None = None,
    poll_seconds: int = 2, on_error: Callable[[], None] | None = None,
) -> None:
    @st.fragment(run_every=poll_seconds)
    def job_panel() -> None:
        protected = st.empty()
        try:
            if authorize is not None:
                authorize()
            with client_scope() as client:
                job = client.current()
                if authorize is not None:
                    authorize()
                with protected.container():
                    st.caption(
                        "One fictional financial sample, one durable job. Candidates are unreviewed; "
                        "this preview does not approve records or answer business questions."
                    )
                    st.selectbox("Sample document", ["ExampleCo - fictional financial statements"])
                    with st.expander("Source blocks"):
                        for chunk in plan.chunks:
                            for block in chunk.blocks:
                                st.caption(f"{block.id} | {block.location}")
                                st.code(block.text, language=None)
                    st.button("Refresh status (read only)", key="refresh")
                    st.caption(
                        f"Status refreshes every {poll_seconds} seconds while this page is connected. "
                        "Reads never start work."
                    )
                    st.caption(f"Job: {job.job_id} | Backend instance: {job.app_instance_id}")
                    if notice := st.session_state.pop("notice", None):
                        st.success(notice)
                    if job.round is not None:
                        show_round(job.round)
                    if job.round is not None and job.round.state.value == "in_progress_or_interrupted":
                        st.error(
                            "Inspection only: an attempt may still be active or may have been interrupted. "
                            "No new round is safe to authorize. Inspect the backend; do not delete its claims."
                        )
                        return
                    if job.pending is not None:
                        st.warning(
                            "A saved request already owns this transition. Reads do not retry it. "
                            "An explicit retry preserves its request ID, attempt allowance, and original deadline."
                        )
                        st.json(job.pending.body())
                        if st.button("Retry saved request", key="retry"):
                            client.retry(job.pending)
                            st.session_state["notice"] = "Saved request acknowledged; no new authorization was created."
                            st.rerun()
                    elif job.round is not None and job.round.state == BatchState.COMPLETED:
                        st.success("Extraction completed. Candidate records still require human review.")
                    elif job.round is not None and job.round.state not in (BatchState.LIMITED, BatchState.FAILED):
                        st.info("The independent backend owns this round. You can close and reopen this page.")
                    can_start = job.round is None and job.pending is None
                    can_resume = (
                        job.round is not None and job.pending is None
                        and job.round.state in (BatchState.LIMITED, BatchState.FAILED)
                    )
                    if can_start or can_resume:
                        st.subheader("Authorize one bounded round")
                        maximum = st.number_input("Attempt allowance", min_value=1, max_value=5, value=1, key="attempts")
                        duration = st.number_input(
                            "Round time limit (seconds)", min_value=10, max_value=300, value=120, key="duration",
                        )
                        st.caption("Only a button click authorizes work. Refreshing or reopening never renews a budget.")
                        if can_start and st.button("Start extraction", key="start", type="primary"):
                            client.start(job.job_id, max_attempts=maximum, duration_seconds=duration)
                            st.session_state["notice"] = "Start accepted. Progress is stored by the independent backend."
                            st.rerun()
                        if can_resume and job.round is not None and st.button("Resume with a new bounded round", key="resume", type="primary"):
                            client.resume(job.round, max_attempts=maximum, duration_seconds=duration)
                            st.session_state["notice"] = "Resume accepted. Earlier committed records are preserved."
                            st.rerun()
        except WorkbenchError as error:
            protected.empty()
            st.session_state.pop("notice", None)
            st.error(str(error))
            if on_error is not None:
                on_error()

    job_panel()
