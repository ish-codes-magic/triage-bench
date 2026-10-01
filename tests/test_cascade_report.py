"""The cascade report end to end on stored runs (tiers and gates from the run registry)."""

from pathlib import Path

from triagelab.eval.cascade_report import CascadeSpec, GateSpec, build_cascade_report

from .test_runner import _config, _run, workspace  # noqa: F401


def test_a_cascade_report_from_stored_runs(workspace: Path, tmp_path: Path) -> None:  # noqa: F811
    cheap = _run(_config(workspace, "majority", name="cheap")).run_id
    full = _run(_config(workspace, "majority", name="full")).run_id
    spec = CascadeSpec(
        title="t",
        cheap=cheap,
        full=full,
        gates={"self": GateSpec(kind="self"), "agree": GateSpec(kind="agreement", run=full)},
        metrics=["t1_micro_f1"],
        decision_backends={"same": cheap},
    )
    text = build_cascade_report(spec, workspace / "runs", "silver", tmp_path / "figs", "e7")
    assert "| cheap tier alone |" in text
    assert "| full agent alone |" in text
    assert "| self, cross-fitted" in text
    assert "| agree | t1_micro_f1 | +0.000" in text  # identical tiers: no difference
    assert (tmp_path / "figs" / "e7-silver-cascade.png").stat().st_size > 1000
    assert "## Decision level (H3)" in text
    assert "| type | agent alone |" in text
