"""Results tables and run-vs-run comparisons, built only from the run registry.

AGENTS.md §16: every reported number is regenerated from runs/, never typed by hand.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from triagelab.config import Config
from triagelab.data.profile import load_profile
from triagelab.data.splits import Split, parse_split
from triagelab.data.storage import read_jsonl
from triagelab.eval.bootstrap import paired_bootstrap
from triagelab.eval.dataset import EvalExample, load_split
from triagelab.eval.gold_labels import human_predictions, with_gold
from triagelab.eval.registry import RunManifest
from triagelab.eval.score import METRICS, MetricScore, SystemStats, align, score, statistic
from triagelab.labeling.gold import GoldStore, gold_path
from triagelab.triage import TriageResult

Labels = Literal["silver", "gold"]

HEADLINE = (
    "t1_micro_f1",
    "t1_area_micro_f1",
    "t2_link_f1",
    "t3_accuracy",
    "t3_top3_accuracy",
    "t4_f1",
)


class ScoredRun(BaseModel):
    run_id: str
    name: str
    split: str
    system: str
    model: str
    created_at: datetime
    dataset_hash: str
    metrics: dict[str, MetricScore]
    stats: SystemStats


def load_scored_runs(runs_dir: Path) -> list[ScoredRun]:
    runs: list[ScoredRun] = []
    if not runs_dir.is_dir():
        return runs
    for run_dir in sorted(runs_dir.iterdir()):
        metrics_file, manifest_file = run_dir / "metrics.json", run_dir / "manifest.json"
        if not (metrics_file.is_file() and manifest_file.is_file()):
            continue
        manifest = RunManifest.model_validate_json(manifest_file.read_text(encoding="utf-8"))
        metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
        runs.append(
            ScoredRun(
                run_id=manifest.run_id,
                name=manifest.name,
                split=metrics["split"],
                system=manifest.details.get("system", "?"),
                model=manifest.details.get("model", "-"),
                created_at=manifest.created_at,
                dataset_hash=manifest.details.get("dataset_hash", "unknown"),
                metrics={k: MetricScore.model_validate(v) for k, v in metrics["metrics"].items()},
                stats=SystemStats.model_validate(metrics["system"]),
            )
        )
    return runs


def _cell(m: MetricScore | None) -> str:
    if m is None or m.point is None:
        return "n/a"
    return f"{m.point:.2f} [{m.low:.2f}, {m.high:.2f}]"


def results_table(runs: list[ScoredRun], split: str) -> str:
    """One row per config name for `split`: its most complete scored run, latest first.

    Most complete wins so a quick `--limit` run (a smoke check, a trace demo) never
    replaces a full evaluation in the table.
    """
    latest: dict[str, ScoredRun] = {}
    for run in sorted(runs, key=lambda r: (r.stats.issues, r.created_at)):
        if run.split == split:
            latest[run.name] = run
    rows = sorted(latest.values(), key=lambda r: r.name)
    header = (
        "| experiment | system | T1 micro-F1 | T1 area F1 | T2 link F1 | T3 acc | T3 top-3 | "
        "T4 F1 | $/issue | p50 latency |"
    )
    lines = [header, "|" + "---|" * 10]
    for r in rows:
        cells = " | ".join(_cell(r.metrics.get(m)) for m in HEADLINE)
        lines.append(
            f"| {r.name} | {r.system} | {cells} | ${r.stats.cost_usd_per_issue:.5f} | "
            f"{r.stats.latency_ms_p50 / 1000:.1f}s |"
        )
    hashes = sorted({r.dataset_hash[:12] for r in rows})
    lines += [
        "",
        f"Silver labels, {split} split (n = {rows[0].stats.issues if rows else 0}). "
        "Cells are point estimates with 95% bootstrap intervals (1,000 issue resamples). "
        f"Dataset hash: {', '.join(hashes) or 'n/a'}. Runs: "
        + ", ".join(f"`{r.run_id}`" for r in rows)
        + ".",
    ]
    return "\n".join(lines) + "\n"


class DeltaRow(BaseModel):
    metric: str
    a: float | None
    b: float | None
    delta: float | None
    low: float | None
    high: float | None
    significant: bool


def load_run(run_dir: Path) -> tuple[Config, Split, list[TriageResult]]:
    cfg = Config.model_validate(
        yaml.safe_load((run_dir / "config.yaml").read_text(encoding="utf-8"))
    )
    manifest = RunManifest.model_validate_json(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    split = parse_split(manifest.details.get("split", "dev"))
    return cfg, split, read_jsonl(run_dir / "predictions.jsonl", TriageResult)


def examples_for(cfg: Config, split: Split, labels: Labels) -> list[EvalExample]:
    """The split's examples, answered by silver labels or (adjudicated issues only) gold."""
    profile = load_profile(cfg.dataset.profile)
    examples = load_split(cfg.dataset.data_dir, profile, split)
    if labels == "gold":
        records = GoldStore(gold_path(cfg.dataset.data_dir, profile)).load()
        examples = with_gold(examples, records, profile)
    return examples


def compare_runs(
    run_a: Path,
    run_b: Path,
    *,
    resamples: int = 1000,
    seed: int = 0,
    exclude_errors: bool = False,
    labels: Labels = "silver",
) -> list[DeltaRow]:
    """B minus A on the issues both runs predicted, with paired-bootstrap intervals.

    `exclude_errors` drops issues where either run fell back (e.g. a provider outage), to
    isolate the effect of a change from infrastructure noise.
    """
    cfg_a, split_a, preds_a = load_run(run_a)
    _, split_b, preds_b = load_run(run_b)
    if split_a != split_b:
        raise ValueError(f"Runs are on different splits ({split_a} vs {split_b}).")
    examples = examples_for(cfg_a, split_a, labels)
    # Later lines win: a retried issue's final prediction replaces its failed attempt.
    latest_a = {p.issue_ref: p for p in preds_a}
    latest_b = {p.issue_ref: p for p in preds_b}
    shared = set(latest_a) & set(latest_b)
    if exclude_errors:
        shared = {r for r in shared if latest_a[r].error is None and latest_b[r].error is None}
    examples = [e for e in examples if e.snapshot.issue_ref in shared]
    data_a = align(examples, list(latest_a.values()))
    data_b = align(examples, list(latest_b.values()))
    rows: list[DeltaRow] = []
    for name, fn in METRICS.items():
        d = paired_bootstrap(
            len(examples),
            statistic(fn, data_a),
            statistic(fn, data_b),
            resamples=resamples,
            seed=seed,
        )
        a, b = (
            statistic(fn, data_a)(range(len(examples))),
            statistic(fn, data_b)(range(len(examples))),
        )
        defined = d.valid_resamples > 0
        rows.append(
            DeltaRow(
                metric=name,
                a=a,
                b=b,
                delta=d.delta if defined else None,
                low=d.low if defined else None,
                high=d.high if defined else None,
                significant=defined and d.significant,
            )
        )
    return rows


def rescore_on_gold(
    runs: list[ScoredRun], runs_dir: Path, cfg: Config, split: Split, *, resamples: int = 1000
) -> list[ScoredRun]:
    """Every run re-scored against gold, plus the person's blind pass as a "human" row.

    Offline and free: stored predictions are scored again; no model is called.
    """
    out: list[ScoredRun] = []
    for run in runs:
        if run.split != split:
            continue
        run_cfg, _, preds = load_run(runs_dir / run.run_id)
        latest = {p.issue_ref: p for p in preds}
        examples = [
            e for e in examples_for(run_cfg, split, "gold") if e.snapshot.issue_ref in latest
        ]
        if not examples:
            continue
        card = score(examples, list(latest.values()), resamples=resamples)
        out.append(run.model_copy(update={"metrics": card.metrics, "stats": card.system}))
    profile = load_profile(cfg.dataset.profile)
    records = GoldStore(gold_path(cfg.dataset.data_dir, profile)).load()
    examples = examples_for(cfg, split, "gold")
    if examples:
        card = score(examples, human_predictions(records), resamples=resamples)
        out.append(
            ScoredRun(
                run_id="gold-labels (blind pass)",
                name="human, blind",
                split=split,
                system="human",
                model="-",
                created_at=datetime.now(UTC),
                dataset_hash="gold",
                metrics=card.metrics,
                stats=card.system,
            )
        )
    return out


def render_comparison(rows: list[DeltaRow], a_name: str, b_name: str) -> str:
    def f(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.3f}"

    lines = [
        f"| metric | A: {a_name} | B: {b_name} | B - A [95% CI] | |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        ci = "n/a" if r.delta is None else f"{r.delta:+.3f} [{r.low:+.3f}, {r.high:+.3f}]"
        verdict = "significant" if r.significant else ""
        lines.append(f"| {r.metric} | {f(r.a)} | {f(r.b)} | {ci} | {verdict} |")
    return "\n".join(lines) + "\n"
