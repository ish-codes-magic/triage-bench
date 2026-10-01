"""The regression gate: a candidate run against the blessed baseline, on a fixed subset.

A pull request that changes the agent runs it for real on a fixed dev subset (eval.yml),
and this module decides whether the change may merge:

  - FAIL if a gated metric's point estimate drops by more than its `max_drop`;
  - FAIL if cost per issue rises by more than `max_cost_increase` (relative), or if the
    share of fallback answers exceeds `max_error_rate`;
  - otherwise PASS. A statistically significant drop that is within its threshold is
    reported as a warning, not a failure.

Thresholds are on point estimates, not on confidence intervals: on 50 issues a real 5-point
drop in micro-F1 is rarely "significant", and a gate that never fires isn't one. The
paired-bootstrap interval is printed next to every delta so a reviewer can judge noise.
"""

import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from triagelab.data.storage import append_jsonl, read_parquet, write_parquet
from triagelab.eval.failure_tagger import FAILURES_FILE
from triagelab.eval.report import DeltaRow, compare_runs, load_run
from triagelab.hashing import stable_hash

Verdict = Literal["pass", "warn", "fail"]


class GateRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    max_drop: float = Field(ge=0.0, description="Largest tolerated fall in the point estimate.")


class GateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labels: Literal["silver", "gold"] = "gold"
    rules: list[GateRule]
    report_metrics: list[str] = Field(
        default_factory=list[str], description="Shown in the table, never gated."
    )
    max_cost_increase: float = Field(ge=0.0, description="Relative rise in cost per issue.")
    max_error_rate: float = Field(ge=0.0, le=1.0)
    # A crashed or partial candidate must never pass by having nothing to compare.
    min_coverage: float = Field(
        default=1.0, gt=0.0, le=1.0, description="Share of baseline issues the candidate answers."
    )


def load_gate_config(path: Path) -> GateConfig:
    return GateConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class GateRow(BaseModel):
    metric: str
    baseline: float | None
    candidate: float | None
    delta: float | None
    low: float | None
    high: float | None
    limit: str  # the rule, as shown in the table ("max drop 0.05", or "" if not gated)
    verdict: Verdict


class GateReport(BaseModel):
    baseline_run: str
    candidate_run: str
    issues: int
    rows: list[GateRow]
    failure_deltas: dict[str, tuple[int, int]] | None  # category -> (baseline, candidate)

    @property
    def verdict(self) -> Verdict:
        verdicts = {r.verdict for r in self.rows}
        return "fail" if "fail" in verdicts else "warn" if "warn" in verdicts else "pass"


def _metric_row(d: DeltaRow, rule: GateRule | None) -> GateRow:
    verdict: Verdict = "pass"
    if rule is not None and d.delta is not None:
        if d.delta < -rule.max_drop:
            verdict = "fail"
        elif d.significant and d.delta < 0:
            verdict = "warn"
    return GateRow(
        metric=d.metric,
        baseline=d.a,
        candidate=d.b,
        delta=d.delta,
        low=d.low,
        high=d.high,
        limit=f"max drop {rule.max_drop:.2f}" if rule else "",
        verdict=verdict,
    )


def _system_rows(
    baseline_dir: Path, candidate_dir: Path, shared: set[str], gate: GateConfig
) -> list[GateRow]:
    def per_issue(run_dir: Path) -> tuple[float, float]:
        latest = {p.issue_ref: p for p in load_run(run_dir)[2] if p.issue_ref in shared}
        n = max(len(latest), 1)
        cost = sum(p.cost_usd for p in latest.values()) / n
        errors = sum(p.error is not None for p in latest.values()) / n
        return cost, errors

    cost_a, err_a = per_issue(baseline_dir)
    cost_b, err_b = per_issue(candidate_dir)
    rise = (cost_b - cost_a) / cost_a if cost_a > 0 else 0.0
    return [
        GateRow(
            metric="cost_per_issue_usd",
            baseline=cost_a,
            candidate=cost_b,
            delta=cost_b - cost_a,
            low=None,
            high=None,
            limit=f"max rise {gate.max_cost_increase:.0%}",
            verdict="fail" if rise > gate.max_cost_increase else "pass",
        ),
        GateRow(
            metric="error_rate",
            baseline=err_a,
            candidate=err_b,
            delta=err_b - err_a,
            low=None,
            high=None,
            limit=f"max {gate.max_error_rate:.0%}",
            verdict="fail" if err_b > gate.max_error_rate else "pass",
        ),
    ]


def check(baseline_dir: Path, candidate_dir: Path, gate: GateConfig) -> GateReport:
    """Score both runs on the issues they share, with the gate's labels."""
    deltas = {d.metric: d for d in compare_runs(baseline_dir, candidate_dir, labels=gate.labels)}
    rules = {r.metric: r for r in gate.rules}
    unknown = (set(rules) | set(gate.report_metrics)) - set(deltas)
    if unknown:
        raise ValueError(f"gate config names unknown metrics: {sorted(unknown)}")
    rows = [_metric_row(deltas[m], rules[m]) for m in rules]
    rows += [_metric_row(deltas[m], None) for m in gate.report_metrics if m not in rules]
    refs_a = {p.issue_ref for p in load_run(baseline_dir)[2]}
    shared = refs_a & {p.issue_ref for p in load_run(candidate_dir)[2]}
    coverage = len(shared) / len(refs_a) if refs_a else 0.0
    rows.insert(
        0,
        GateRow(
            metric="coverage",
            baseline=1.0,
            candidate=coverage,
            delta=coverage - 1.0,
            low=None,
            high=None,
            limit=f"min {gate.min_coverage:.0%}",
            verdict="fail" if coverage < gate.min_coverage else "pass",
        ),
    )
    rows += _system_rows(baseline_dir, candidate_dir, shared, gate)
    return GateReport(
        baseline_run=_run_id(baseline_dir),
        candidate_run=_run_id(candidate_dir),
        issues=len(shared),
        rows=rows,
        failure_deltas=_failure_deltas(baseline_dir, candidate_dir, shared),
    )


def _run_id(run_dir: Path) -> str:
    """The recorded run id: a blessed baseline lives in a folder of another name."""
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    return str(manifest["run_id"])


def _categories(run_dir: Path, refs: set[str]) -> Counter[str] | None:
    """Failure-category counts over `refs` only, or None if the run isn't tagged."""
    path = run_dir / FAILURES_FILE
    if not path.exists():
        return None
    rows = read_parquet(path)
    return Counter(c for row in rows if row["issue_ref"] in refs for c in row["categories"])


def _failure_deltas(
    baseline_dir: Path, candidate_dir: Path, shared: set[str]
) -> dict[str, tuple[int, int]] | None:
    a, b = _categories(baseline_dir, shared), _categories(candidate_dir, shared)
    if a is None or b is None:
        return None
    both: Counter[str] = a + b
    return {c: (a[c], b[c]) for c, _ in both.most_common()}


def pick_subset(refs: list[str], n: int) -> list[str]:
    """A fixed pseudo-random subset: the n refs with the smallest stable hash.

    Order-independent and reproducible from the refs alone, so re-running it gives the
    same subset, and adding an issue later changes the subset by at most one issue.
    """
    return sorted(sorted(refs, key=stable_hash)[:n], key=lambda r: int(r.rsplit("#", 1)[1]))


# What a blessed baseline keeps: enough to re-score it (config, manifest, predictions)
# and to report on it (cost, git SHA, failure tags), but not its traces.
BASELINE_FILES = ("config.yaml", "manifest.json", "cost.json", "git_sha", "failures.parquet")


def bless(run_dir: Path, dest: Path, subset: list[str] | None = None) -> int:
    """Make a run the gate's baseline: its latest prediction per issue (only the subset's,
    if given), its failure tags for those issues, and its records."""
    wanted = set(subset) if subset is not None else None
    latest = {
        p.issue_ref: p for p in load_run(run_dir)[2] if wanted is None or p.issue_ref in wanted
    }
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    append_jsonl(dest / "predictions.jsonl", latest.values())
    for name in BASELINE_FILES:
        if not (run_dir / name).exists():
            continue
        if name == FAILURES_FILE:
            rows = [r for r in read_parquet(run_dir / name) if r["issue_ref"] in latest]
            write_parquet(dest / name, rows)
        else:
            # The baseline is committed: LF and a final newline, even for records that an
            # older run wrote on Windows with CRLF.
            text = (run_dir / name).read_bytes().decode("utf-8").replace("\r\n", "\n")
            (dest / name).write_bytes((text.rstrip("\n") + "\n").encode("utf-8"))
    return len(latest)


_ICON: dict[Verdict, str] = {"pass": "pass", "warn": "WARN", "fail": "**FAIL**"}


def render(report: GateReport) -> str:
    """Markdown for the job summary and the PR comment."""

    def num(x: float | None, metric: str) -> str:
        if x is None:
            return "n/a"
        return f"${x:.5f}" if metric.startswith("cost") else f"{x:.3f}"

    def delta(r: GateRow) -> str:
        if r.delta is None:
            return "n/a"
        text = f"{r.delta:+.5f}" if r.metric.startswith("cost") else f"{r.delta:+.3f}"
        return text if r.low is None else f"{text} [{r.low:+.3f}, {r.high:+.3f}]"

    lines = [
        f"### Regression gate: {report.verdict.upper()}",
        "",
        f"Candidate `{report.candidate_run}` vs baseline `{report.baseline_run}` "
        f"on {report.issues} shared issues. Deltas are candidate - baseline with 95% "
        "paired-bootstrap intervals.",
        "",
        "| metric | baseline | candidate | delta [95% CI] | rule | verdict |",
        "|---|---|---|---|---|---|",
    ]
    for r in report.rows:
        lines.append(
            f"| {r.metric} | {num(r.baseline, r.metric)} | {num(r.candidate, r.metric)} | "
            f"{delta(r)} | {r.limit} | {_ICON[r.verdict] if r.limit else ''} |"
        )
    if report.failure_deltas:
        lines += ["", "| failure category | baseline | candidate | delta |", "|---|---|---|---|"]
        for cat, (a, b) in report.failure_deltas.items():
            lines.append(f"| {cat} | {a} | {b} | {b - a:+d} |")
    return "\n".join(lines) + "\n"
