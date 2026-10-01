"""Calibration of every decision source, read from stored predictions (E6, AGENTS.md §12.5).

Any run is a decision source: a decision-backend run, but also the agent or the stuffed
agent, whose per-label and component confidences are verbalized too. For each question
(type label, component) an *outcome* is the source's answer, its confidence, and whether
it matched the reference. A missing answer counts as wrong with confidence 0.
"""

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from triagelab.data.models import IssueSnapshot
from triagelab.data.profile import load_profile
from triagelab.decisions.questions import QuestionId, answer_for
from triagelab.eval.bootstrap import Interval, bootstrap_ci
from triagelab.eval.calibration import aurc, brier, ece
from triagelab.eval.report import Labels, examples_for, load_run
from triagelab.triage import TriageResult


@dataclass(frozen=True)
class Outcome:
    issue: IssueSnapshot
    answer: str | None
    confidence: float
    correct: bool


def _type_answer(p: TriageResult, types: Sequence[str]) -> tuple[str | None, float]:
    found = [label for label in p.labels if label in types]
    if not found:
        return None, 0.0
    best = max(found, key=lambda label: p.label_confidence.get(label, 0.0))
    return best, p.label_confidence.get(best, 0.0)


def outcomes(run_dir: Path, labels: Labels) -> dict[QuestionId, list[Outcome]]:
    cfg, split, preds = load_run(run_dir)
    profile = load_profile(cfg.dataset.profile)
    latest = {p.issue_ref: p for p in preds}
    out: dict[QuestionId, list[Outcome]] = {"type": [], "component": []}
    for e in examples_for(cfg, split, labels):
        p = latest.get(e.snapshot.issue_ref)
        if p is None:
            continue
        for qid in out:
            reference = answer_for(qid, e.gold, profile)
            if reference is None:
                continue
            if qid == "type":
                answer, conf = _type_answer(p, profile.taxonomy.type)
            else:
                answer, conf = p.component, p.component_confidence or 0.0
            out[qid].append(Outcome(e.snapshot, answer, conf, answer == reference))
    return out


class SourceStats(BaseModel):
    source: str
    question: str
    n: int
    accuracy: Interval
    mean_confidence: float
    ece: Interval  # 10 equal-width bins
    ece_mass: float  # 10 equal-mass bins
    brier: Interval
    aurc: float
    cost_per_issue: float


def summarise(
    source: str, question: str, rows: Sequence[Outcome], cost_per_issue: float, *, seed: int = 0
) -> SourceStats:
    conf = [r.confidence for r in rows]
    right = [r.correct for r in rows]

    def stat(fn: Callable[[list[float], list[bool]], float]) -> Interval:
        return bootstrap_ci(
            len(rows), lambda idx: fn([conf[i] for i in idx], [right[i] for i in idx]), seed=seed
        )

    return SourceStats(
        source=source,
        question=question,
        n=len(rows),
        accuracy=stat(lambda _, r: sum(r) / len(r)),
        mean_confidence=statistics.fmean(conf) if conf else 0.0,
        ece=stat(lambda c, r: ece(c, r)),
        ece_mass=ece(conf, right, 10, "mass") if rows else 0.0,
        brier=stat(brier),
        aurc=aurc(conf, right) if rows else 0.0,
        cost_per_issue=cost_per_issue,
    )


# Slices of AGENTS.md §12.5: where calibration might break.
def _fenced_share(body: str) -> float:
    lines = body.splitlines()
    inside, fenced = False, 0
    for line in lines:
        if line.strip().startswith("```"):
            inside = not inside
            continue
        fenced += inside
    return fenced / len(lines) if lines else 0.0


def _non_ascii_letter_share(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    return sum(not ch.isascii() for ch in letters) / len(letters) if letters else 0.0


SLICES: dict[str, Callable[[IssueSnapshot], bool]] = {
    "short (body < 300 chars)": lambda s: len(s.body.strip()) < 300,
    "mostly logs/code (> 50% fenced lines)": lambda s: _fenced_share(s.body) > 0.5,
    "non-English (> 10% non-ASCII letters)": lambda s: (
        _non_ascii_letter_share(s.title + s.body) > 0.1
    ),
}


@dataclass(frozen=True)
class SliceStats:
    name: str
    n: int
    accuracy: float
    mean_confidence: float
    ece: float


def slices(rows: Sequence[Outcome]) -> list[SliceStats]:
    out: list[SliceStats] = []
    everything: dict[str, Callable[[IssueSnapshot], bool]] = {"all": lambda _: True, **SLICES}
    for name, member in everything.items():
        part = [r for r in rows if member(r.issue)]
        if not part:
            out.append(SliceStats(name, 0, float("nan"), float("nan"), float("nan")))
            continue
        conf, right = [r.confidence for r in part], [r.correct for r in part]
        out.append(
            SliceStats(
                name, len(part), sum(right) / len(part), statistics.fmean(conf), ece(conf, right)
            )
        )
    return out


def cost_per_issue(run_dir: Path) -> float:
    latest = {p.issue_ref: p for p in load_run(run_dir)[2]}
    return statistics.fmean(p.cost_usd for p in latest.values()) if latest else 0.0


class CalibrationSpec(BaseModel):
    """Which runs to compare (display name -> run id), e.g. reports/calibration/e6.yaml."""

    title: str
    sources: dict[str, str]


def _ci(i: Interval) -> str:
    return f"{i.point:.3f} [{i.low:.3f}, {i.high:.3f}]"


def build_report(
    spec: CalibrationSpec, runs_dir: Path, labels: Labels, figures_dir: Path, stem: str
) -> str:
    """Tables per question, slices, and two figures per question (written to figures_dir)."""
    from triagelab.eval.figures import reliability_figure, risk_coverage_figure

    per_source = {name: outcomes(runs_dir / run, labels) for name, run in spec.sources.items()}
    costs = {name: cost_per_issue(runs_dir / run) for name, run in spec.sources.items()}
    lines = [f"# {spec.title} ({labels} labels)", ""]
    for qid in ("type", "component"):
        series = {name: o[qid] for name, o in per_source.items() if o[qid]}
        if not series:
            continue
        reliability = figures_dir / f"{stem}-{labels}-{qid}-reliability.png"
        coverage = figures_dir / f"{stem}-{labels}-{qid}-risk-coverage.png"
        reliability_figure(series, f"{qid}: reliability ({labels} labels)", reliability)
        risk_coverage_figure(series, f"{qid}: risk-coverage ({labels} labels)", coverage)
        lines += [
            f"## {qid}",
            "",
            "| source | n | accuracy [95% CI] | mean conf. | ECE [95% CI] | ECE (equal-mass) "
            "| Brier [95% CI] | AURC | $/issue |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for name, rows in series.items():
            s = summarise(name, qid, rows, costs[name])
            lines.append(
                f"| {name} | {s.n} | {_ci(s.accuracy)} | {s.mean_confidence:.3f} | {_ci(s.ece)} "
                f"| {s.ece_mass:.3f} | {_ci(s.brier)} | {s.aurc:.3f} | ${s.cost_per_issue:.5f} |"
            )
        lines += [
            "",
            f"![{qid} reliability](../figures/{reliability.name}) "
            f"![{qid} risk-coverage](../figures/{coverage.name})",
            "",
            "Slices (n is small: read them as warnings, not estimates):",
            "",
            "| source | slice | n | accuracy | mean conf. | ECE |",
            "|---|---|---|---|---|---|",
        ]
        for name, rows in series.items():
            for sl in slices(rows):
                if sl.n:
                    lines.append(
                        f"| {name} | {sl.name} | {sl.n} | {sl.accuracy:.2f} | "
                        f"{sl.mean_confidence:.2f} | {sl.ece:.3f} |"
                    )
        lines.append("")
    lines += [
        "ECE uses 10 equal-width bins; AURC is the area under the risk (1 - accuracy) vs "
        "coverage curve (lower is better). Intervals: 1,000 issue resamples. Runs: "
        + ", ".join(f"{name} `{run}`" for name, run in spec.sources.items())
        + ".",
    ]
    return "\n".join(lines) + "\n"
