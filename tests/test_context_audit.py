"""The context audit: what a run's traces may and may not show about past issues."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from triagelab.data.models import Actor, IssueSnapshot, LabelEvent
from triagelab.eval.context_audit import audit_run, pasted, render, returned
from triagelab.retrieval.corpus import Corpus, IndexedIssue

T0 = datetime(2026, 6, 1, tzinfo=UTC)
TRIAGER = Actor(login="triager", is_bot=False)


def indexed(number: int, created: datetime, *labels: tuple[str, datetime]) -> IndexedIssue:
    return IndexedIssue(
        number=number, url=f"https://example.test/{number}", created_at=created,
        title=f"issue {number}", body="body", title_renames=(), state_events=(),
        label_events=tuple(
            LabelEvent(at=at, label=name, added=True, actor=TRIAGER) for name, at in labels
        ),
    )  # fmt: skip


# #1 is old, and gets `type-bug` before the triaged issue and `stdlib` only after it.
# #3 is opened after the triaged issue (#2).
CORPUS = Corpus(
    [
        indexed(1, T0, ("type-bug", T0 + timedelta(hours=1)), ("stdlib", T0 + timedelta(days=9))),
        indexed(2, T0 + timedelta(days=5)),
        indexed(3, T0 + timedelta(days=7)),
    ]
)
ISSUE = IssueSnapshot(
    issue_ref="o/r#2", repo="o/r", number=2, title="t", body="b",
    author_association="NONE", created_at=T0 + timedelta(days=5),
)  # fmt: skip


def stuffed(*rows: str) -> dict[str, Any]:
    block = "<similar_issues>\nEarlier issues:\n" + "\n".join(rows) + "\n</similar_issues>"
    message = {"role": "user", "content": "the issue\n\n" + block}
    return {"issue_ref": "o/r#2", "event": "llm", "step": 1, "new_messages": [message]}


def tool(name: str, output: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"issue_ref": "o/r#2", "event": "tool", "name": name, "output": output,
            "is_error": is_error}  # fmt: skip


def run(tmp_path: Path, *events: dict[str, Any]) -> Path:
    path = tmp_path / "traces.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return path


def test_parsers_read_both_ways_an_issue_reaches_the_model() -> None:
    rows = "- #1 [open; labels: stdlib, type-bug] a: b\n- #9 [closed; labels: none] c: d"
    block = f"<similar_issues>\n{rows}\n</similar_issues>"
    assert [(s.number, s.labels) for s in pasted(block)] == [(1, ("stdlib", "type-bug")), (9, ())]
    results = json.dumps({"as_of": "x", "results": [{"number": 1, "labels": ["type-bug"]}]})
    found = returned("search_similar_issues", results + "\n[tool calls used: 1 of 15]")
    assert [(s.number, s.labels) for s in found] == [(1, ("type-bug",))]
    cut = '{"number": 1, "url": "u", "body": "a long body that was trunc'
    assert [(s.number, s.labels) for s in returned("get_issue", cut)] == [(1, None)]


def test_a_run_that_only_saw_the_past_is_clean(tmp_path: Path) -> None:
    traces = run(
        tmp_path,
        stuffed("- #1 [open; labels: type-bug] issue 1: body"),
        tool("get_issue", json.dumps({"number": 1, "labels": ["type-bug"]})),
        tool("get_issue", "not available as of ...", is_error=True),  # a refusal shows nothing
        {"issue_ref": "o/r#2", "event": "end"},
    )
    audit = audit_run(traces, {"o/r#2": ISSUE}, CORPUS)
    assert audit.clean
    assert (audit.issues, audit.shown) == (1, 2)
    assert "clean" in render(audit, "run-1")


def test_each_kind_of_leak_is_counted(tmp_path: Path) -> None:
    traces = run(
        tmp_path,
        stuffed(
            "- #2 [open; labels: none] the issue itself: body",
            "- #3 [open; labels: none] opened later: body",
            "- #1 [open; labels: stdlib, type-bug] a label from the future: body",
        ),
        tool("get_issue", json.dumps({"number": 77, "labels": []})),  # not in the corpus
    )
    audit = audit_run(traces, {"o/r#2": ISSUE}, CORPUS)
    assert not audit.clean
    assert (audit.itself, audit.not_visible, audit.wrong_labels) == (1, 2, 1)
    assert "LEAK" in render(audit, "run-1")


def test_truncated_results_are_counted_but_not_called_leaks(tmp_path: Path) -> None:
    traces = run(tmp_path, tool("get_issue", '{"number": 1, "url": "u", "body": "cut he'))
    audit = audit_run(traces, {"o/r#2": ISSUE}, CORPUS)
    assert audit.clean
    assert audit.labels_unchecked == 1
