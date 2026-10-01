"""Results tables and run-vs-run comparisons, built only from the run registry.

AGENTS.md §16: every reported number is regenerated from runs/, never typed by hand.
"""

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from triagelab.config import Config
from triagelab.data.profile import load_profile
from triagelab.data.splits import Split, parse_split
from triagelab.data.storage import read_jsonl, read_parquet
from triagelab.eval.bootstrap import paired_bootstrap
from triagelab.eval.dataset import EvalExample, load_split
from triagelab.eval.failure_tagger import FAILURES_FILE
from triagelab.eval.gold_labels import human_predictions, with_gold
from triagelab.eval.registry import RunManifest
from triagelab.eval.score import METRICS, MetricScore, SystemStats, align, score, statistic
from triagelab.labeling.gold import GoldStore, gold_path
from triagelab.triage import TriageResult

Labels = Literal["silver", "gold"]

# T4 (needs-info) is scored in every scorecard but kept out of the headline table:
# adjudication showed its silver labels track CPython's `pending` label, not missing
# information (ADR-0036).
HEADLINE = (
    "t1_micro_f1",
    "t1_area_micro_f1",
    "t2_link_f1",
    "t3_accuracy",
    "t3_top3_accuracy",
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
    # Every model call came from the cache: answers and costs are the original run's, but
    # its latencies measure the replay, not the model.
    replayed: bool = False


def _replayed(run_dir: Path) -> bool:
    cost_file = run_dir / "cost.json"
    if not cost_file.is_file():
        return False
    cost = json.loads(cost_file.read_text(encoding="utf-8"))
    return cost.get("calls", 0) > 0 and cost.get("cache_hits") == cost.get("calls")


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
                replayed=_replayed(run_dir),
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
        "$/issue | p50 latency |"
    )
    lines = [header, "|" + "---|" * 9]
    for r in rows:
        cells = " | ".join(_cell(r.metrics.get(m)) for m in HEADLINE)
        latency = "replay" if r.replayed else f"{r.stats.latency_ms_p50 / 1000:.1f}s"
        lines.append(
            f"| {r.name} | {r.system} | {cells} | ${r.stats.cost_usd_per_issue:.5f} | {latency} |"
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
    if any(r.replayed for r in rows):
        lines.append(
            '\n"replay": the run re-used every model answer from the cache (a post-processing '
            "change), so its latency measures the replay; the live run's latency applies."
        )
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
    runs: list[ScoredRun],
    runs_dir: Path,
    cfg: Config,
    split: Split,
    *,
    resamples: int = 1000,
    include_blind_pass: bool = False,
) -> list[ScoredRun]:
    """Every run re-scored against gold. Offline and free: no model is called.

    `include_blind_pass` adds the annotators' blind pass as a row. It is off by default:
    when the same annotator adjudicated the gold starting from their own blind answer,
    that row is anchored on itself and is not a baseline (only an independent
    annotator's blind pass would be).
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
    if examples and include_blind_pass:
        card = score(examples, human_predictions(records), resamples=resamples)
        # Named after whoever labeled: a person, or a model annotator (ADR-0035).
        annotators = ", ".join(sorted({r.annotator for r in records.values()}))
        out.append(
            ScoredRun(
                run_id="gold-labels (blind pass)",
                name=f"{annotators}, blind",
                split=split,
                system="annotator",
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


class Comparison(BaseModel):
    name: str
    a: str  # a run id, or "reference"
    b: str


class DeltaSpec(BaseModel):
    """A paired-comparison report, declared as data (e.g. reports/experiments/m6.yaml)."""

    title: str
    reference: str
    metrics: list[str]
    comparisons: list[Comparison]


def deltas_table(spec: DeltaSpec, runs_dir: Path, labels: Labels) -> str:
    """One row per comparison: B minus A per metric, bold where the 95% CI excludes 0."""

    def run(ref: str) -> Path:
        return runs_dir / (spec.reference if ref == "reference" else ref)

    def cell(r: DeltaRow) -> str:
        if r.delta is None:
            return "n/a"
        text = f"{r.delta:+.3f} [{r.low:+.3f}, {r.high:+.3f}]"
        return f"**{text}**" if r.significant else text

    lines = [
        f"| comparison (B - A) | {' | '.join(spec.metrics)} |",
        "|---|" + "---|" * len(spec.metrics),
    ]
    for c in spec.comparisons:
        rows = {r.metric: r for r in compare_runs(run(c.a), run(c.b), labels=labels)}
        missing = set(spec.metrics) - set(rows)
        if missing:
            raise ValueError(f"unknown metrics: {sorted(missing)}")
        lines.append(f"| {c.name} | " + " | ".join(cell(rows[m]) for m in spec.metrics) + " |")
    lines += [
        "",
        f"{labels.capitalize()} labels. Paired bootstrap over the issues both runs answered "
        "(1,000 resamples); **bold** = the 95% interval excludes 0. "
        f"Reference: `{spec.reference}`.",
    ]
    return "\n".join(lines) + "\n"


def failure_table(spec: DeltaSpec, runs_dir: Path, top: int = 6) -> str | None:
    """Failure-category counts (LLM tagger) for every tagged run in the spec, or None."""
    named: dict[str, str] = {spec.reference: "reference"}
    for c in spec.comparisons:
        for run_id in (c.a, c.b):
            if run_id != "reference":
                named.setdefault(run_id, c.name.split(":")[0] if ":" in c.name else c.name)
    counts: dict[str, Counter[str]] = {}
    failing: dict[str, int] = {}
    for run_id in named:
        path = runs_dir / run_id / FAILURES_FILE
        if path.is_file():
            rows = read_parquet(path)
            counts[run_id] = Counter(cat for r in rows for cat in r["categories"])
            failing[run_id] = len(rows)
    if not counts:
        return None
    total: Counter[str] = Counter()
    for c in counts.values():
        total += c
    cats = [cat for cat, _ in total.most_common(top)]
    lines = [
        f"| run | failing issues | {' | '.join(cats)} |",
        "|---|---|" + "---|" * len(cats),
    ]
    for run_id, c in counts.items():
        cells = " | ".join(str(c[cat]) for cat in cats)
        lines.append(f"| {named[run_id]} (`{run_id[-6:]}`) | {failing[run_id]} | {cells} |")
    lines += [
        "",
        "Failure categories from the LLM tagger against the adjudicated labels "
        "(docs/FAILURE_TAXONOMY.md; categories with tagger kappa < 0.6 are unvalidated).",
    ]
    return "\n".join(lines) + "\n"
