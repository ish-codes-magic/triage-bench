"""The failure-review page: a failed issue, truth vs prediction, the agent's trace, and tags."""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import streamlit as st

from triagelab.eval.failures import Failure, find_failures
from triagelab.eval.report import examples_for, load_run
from triagelab.harness.trace_stats import load_events
from triagelab.labeling.failure_tags import FailureTag, FailureTagStore
from triagelab.labeling.gold import LabelingItem, load_items
from triagelab.labeling.settings import AppSettings
from triagelab.labeling.views import show_issue, show_trace

SUBMIT_SHORTCUT = "Ctrl+Enter"


def _runs_dir() -> Path:
    return Path(os.environ.get("TRIAGELAB_RUNS_DIR", "runs"))


def traced_runs(runs_dir: Path) -> list[Path]:
    """Runs with traces (agent runs), newest first."""
    if not runs_dir.is_dir():
        return []
    runs = [
        d
        for d in runs_dir.iterdir()
        if (d / "traces.jsonl").is_file() and (d / "predictions.jsonl").is_file()
    ]
    return sorted(runs, key=lambda d: d.name, reverse=True)


@st.cache_resource(show_spinner="Loading issues...")
def _issues(settings: AppSettings) -> dict[str, LabelingItem]:
    return {i.snapshot.issue_ref: i for i in load_items(settings.data_dir, settings.profile())}


@st.cache_data(show_spinner="Finding failures...")
def _failures(run_dir: str, labels: str) -> tuple[list[Failure], dict[str, list[dict[str, Any]]]]:
    cfg, split, _ = load_run(Path(run_dir))
    predictions, events = load_events(Path(run_dir))
    examples = examples_for(cfg, split, "gold" if labels == "gold" else "silver")
    return find_failures(examples, predictions), dict(events)


def render() -> None:
    settings = AppSettings.from_env()
    runs = traced_runs(_runs_dir())
    if not runs:
        st.info("No agent runs with traces yet: run `triagelab eval` with an agent config.")
        return
    run = st.sidebar.selectbox("Run", runs, format_func=lambda d: d.name, key="review_run")
    labels = st.sidebar.radio("Truth", ["silver", "gold"], horizontal=True, key="review_labels")
    failures, events = _failures(str(run), labels)
    store = FailureTagStore(settings.data_dir)
    tags = store.load()
    tagged = sum(1 for f in failures if (run.name, f.issue_ref) in tags)
    st.sidebar.progress(tagged / max(len(failures), 1), text=f"{tagged}/{len(failures)} tagged")
    if not failures:
        st.success("No failures in this run against these labels.")
        return
    names = [
        f"{'✓' if (run.name, f.issue_ref) in tags else '·'} #{f.issue_ref.rsplit('#', 1)[1]} "
        f"{'/'.join(f.tasks)}"
        for f in failures
    ]
    first_open = next((i for i, f in enumerate(failures) if (run.name, f.issue_ref) not in tags), 0)
    idx = st.sidebar.selectbox(
        "Failure", range(len(failures)), index=first_open, format_func=names.__getitem__,
        key=f"review_idx_{run.name}_{labels}_{tagged}",
    )  # fmt: skip
    failure = failures[idx]
    issue = _issues(settings).get(failure.issue_ref)

    left, right = st.columns([3, 2])
    with left:
        if issue is not None:
            show_issue(issue)
        st.markdown("**Agent trace**")
        show_trace(events.get(failure.trace_id, []))
    with right:
        st.markdown("**What went wrong**")
        for task, detail in failure.details.items():
            st.markdown(f"- **{task}:** {detail}")
        existing = tags.get((run.name, failure.issue_ref))
        with st.form(f"tag_{run.name}_{failure.issue_ref}"):
            codes = st.multiselect(
                "Failure codes",
                store.codes_in_use(),
                default=existing.codes if existing else [],
                accept_new_options=True,  # open coding: invent a code when none fits
                key=f"codes_{run.name}_{failure.issue_ref}",
            )
            note = st.text_area(
                "Note", value=existing.note if existing else "", key=f"note_{failure.issue_ref}"
            )
            if st.form_submit_button("Save and next", shortcut=SUBMIT_SHORTCUT, type="primary"):
                if not codes:
                    st.error("Add at least one code.")
                else:
                    store.save(
                        FailureTag(
                            run_id=run.name,
                            issue_ref=failure.issue_ref,
                            tasks=failure.tasks,
                            codes=[c.strip() for c in codes if c.strip()],
                            note=note,
                            annotator=settings.annotator,
                            tagged_at=datetime.now(UTC),
                        )
                    )
                    st.rerun()
