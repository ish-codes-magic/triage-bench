"""Score predictions against gold: headline metrics with bootstrap intervals.

Every headline metric is one function over (gold, prediction, weight) lists, registered
in METRICS. The same functions power point estimates, bootstrap intervals and paired
comparisons, so `eval` and `compare` can never disagree about what a metric means.

Subsets are part of each metric's definition:
  - T1 is scored on human-triaged issues only: untriaged issues have no labels for lack
    of attention, not because none apply (ADR-0013).
  - T3 is scored on issues that have a gold component (a merged fix exists).
  - T2 and T4 are scored on every issue.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from triagelab.eval.bootstrap import bootstrap_ci
from triagelab.eval.dataset import EvalExample, Gold
from triagelab.eval.metrics import (
    accuracy,
    binary_prf,
    duplicate_detection_prf,
    duplicate_prf,
    multilabel_prf,
    percentile,
    top_k_accuracy,
)
from triagelab.triage import TriageResult

Weights = Sequence[float] | None
MetricFn = Callable[[Sequence[Gold], Sequence[TriageResult], Weights], float | None]


def _subset(
    golds: Sequence[Gold],
    preds: Sequence[TriageResult],
    weights: Weights,
    keep: Callable[[Gold], bool],
) -> tuple[list[Gold], list[TriageResult], list[float] | None]:
    idx = [i for i, g in enumerate(golds) if keep(g)]
    return (
        [golds[i] for i in idx],
        [preds[i] for i in idx],
        None if weights is None else [weights[i] for i in idx],
    )


def _t1(group: str | None, stat: str) -> MetricFn:
    def fn(golds: Sequence[Gold], preds: Sequence[TriageResult], w: Weights) -> float | None:
        g, p, ww = _subset(golds, preds, w, lambda x: x.human_triaged)
        if not g:
            return None
        gold_sets = [
            {lab for lab in x.labels if group is None or x.label_groups.get(lab) == group}
            for x in g
        ]
        known = {lab: grp for x in g for lab, grp in x.label_groups.items()}
        pred_sets = [
            {lab for lab in r.labels if group is None or known.get(lab) == group} for r in p
        ]
        scores = multilabel_prf(gold_sets, pred_sets, ww)
        return scores.macro_f1 if stat == "macro" else scores.micro.f1

    return fn


def _t2(kind: str) -> MetricFn:
    def fn(golds: Sequence[Gold], preds: Sequence[TriageResult], w: Weights) -> float | None:
        gold = [g.duplicate_of for g in golds]
        pred = [r.duplicate_of for r in preds]
        s = (
            duplicate_detection_prf(gold, pred, w)
            if kind == "detect_f1"
            else duplicate_prf(gold, pred, w)
        )
        if s.support == 0:
            return None
        return {"f1": s.f1, "detect_f1": s.f1, "precision": s.precision, "recall": s.recall}[kind]

    return fn


def _t3(k: int) -> MetricFn:
    def fn(golds: Sequence[Gold], preds: Sequence[TriageResult], w: Weights) -> float | None:
        g, p, ww = _subset(golds, preds, w, lambda x: x.component is not None)
        if not g:
            return None
        gold = [x.component or "" for x in g]
        if k == 1:
            return accuracy(gold, [r.component for r in p], ww)
        ranked = [r.component_candidates or ([r.component] if r.component else []) for r in p]
        return top_k_accuracy(gold, ranked, k, ww)

    return fn


def _t4(kind: str) -> MetricFn:
    def fn(golds: Sequence[Gold], preds: Sequence[TriageResult], w: Weights) -> float | None:
        s = binary_prf([g.needs_info for g in golds], [r.needs_info for r in preds], w)
        if s.support == 0:
            return None
        return {"f1": s.f1, "precision": s.precision, "recall": s.recall}[kind]

    return fn


# Headline metrics, in report order.
METRICS: dict[str, MetricFn] = {
    "t1_micro_f1": _t1(None, "micro"),
    "t1_macro_f1": _t1(None, "macro"),
    "t1_type_micro_f1": _t1("type", "micro"),
    "t1_area_micro_f1": _t1("area", "micro"),
    "t2_link_f1": _t2("f1"),
    "t2_link_precision": _t2("precision"),
    "t2_link_recall": _t2("recall"),
    "t2_detect_f1": _t2("detect_f1"),
    "t3_accuracy": _t3(1),
    "t3_top3_accuracy": _t3(3),
    "t4_f1": _t4("f1"),
    "t4_precision": _t4("precision"),
    "t4_recall": _t4("recall"),
}


class MetricScore(BaseModel):
    point: float | None
    low: float | None
    high: float | None
    weighted: float | None  # natural-rate estimate using sampling weights


class SystemStats(BaseModel):
    issues: int
    errors: int
    cost_usd_total: float
    cost_usd_per_issue: float
    latency_ms_p50: float
    latency_ms_p95: float
    tokens_in_per_issue: float
    tokens_out_per_issue: float


class Scorecard(BaseModel):
    metrics: dict[str, MetricScore]
    system: SystemStats
    per_label_f1: dict[str, float]


@dataclass(frozen=True)
class Aligned:
    golds: list[Gold]
    preds: list[TriageResult]
    weights: list[float]


def align(examples: Sequence[EvalExample], predictions: Sequence[TriageResult]) -> Aligned:
    by_ref = {p.issue_ref: p for p in predictions}
    missing = [e.snapshot.issue_ref for e in examples if e.snapshot.issue_ref not in by_ref]
    if missing:
        raise ValueError(f"{len(missing)} examples have no prediction, e.g. {missing[:3]}")
    return Aligned(
        golds=[e.gold for e in examples],
        preds=[by_ref[e.snapshot.issue_ref] for e in examples],
        weights=[e.weight for e in examples],
    )


def statistic(
    fn: MetricFn, data: Aligned, weighted: bool = False
) -> Callable[[Sequence[int]], float | None]:
    def stat(idx: Sequence[int]) -> float | None:
        return fn(
            [data.golds[i] for i in idx],
            [data.preds[i] for i in idx],
            [data.weights[i] for i in idx] if weighted else None,
        )

    return stat


def score(
    examples: Sequence[EvalExample],
    predictions: Sequence[TriageResult],
    *,
    resamples: int = 1000,
    seed: int = 0,
) -> Scorecard:
    data = align(examples, predictions)
    n = len(data.golds)
    metrics: dict[str, MetricScore] = {}
    for name, fn in METRICS.items():
        ci = bootstrap_ci(n, statistic(fn, data), resamples=resamples, seed=seed)
        defined = ci.valid_resamples > 0
        metrics[name] = MetricScore(
            point=ci.point if defined else None,
            low=ci.low if defined else None,
            high=ci.high if defined else None,
            weighted=statistic(fn, data, weighted=True)(range(n)),
        )

    triaged = [(g, p) for g, p in zip(data.golds, data.preds, strict=True) if g.human_triaged]
    per_label = multilabel_prf(
        [set(g.labels) for g, _ in triaged], [set(p.labels) for _, p in triaged]
    )
    preds = data.preds
    return Scorecard(
        metrics=metrics,
        system=SystemStats(
            issues=n,
            errors=sum(p.error is not None for p in preds),
            cost_usd_total=sum(p.cost_usd for p in preds),
            cost_usd_per_issue=sum(p.cost_usd for p in preds) / n if n else 0.0,
            latency_ms_p50=percentile([float(p.latency_ms) for p in preds], 50),
            latency_ms_p95=percentile([float(p.latency_ms) for p in preds], 95),
            tokens_in_per_issue=sum(p.tokens_in for p in preds) / n if n else 0.0,
            tokens_out_per_issue=sum(p.tokens_out for p in preds) / n if n else 0.0,
        ),
        per_label_f1={k: v.f1 for k, v in per_label.per_label.items()},
    )
