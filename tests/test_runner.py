"""Runner tests on a small synthetic dataset built with the real build pipeline."""

import json
from pathlib import Path

import pytest

from triagelab import wiring
from triagelab.config import Config, load_config
from triagelab.data.build import build_dataset
from triagelab.data.collect import raw_paths
from triagelab.data.profile import load_profile
from triagelab.data.splits import Split
from triagelab.data.storage import append_jsonl, read_jsonl
from triagelab.eval.dataset import load_split
from triagelab.eval.report import (
    Comparison,
    DeltaSpec,
    compare_runs,
    deltas_table,
    load_scored_runs,
    rescore_on_gold,
    results_table,
)
from triagelab.eval.runner import RunOutcome, TestSetLockedError, run_eval
from triagelab.labeling.gold import Decision, GoldRecord, GoldStore, gold_path
from triagelab.llm_client import LLMClient
from triagelab.triage import TriageResult

from .fakes import FakeBackend
from .test_build import FIXED_NOW, _issues

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO_ROOT / "configs" / "repos" / "python__cpython.yaml"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    profile = load_profile(PROFILE_PATH)
    issues_path, _ = raw_paths(tmp_path / "data", profile)
    append_jsonl(issues_path, _issues())
    build_dataset(profile, tmp_path / "data", tmp_path / "reports", now=lambda: FIXED_NOW)
    return tmp_path


def _config(ws: Path, kind: str, *, per_run_usd: float = 5.0, name: str | None = None) -> Config:
    cfg = load_config(REPO_ROOT / "configs" / "base.yaml")
    return cfg.model_validate(
        {
            **cfg.model_dump(),
            "name": name or f"test-{kind}",
            "system": {"kind": kind},
            "budget": {"usd_total": 150.0, "usd_per_run": per_run_usd},
            "cache": {"enabled": False, "dir": str(ws / "cache")},
            "paths": {
                "runs_dir": str(ws / "runs"),
                "prices_file": str(REPO_ROOT / "configs" / "prices.yaml"),
                "ledger_file": str(ws / "runs" / "ledger.jsonl"),
            },
            "dataset": {
                "profile": str(PROFILE_PATH),
                "data_dir": str(ws / "data"),
                "reports_dir": str(ws / "reports"),
            },
            "eval": {"concurrency": 3, "bootstrap_resamples": 100},
        }
    )


def _run(
    cfg: Config,
    split: Split = "dev",
    *,
    limit: int | None = None,
    allow_test: bool = False,
    resume_dir: Path | None = None,
) -> RunOutcome:
    return run_eval(
        cfg,
        split=split,
        runs_dir=cfg.paths.runs_dir,
        command="test",
        log=lambda _: None,
        limit=limit,
        allow_test=allow_test,
        resume_dir=resume_dir,
    )


def test_majority_run_writes_scored_artifacts(workspace: Path) -> None:
    outcome = _run(_config(workspace, "majority"))
    assert outcome.completed == outcome.total == 5
    assert outcome.scorecard is not None
    for name in (
        "predictions.jsonl",
        "predictions.parquet",
        "metrics.json",
        "cost.json",
        "manifest.json",
    ):
        assert (outcome.run_dir / name).is_file(), name
    manifest = json.loads((outcome.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["details"]["split"] == "dev"
    assert len(manifest["details"]["dataset_hash"]) == 64


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    answer = {
        "labels": [{"label": "type-bug", "confidence": 0.9}],
        "component": "stdlib",
        "component_top3": ["stdlib"],
        "component_confidence": 0.6,
        "needs_info": False,
        "needs_info_confidence": 0.1,
        "missing_info": [],
        "triage_comment": "ok",
    }
    backend = FakeBackend(text=json.dumps(answer))
    real = wiring.build_llm_client

    def build(cfg: Config, *, run_id: str) -> LLMClient:
        return real(cfg, run_id=run_id, backend=backend)

    monkeypatch.setattr(wiring, "build_llm_client", build)
    return backend


def test_llm_run_is_parallel_safe_and_costed(workspace: Path, fake_llm: FakeBackend) -> None:
    outcome = _run(_config(workspace, "llm_single_shot"))
    assert outcome.scorecard is not None
    assert fake_llm.calls == 5
    assert outcome.scorecard.system.cost_usd_total > 0
    cost = json.loads((outcome.run_dir / "cost.json").read_text(encoding="utf-8"))
    assert cost["calls"] == 5


def test_budget_stop_keeps_partial_work_and_leaves_run_unscored(
    workspace: Path, fake_llm: FakeBackend
) -> None:
    outcome = _run(_config(workspace, "llm_single_shot", per_run_usd=1e-9))
    assert outcome.stopped_reason is not None
    assert outcome.stopped_reason.startswith("budget")
    assert outcome.scorecard is None
    assert fake_llm.calls == 0


def test_resume_only_runs_missing_issues(workspace: Path, fake_llm: FakeBackend) -> None:
    cfg = _config(workspace, "llm_single_shot")
    first = _run(cfg, limit=2)
    assert fake_llm.calls == 2
    resumed = _run(cfg, resume_dir=first.run_dir)
    assert fake_llm.calls == 5  # only the 3 missing issues were called
    assert resumed.completed == 5
    assert len(read_jsonl(first.run_dir / "predictions.jsonl", TriageResult)) == 5


def test_test_split_is_locked_and_capped(workspace: Path) -> None:
    cfg = _config(workspace, "majority")
    with pytest.raises(TestSetLockedError, match="locked"):
        _run(cfg, split="test")
    _run(cfg, split="test", allow_test=True)
    _run(cfg, split="test", allow_test=True)
    with pytest.raises(TestSetLockedError, match="2 times"):
        _run(cfg, split="test", allow_test=True)


def test_results_table_and_compare(workspace: Path) -> None:
    a = _run(_config(workspace, "majority", name="e-a"))
    b = _run(_config(workspace, "majority", name="e-b"))
    table = results_table(load_scored_runs(workspace / "runs"), "dev")
    assert "| e-a | majority |" in table
    assert "| e-b | majority |" in table
    rows = compare_runs(a.run_dir, b.run_dir, resamples=100)
    assert all(r.delta in (0.0, None) for r in rows)  # identical systems
    assert not any(r.significant for r in rows)


def test_a_later_partial_run_does_not_replace_a_full_one(workspace: Path) -> None:
    full = _run(_config(workspace, "majority", name="e-a"))
    partial = _run(_config(workspace, "majority", name="e-a"), limit=2)  # e.g. a trace demo
    table = results_table(load_scored_runs(workspace / "runs"), "dev")
    assert full.run_id in table
    assert partial.run_id not in table


def test_infrastructure_failures_are_retried_not_scored(
    workspace: Path, fake_llm: FakeBackend
) -> None:
    # The first 2 backend calls fail (rate limited) and retries are exhausted immediately.
    fake_llm.fail_first = 2
    cfg = _config(workspace, "llm_single_shot")
    cfg = cfg.model_copy(update={"retry": cfg.retry.model_copy(update={"max_attempts": 1})})
    outcome = _run(cfg)
    assert outcome.scorecard is not None
    assert outcome.scorecard.system.errors == 0  # the retry pass recovered both issues
    lines = read_jsonl(outcome.run_dir / "predictions.jsonl", TriageResult)
    assert sum((p.error or "").startswith("infra: ") for p in lines) == 2  # history kept


def test_runs_rescore_on_gold_with_a_human_baseline_row(workspace: Path) -> None:
    cfg = _config(workspace, "majority", name="e-a")
    _run(cfg)
    profile = load_profile(PROFILE_PATH)
    dev = load_split(workspace / "data", profile, "dev")
    store = GoldStore(gold_path(workspace / "data", profile))
    decision = Decision(labels=["type-bug"], component="stdlib")
    for e in dev[:2]:
        store.save(
            GoldRecord(
                issue_ref=e.snapshot.issue_ref, number=e.snapshot.number, split="dev",
                blind=decision, final=decision, annotator="t", blind_seconds=20.0,
                updated_at=FIXED_NOW,
            )
        )  # fmt: skip
    scored = load_scored_runs(workspace / "runs")
    assert {r.name for r in rescore_on_gold(scored, workspace / "runs", cfg, "dev")} == {"e-a"}
    runs = rescore_on_gold(scored, workspace / "runs", cfg, "dev", include_blind_pass=True)
    by_name = {r.name: r for r in runs}
    assert set(by_name) == {"e-a", "t, blind"}  # named after the annotator
    assert by_name["e-a"].stats.issues == 2  # only the adjudicated issues
    assert by_name["t, blind"].metrics["t3_accuracy"].point == 1.0
    gold_rows = compare_runs(
        workspace / "runs" / runs[0].run_id, workspace / "runs" / runs[0].run_id, labels="gold",
        resamples=50,
    )  # fmt: skip
    assert all(r.delta in (0.0, None) for r in gold_rows)


def _with_subset(cfg: Config, path: Path) -> Config:
    return cfg.model_copy(update={"eval": cfg.eval.model_copy(update={"subset": path})})


def test_a_subset_run_evaluates_only_its_issues(workspace: Path) -> None:
    dev = load_split(workspace / "data", load_profile(PROFILE_PATH), "dev")
    subset = workspace / "subset.txt"
    subset.write_text(f"# comment\n{dev[0].snapshot.issue_ref}  # trailing\n", encoding="utf-8")
    outcome = _run(_with_subset(_config(workspace, "majority"), subset))
    assert outcome.total == 1
    manifest = json.loads((outcome.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["details"]["subset"] == subset.as_posix()


def test_a_subset_cannot_reach_another_split(workspace: Path) -> None:
    test_issue = load_split(workspace / "data", load_profile(PROFILE_PATH), "test")[0]
    subset = workspace / "subset.txt"
    subset.write_text(test_issue.snapshot.issue_ref + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not in the dev split"):
        _run(_with_subset(_config(workspace, "majority"), subset))


def test_a_fully_replayed_run_shows_no_latency(workspace: Path) -> None:
    run = _run(_config(workspace, "majority", name="e-a")).run_dir
    cost = json.loads((run / "cost.json").read_text(encoding="utf-8"))
    (run / "cost.json").write_text(json.dumps({**cost, "calls": 5, "cache_hits": 5}), "utf-8")
    table = results_table(load_scored_runs(workspace / "runs"), "dev")
    assert "| replay |" in table
    assert "measures the replay" in table


def test_a_declared_deltas_table(workspace: Path) -> None:
    a = _run(_config(workspace, "majority", name="e-a")).run_id
    b = _run(_config(workspace, "majority", name="e-b")).run_id
    spec = DeltaSpec(
        title="t",
        reference=a,
        metrics=["t1_micro_f1"],
        comparisons=[Comparison(name="b vs ref", a="reference", b=b)],
    )
    table = deltas_table(spec, workspace / "runs", "silver")
    assert "| b vs ref | +0.000 [+0.000, +0.000] |" in table
    with pytest.raises(ValueError, match="unknown metrics"):
        deltas_table(spec.model_copy(update={"metrics": ["nope"]}), workspace / "runs", "silver")


def test_failure_table_lists_tagged_runs_only(workspace: Path) -> None:
    from triagelab.data.storage import write_parquet
    from triagelab.eval.report import failure_table

    a = _run(_config(workspace, "majority", name="e-a")).run_id
    b = _run(_config(workspace, "majority", name="e-b")).run_id
    spec = DeltaSpec(
        title="t", reference=a, metrics=["t1_micro_f1"],
        comparisons=[Comparison(name="E9: b", a="reference", b=b)],
    )  # fmt: skip
    assert failure_table(spec, workspace / "runs") is None
    rows = [
        {"issue_ref": "o/r#1", "categories": ["x", "y"]},
        {"issue_ref": "o/r#2", "categories": ["x"]},
    ]
    write_parquet(workspace / "runs" / b / "failures.parquet", rows)
    table = failure_table(spec, workspace / "runs")
    assert table is not None
    assert "| run | failing issues | x | y |" in table
    assert f"| E9 (`{b[-6:]}`) | 2 | 2 | 1 |" in table
    assert "reference" not in table.split("\n\n")[0]  # untagged runs are left out
