"""The regression gate: verdict rules, baselines, the fixed subset and the eval pack."""

from pathlib import Path

import pytest

from triagelab.config import load_config, read_subset
from triagelab.data.storage import read_jsonl
from triagelab.eval.gate import (
    GateConfig,
    GateRule,
    _metric_row,
    bless,
    check,
    load_gate_config,
    pick_subset,
    render,
)
from triagelab.eval.report import DeltaRow
from triagelab.eval.score import METRICS
from triagelab.triage import TriageResult

from .test_runner import PROFILE_PATH, _config, _run, workspace  # noqa: F401

GATE = GateConfig(
    labels="silver",
    rules=[GateRule(metric="t1_micro_f1", max_drop=0.05)],
    report_metrics=["t3_accuracy"],
    max_cost_increase=0.3,
    max_error_rate=0.1,
)


def _delta(delta: float, significant: bool = False) -> DeltaRow:
    return DeltaRow(
        metric="m", a=0.7, b=0.7 + delta, delta=delta, low=delta - 0.1, high=delta + 0.1,
        significant=significant,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("delta", "significant", "verdict"),
    [
        (-0.06, False, "fail"),  # beyond the threshold, significant or not
        (-0.04, True, "warn"),  # a real but tolerated drop
        (-0.04, False, "pass"),  # within noise and threshold
        (0.10, True, "pass"),  # improvements never fail
    ],
)
def test_metric_verdicts(delta: float, significant: bool, verdict: str) -> None:
    rule = GateRule(metric="m", max_drop=0.05)
    assert _metric_row(_delta(delta, significant), rule).verdict == verdict
    assert _metric_row(_delta(delta, significant), None).verdict == "pass"  # report-only


def test_identical_runs_pass_and_a_regression_fails(workspace: Path) -> None:  # noqa: F811
    base = _run(_config(workspace, "majority", name="gate-a")).run_dir
    cand = _run(_config(workspace, "majority", name="gate-b")).run_dir
    blessed = workspace / "baseline"
    bless(base, blessed)
    assert not (blessed / "traces.jsonl").exists()

    report = check(blessed, cand, GATE)
    assert report.verdict == "pass"
    assert report.baseline_run == base.name  # the recorded id, not the folder name
    assert "### Regression gate: PASS" in render(report)

    # Break the candidate: no labels at all.
    preds = read_jsonl(cand / "predictions.jsonl", TriageResult)
    (cand / "predictions.jsonl").write_bytes(
        "".join(
            p.model_copy(update={"labels": []}).model_dump_json() + "\n" for p in preds
        ).encode()
    )
    report = check(blessed, cand, GATE)
    assert report.verdict == "fail"
    assert next(r for r in report.rows if r.metric == "t1_micro_f1").verdict == "fail"
    assert "**FAIL**" in render(report)


def test_a_candidate_that_misses_issues_fails(workspace: Path) -> None:  # noqa: F811
    base = _run(_config(workspace, "majority", name="gate-a")).run_dir
    partial = _run(_config(workspace, "majority", name="gate-b"), limit=2).run_dir
    report = check(base, partial, GATE)
    assert report.verdict == "fail"
    assert report.rows[0].metric == "coverage"
    assert report.rows[0].verdict == "fail"


def test_unknown_gate_metrics_are_rejected(workspace: Path) -> None:  # noqa: F811
    run = _run(_config(workspace, "majority")).run_dir
    bad = GATE.model_copy(update={"rules": [GateRule(metric="t9_vibes", max_drop=0.1)]})
    with pytest.raises(ValueError, match="t9_vibes"):
        check(run, run, bad)


def test_pick_subset_is_stable_and_order_free() -> None:
    refs = [f"o/r#{n}" for n in range(1, 101)]
    chosen = pick_subset(refs, 10)
    assert len(chosen) == 10
    assert chosen == pick_subset(list(reversed(refs)), 10)
    assert chosen == sorted(chosen, key=lambda r: int(r.split("#")[1]))
    # Adding one issue changes the subset by at most one issue.
    assert len(set(chosen) - set(pick_subset([*refs, "o/r#101"], 10))) <= 1


def test_the_committed_gate_names_real_metrics_and_a_fixed_subset() -> None:
    root = Path(__file__).resolve().parents[1]
    gate = load_gate_config(root / "configs" / "gate" / "gate.yaml")
    assert {r.metric for r in gate.rules} | set(gate.report_metrics) <= set(METRICS)
    refs = read_subset(root / "configs" / "gate" / "dev-subset.txt")
    assert len(refs) == len(set(refs)) == 50
    cfg = load_config(root / "configs" / "gate" / "agent.yaml")
    assert cfg.eval.subset == Path("configs/gate/dev-subset.txt")
