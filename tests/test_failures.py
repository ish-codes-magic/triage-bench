"""Failure detection per task, with human-readable differences."""

from datetime import UTC, datetime

from triagelab.data.models import IssueSnapshot
from triagelab.eval.dataset import EvalExample, Gold
from triagelab.eval.failures import find_failures
from triagelab.triage import TriageResult


def example(
    n: int,
    labels: set[str],
    *,
    component: str | None = "stdlib",
    dup: int | None = None,
    needs_info: bool = False,
    triaged: bool = True,
) -> EvalExample:
    snapshot = IssueSnapshot(
        issue_ref=f"o/r#{n}", repo="o/r", number=n, title="t", body="b",
        author_association="NONE", created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )  # fmt: skip
    gold = Gold(
        labels=frozenset(labels), label_groups=dict.fromkeys(labels, "area"),
        human_triaged=triaged, duplicate_of=dup, component=component, needs_info=needs_info,
    )  # fmt: skip
    return EvalExample(snapshot=snapshot, gold=gold, split="dev", weight=1.0)


def test_each_task_reports_what_differed() -> None:
    examples = [
        example(1, {"type-bug", "stdlib"}),  # all right
        example(2, {"type-bug", "stdlib"}, dup=1),  # labels and duplicate wrong
        example(3, {"docs"}, component="docs", needs_info=True),  # component, needs-info wrong
        example(4, {"x"}, component=None, triaged=False),  # nothing scorable is wrong
    ]
    predictions = [
        TriageResult(
            issue_ref="o/r#1", labels=["type-bug", "stdlib"], component="stdlib", trace_id="t1"
        ),
        TriageResult(
            issue_ref="o/r#2",
            labels=["type-bug", "docs"],
            component="stdlib",
            duplicate_candidates=[1],
            trace_id="t2",
        ),
        TriageResult(issue_ref="o/r#3", labels=["docs"], component="stdlib", trace_id="t3"),
        TriageResult(issue_ref="o/r#4", labels=["y"], component="docs", trace_id="t4"),
    ]
    failures = {f.issue_ref: f for f in find_failures(examples, predictions)}
    assert set(failures) == {"o/r#2", "o/r#3"}
    assert failures["o/r#2"].details == {
        "T1": "missing: stdlib; extra: docs",
        "T2": "missed duplicate of #1 (among candidates)",
    }
    assert failures["o/r#3"].tasks == ["T3", "T4"]
    assert failures["o/r#3"].details["T4"] == "missed that it needed info"
    assert failures["o/r#2"].trace_id == "t2"
