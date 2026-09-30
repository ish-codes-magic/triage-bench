"""The gold-label page: blind pass on the issue as opened, then adjudication with evidence."""

import time
from datetime import UTC, datetime
from typing import cast

import streamlit as st

from triagelab.labeling.gold import (
    Decision,
    GoldRecord,
    GoldStore,
    LabelingItem,
    gold_path,
    label_vocabulary,
    load_items,
)
from triagelab.labeling.settings import AppSettings
from triagelab.labeling.views import show_evidence, show_issue

CANT_TELL = "(can't tell)"
SUBMIT_SHORTCUT = "Ctrl+Enter"


@st.cache_resource(show_spinner="Loading issues...")
def _load(settings: AppSettings) -> tuple[list[LabelingItem], dict[str, list[str]], list[str]]:
    profile = settings.profile()
    items = load_items(settings.data_dir, profile)
    vocab = label_vocabulary(settings.data_dir, profile)
    return items, vocab, [c.name for c in profile.components]


def _store(settings: AppSettings) -> GoldStore:
    return GoldStore(gold_path(settings.data_dir, settings.profile()))


def _decision_widgets(
    prefix: str,
    vocab: dict[str, list[str]],
    components: list[str],
    start: Decision,
    *,
    ask_duplicate: bool,
) -> tuple[Decision | None, str | None]:
    """Render the label widgets; returns the decision, or an error message."""
    types = [x for x in start.labels if x in vocab["type"]]
    kind = st.radio(
        "Type (exactly one)",
        vocab["type"],
        index=vocab["type"].index(types[0]) if types else None,
        horizontal=True,
        key=f"{prefix}_type",
    )
    areas = st.pills(
        "Areas",
        vocab["area"],
        selection_mode="multi",
        default=[x for x in start.labels if x in vocab["area"]],
        key=f"{prefix}_area",
    )
    family = st.multiselect(
        "Topic and OS labels",
        vocab["family"],
        default=[x for x in start.labels if x in vocab["family"]],
        key=f"{prefix}_family",
    )
    options = [*components, CANT_TELL]
    component = st.radio(
        "Component a fix would change",
        options,
        index=options.index(start.component) if start.component in options else len(options) - 1,
        horizontal=True,
        key=f"{prefix}_component",
    )
    needs_info = st.toggle(
        "The reporter must provide more information",
        value=start.needs_info,
        key=f"{prefix}_needs_info",
    )
    duplicate_of: int | None = None
    if ask_duplicate:
        raw = st.text_input(
            "Duplicate of (issue number, blank if not a duplicate)",
            value=str(start.duplicate_of or ""),
            key=f"{prefix}_duplicate",
        ).strip()
        if raw and not raw.lstrip("#").isdigit():
            return None, f"'{raw}' is not an issue number."
        duplicate_of = int(raw.lstrip("#")) if raw else None
    if kind is None:
        return None, "Choose a type label."
    decision = Decision(
        labels=[kind, *areas, *family],
        component=None if component == CANT_TELL else component,
        needs_info=needs_info,
        duplicate_of=duplicate_of,
    )
    return decision, None


def _next_open(items: list[LabelingItem], done: dict[str, GoldRecord], after: int) -> int:
    order = list(range(after + 1, len(items))) + list(range(0, after + 1))
    for i in order:
        record = done.get(items[i].snapshot.issue_ref)
        if record is None or record.final is None:
            return i
    return after


def render() -> None:
    settings = AppSettings.from_env()
    all_items, vocab, components = _load(settings)
    store = _store(settings)
    done = store.load()

    split = st.sidebar.radio("Split", ["dev", "test"], horizontal=True, key="gold_split")
    items = [i for i in all_items if i.split == split]
    finished = sum(1 for i in items if (r := done.get(i.snapshot.issue_ref)) and r.final)
    st.sidebar.progress(finished / max(len(items), 1), text=f"{finished}/{len(items)} adjudicated")
    if not items:
        st.info(f"No {split} issues found.")
        return
    key = f"gold_idx_{split}"
    if key not in st.session_state:
        st.session_state[key] = _next_open(items, done, -1)
    idx = cast(int, st.session_state[key])
    labels = [
        f"{'✓' if (r := done.get(i.snapshot.issue_ref)) and r.final else '·'} #{i.snapshot.number}"
        for i in items
    ]
    chosen = st.sidebar.selectbox(
        "Issue", range(len(items)), index=idx, format_func=labels.__getitem__
    )
    if chosen != idx:
        st.session_state[key] = idx = chosen
    item = items[idx]
    record = done.get(item.snapshot.issue_ref)
    started = st.session_state.setdefault(f"started_{item.snapshot.number}", time.time())

    left, right = st.columns([3, 2])
    with left:
        show_issue(item)
    with right:
        if record is None:
            st.markdown("**Blind pass:** label from the issue alone, as the systems see it.")
            with st.form(f"blind_{item.snapshot.number}"):
                decision, error = _decision_widgets(
                    f"blind_{item.snapshot.number}",
                    vocab,
                    components,
                    Decision(),
                    ask_duplicate=False,
                )
                if st.form_submit_button(
                    "Save and reveal", shortcut=SUBMIT_SHORTCUT, type="primary"
                ):
                    if decision is None:
                        st.error(error)
                    else:
                        store.save(
                            GoldRecord(
                                issue_ref=item.snapshot.issue_ref,
                                number=item.snapshot.number,
                                split=item.split,
                                blind=decision,
                                annotator=settings.annotator,
                                blind_seconds=round(time.time() - started, 1),
                                updated_at=datetime.now(UTC),
                            )
                        )
                        st.rerun()
            return
        show_evidence(item.evidence)
        st.markdown("**Final pass:** the gold answer, given everything above.")
        start = record.final or record.blind.model_copy(
            update={"duplicate_of": item.evidence.duplicate_of}
        )
        with st.form(f"final_{item.snapshot.number}"):
            decision, error = _decision_widgets(
                f"final_{item.snapshot.number}", vocab, components, start, ask_duplicate=True
            )
            unusable = st.checkbox(
                "Unusable (spam, not an issue, can't judge)",
                value=record.unusable,
                key=f"unusable_{item.snapshot.number}",
            )
            notes = st.text_area("Notes", value=record.notes, key=f"notes_{item.snapshot.number}")
            if st.form_submit_button(
                "Save gold and next", shortcut=SUBMIT_SHORTCUT, type="primary"
            ):
                if decision is None:
                    st.error(error)
                else:
                    store.save(
                        record.model_copy(
                            update={
                                "final": decision,
                                "unusable": unusable,
                                "notes": notes,
                                "updated_at": datetime.now(UTC),
                            }
                        )
                    )
                    st.session_state[key] = _next_open(items, store.load(), idx)
                    st.rerun()
