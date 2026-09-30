"""The judge-rating page: score triage comments on the rubric, blind to which system wrote them."""

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from triagelab.labeling.gold import LabelingItem, load_items
from triagelab.labeling.ratings import Rating, RatingItem, RatingStore, Rubric, load_rubric
from triagelab.labeling.settings import AppSettings
from triagelab.labeling.views import show_evidence, show_issue

SUBMIT_SHORTCUT = "Ctrl+Enter"


@st.cache_resource(show_spinner="Loading issues...")
def _issues(settings: AppSettings) -> dict[str, LabelingItem]:
    return {i.snapshot.issue_ref: i for i in load_items(settings.data_dir, settings.profile())}


def _rubric() -> Rubric:
    return load_rubric(Path(os.environ.get("TRIAGELAB_RUBRIC", "configs/judge/rubric.yaml")))


def _next_unrated(items: list[RatingItem], rated: set[str]) -> int | None:
    return next((i for i, item in enumerate(items) if item.item_id not in rated), None)


def render() -> None:
    settings = AppSettings.from_env()
    store = RatingStore(settings.data_dir)
    items = store.items()
    if not items:
        st.info("No comments to rate yet: run `triagelab judge sample` first.")
        return
    rubric = _rubric()
    ratings = store.ratings()
    st.sidebar.progress(len(ratings) / len(items), text=f"{len(ratings)}/{len(items)} rated")
    idx = _next_unrated(items, set(ratings))
    if idx is None:
        st.success("Every comment is rated. Thank you!")
        return
    item = items[idx]
    issue = _issues(settings)[item.issue_ref]
    started = st.session_state.setdefault(f"rate_started_{item.item_id}", time.time())

    left, right = st.columns([3, 2])
    with left:
        show_issue(issue)
        show_evidence(issue.evidence)
    with right:
        st.markdown("**Draft triage comment** (the system that wrote it is hidden)")
        with st.container(border=True):
            st.text(item.comment)
        with st.form(f"rate_{item.item_id}"):
            scores: dict[str, int | None] = {}
            for c in rubric.criteria:
                scores[c.name] = st.segmented_control(
                    f"{c.name.capitalize()}: {c.question}",
                    rubric.scale,
                    key=f"rate_{item.item_id}_{c.name}",
                )
                st.caption(" · ".join(f"**{level}** {text}" for level, text in c.levels.items()))
            if st.form_submit_button("Save and next", shortcut=SUBMIT_SHORTCUT, type="primary"):
                missing = [name for name, score in scores.items() if score is None]
                if missing:
                    st.error(f"Score every criterion (missing: {', '.join(missing)}).")
                else:
                    store.save(
                        Rating(
                            item_id=item.item_id,
                            scores={k: int(v) for k, v in scores.items() if v is not None},
                            rubric_version=rubric.version,
                            annotator=settings.annotator,
                            seconds=round(time.time() - started, 1),
                            rated_at=datetime.now(UTC),
                        )
                    )
                    st.rerun()
