"""Display pieces shared by the labeling pages."""

from typing import Any

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


def show_trace(events: list[dict[str, Any]]) -> None:
    """An agent trace, step by step: the model's calls, reasoning and what tools returned."""
    for e in events:
        kind = e.get("event")
        if kind == "llm":
            calls = ", ".join(c["name"] for c in e.get("tool_calls", [])) or "(text reply)"
            forced = f" · forced {e['tool_choice']}" if e.get("tool_choice") else ""
            st.markdown(f"**Step {e['step']}** → {calls}{forced}")
            if e.get("reasoning"):
                with st.expander("reasoning"):
                    st.text(str(e["reasoning"])[:4000])
            for call in e.get("tool_calls", []):
                if call["name"] == "submit_triage":
                    with st.expander("submitted answer"):
                        st.code(str(call["arguments"])[:4000], language="json")
        elif kind == "tool":
            status = "error" if e.get("is_error") else "ok"
            with st.expander(f"{e['name']}({str(e.get('arguments'))[:80]}) → {status}"):
                st.text(str(e.get("output", ""))[:3000])
        elif kind in ("compaction", "validation_error"):
            st.caption(f"{kind}: {str(e.get('error', e))[:300]}")
        elif kind == "end":
            st.caption(f"stopped: {e.get('stop_reason')} (forced: {e.get('forced')})")
