"""Calibration reports: outcome extraction, slices, summaries and a generated report."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from triagelab.data.models import IssueSnapshot
from triagelab.eval.calibration_report import (
    SLICES,
    CalibrationSpec,
    Outcome,
    _type_answer,  # pyright: ignore[reportPrivateUsage]
    build_report,
    outcomes,
    slices,
    summarise,
)
from triagelab.triage import TriageResult

from .test_runner import _config, _run, workspace  # noqa: F401

TYPES = ["type-bug", "type-crash", "type-feature"]


def snap(body: str, title: str = "t") -> IssueSnapshot:
    return IssueSnapshot(
        issue_ref="o/r#1", repo="o/r", number=1, title=title, body=body,
        author_association="NONE", created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )  # fmt: skip


def test_the_type_answer_is_the_most_confident_type_label() -> None:
    p = TriageResult(
        issue_ref="o/r#1",
        labels=["stdlib", "type-bug", "type-crash"],
        label_confidence={"stdlib": 1.0, "type-bug": 0.6, "type-crash": 0.8},
    )
    assert _type_answer(p, TYPES) == ("type-crash", 0.8)
    assert _type_answer(TriageResult(issue_ref="o/r#1", labels=["stdlib"]), TYPES) == (None, 0.0)


def test_slices() -> None:
    short, logs, foreign = SLICES.values()
    assert short(snap("crash"))
    assert not short(snap("x" * 400))
    assert logs(snap("see:\n```\nTraceback\n  File a\n  File b\nError\n```"))
    assert not logs(snap("one line\n```\ncode\n```\nmore\ntext\nhere\nand here"))
    assert foreign(snap("Пример ошибки при импорте модуля"))
    assert not foreign(snap("An English report about café menus"))


def test_summary_and_slice_tables() -> None:
    rows = [
        Outcome(snap("short"), "a", 0.9, True),
        Outcome(snap("x" * 400), "a", 0.9, False),
        Outcome(snap("y" * 400), "b", 0.5, True),
    ]
    s = summarise("src", "type", rows, cost_per_issue=0.001)
    assert s.n == 3
    assert s.accuracy.point == pytest.approx(2 / 3)
    assert s.mean_confidence == pytest.approx(2.3 / 3)
    by_name = {sl.name: sl for sl in slices(rows)}
    assert by_name["all"].n == 3
    assert by_name["short (body < 300 chars)"].n == 1


def test_a_report_with_figures(workspace: Path, tmp_path: Path) -> None:  # noqa: F811
    run = _run(_config(workspace, "majority")).run_id
    rows = outcomes(workspace / "runs" / run, "silver")
    assert rows["type"]  # majority predicts type-bug, which the synthetic issues carry
    spec = CalibrationSpec(title="t", sources={"majority": run})
    text = build_report(spec, workspace / "runs", "silver", tmp_path / "figs", "spec")
    assert "| majority |" in text
    assert (tmp_path / "figs" / "spec-silver-type-reliability.png").stat().st_size > 1000
    assert (tmp_path / "figs" / "spec-silver-type-risk-coverage.png").is_file()
