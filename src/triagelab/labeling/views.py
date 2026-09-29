"""Display pieces shared by the labeling pages."""

import streamlit as st

from triagelab.labeling.gold import Evidence, LabelingItem


def show_issue(item: LabelingItem) -> None:
    s = item.snapshot
    st.subheader(f"#{s.number} · {s.title}")
    st.caption(f"{item.split} · opened {s.created_at:%Y-%m-%d} · author: {s.author_association}")
    with st.container(height=420):
        # Plain text: issue bodies are untrusted, and Markdown would render links/images.
        st.text(s.body or "(empty body)")


def show_evidence(ev: Evidence) -> None:
    st.markdown("**What happened next**")
    st.link_button("Open the issue on GitHub", ev.url)
    labels = ", ".join(f"`{label}` ({source})" for label, source in ev.labels) or "none"
    st.markdown(f"- **Labels applied:** {labels}")
    pending = f" (from {ev.needs_info_at:%Y-%m-%d})" if ev.needs_info_at else ""
    st.markdown(f"- **`pending` (needs info):** {'yes' + pending if ev.needs_info else 'no'}")
    if ev.duplicate_of:
        st.markdown(
            f"- **Closed as a duplicate of** #{ev.duplicate_of} "
            f"({ev.duplicate_source}): {ev.duplicate_title or '(title unknown)'}"
        )
    votes = ", ".join(f"{c} {v:.2f}" for c, v in ev.component_votes.items()) or "no fix found"
    st.markdown(f"- **Derived component:** `{ev.component}` · votes: {votes}")
    for pr in ev.fix_prs:
        with st.expander(f"Fix PR #{pr.number}: {pr.title} ({pr.files_total} files)"):
            st.code("\n".join(pr.files) or "(files unknown)", language=None)
