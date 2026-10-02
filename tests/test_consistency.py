"""Consistency metrics, checked against cases small enough to count by hand."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from triagelab.data.models import IssueSnapshot
from triagelab.data.profile import load_profile
from triagelab.eval.consistency import (
    ConsistencySpec,
    Group,
    accuracy,
    build_report,
    decisions,
    ever_right,
    pass_k,
    unanimous,
)
from triagelab.eval.dataset import EvalExample, Gold
from triagelab.eval.report import load_scored_runs
from triagelab.triage import TriageResult

from .fakes import FakeBackend
from .test_runner import PROFILE_PATH, _config, _run, fake_llm, workspace  # noqa: F401

PROFILE = load_profile(PROFILE_PATH)

# 4 issues, 3 runs each:   always right | right twice | right once | never right
CORRECT = [(True, True, True), (True, True, False), (False, True, False), (False, False, False)]


def test_the_three_accuracies_by_hand() -> None:
    assert accuracy(CORRECT) == pytest.approx(6 / 12)  # 3 + 2 + 1 + 0 correct cells
    assert pass_k(CORRECT) == pytest.approx(1 / 4)  # only the first issue
    assert ever_right(CORRECT) == pytest.approx(3 / 4)  # all but the last
    # The ordering always holds: 0.25 <= 0.50 <= 0.75 here.


def test_one_run_makes_all_three_equal() -> None:
    single = [(True,), (False,), (True,)]
    assert accuracy(single) == pass_k(single) == ever_right(single) == pytest.approx(2 / 3)


def test_unanimous_counts_agreement_not_correctness() -> None:
    answers = [("bug", "bug", "bug"), ("bug", "crash", "bug"), (None, None, None)]
    assert unanimous(answers) == pytest.approx(2 / 3)  # consistently wrong still agrees


def test_empty_inputs_have_no_value() -> None:
    assert accuracy([]) is None
    assert pass_k([]) is None
    assert ever_right([]) is None
    assert unanimous([]) is None


def example(number: int, labels: set[str], component: str | None) -> EvalExample:
    snapshot = IssueSnapshot(
        issue_ref=f"o/r#{number}", repo="o/r", number=number, title="t", body="b",
        author_association="NONE", created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )  # fmt: skip
    gold = Gold(
        labels=frozenset(labels), label_groups={}, human_triaged=True, duplicate_of=None,
        component=component, needs_info=False,
    )  # fmt: skip
    return EvalExample(snapshot=snapshot, gold=gold, split="dev", weight=1.0)


def result(number: int, labels: list[str], component: str | None) -> TriageResult:
    return TriageResult(issue_ref=f"o/r#{number}", labels=labels, component=component)


def test_decisions_line_up_answers_across_runs() -> None:
    examples = [
        example(1, {"type-bug", "stdlib"}, "stdlib"),
        example(2, {"type-feature"}, None),  # no reference component: not scored there
        example(3, {"type-bug"}, "docs"),  # missing from the second run: dropped everywhere
    ]
    first = {
        "o/r#1": result(1, ["type-bug", "stdlib"], "stdlib"),
        "o/r#2": result(2, ["type-feature"], "docs"),
        "o/r#3": result(3, ["type-bug"], "docs"),
    }
    second = {
        "o/r#1": result(1, ["type-crash", "stdlib"], "stdlib"),
        "o/r#2": result(2, ["type-feature"], "tests"),
    }
    by_name = {d.name: d for d in decisions(examples, [first, second], PROFILE)}
    kind = by_name["type label"]
    assert kind.answers == [(("type-bug",), ("type-crash",)), (("type-feature",),) * 2]
    assert kind.correct() == [(True, False), (True, True)]
    assert by_name["all labels (exact set)"].correct() == [(True, False), (True, True)]
    component = by_name["component"]
    assert component.answers == [("stdlib", "stdlib")]  # issue 2 has no reference component
    assert component.correct() == [(True, True)]
    assert by_name["duplicate link"].correct() == [(True, True), (True, True)]


def test_the_report_reads_repeated_runs_from_the_registry(
    workspace: Path,  # noqa: F811
    fake_llm: FakeBackend,  # noqa: F811
) -> None:
    cfg = _config(workspace, "llm_single_shot", name="e-llm")
    runs = [_run(cfg), _run(cfg, sample=1), _run(cfg, sample=2)]
    spec = ConsistencySpec(title="t", groups=[Group(name="llm", runs=[r.run_id for r in runs])])
    table = build_report(spec, workspace / "runs", "silver", resamples=50)
    row = next(line for line in table.splitlines() if line.startswith("| llm | type label |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[2:4] == ["3", "5"]  # k runs, the 5 dev issues
    assert cells[8].startswith("1.00")  # a fake model gives the same answer every time
    assert len(load_scored_runs(workspace / "runs")) == 3
