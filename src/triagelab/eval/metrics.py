"""Task metrics, written by hand (AGENTS.md §1.3) and tested against hand-computed cases.

Conventions:
  - Every function takes optional per-issue `weights`. Unweighted = the stratified sample
    as drawn; weighted with the stored sampling weights = a natural-rate estimate.
  - 0/0 is scored as 0 (sklearn's `zero_division=0`), and `support` is always reported
    so a 0 caused by having no positives is recognisable.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PRF:
    precision: float
    recall: float
    f1: float
    tp: float
    fp: float
    fn: float

    @property
    def support(self) -> float:
        return self.tp + self.fn


def _div(a: float, b: float) -> float:
    return a / b if b else 0.0


def prf_from_counts(tp: float, fp: float, fn: float) -> PRF:
    p = _div(tp, tp + fp)
    r = _div(tp, tp + fn)
    return PRF(precision=p, recall=r, f1=_div(2 * p * r, p + r), tp=tp, fp=fp, fn=fn)


def _weights(n: int, weights: Sequence[float] | None) -> Sequence[float]:
    if weights is None:
        return [1.0] * n
    if len(weights) != n:
        raise ValueError(f"{len(weights)} weights for {n} items")
    return weights


# ---- T4 (and any binary task) ---------------------------------------------------------------


def binary_prf(
    gold: Sequence[bool], pred: Sequence[bool], weights: Sequence[float] | None = None
) -> PRF:
    w = _weights(len(gold), weights)
    tp = sum(wi for g, p, wi in zip(gold, pred, w, strict=True) if g and p)
    fp = sum(wi for g, p, wi in zip(gold, pred, w, strict=True) if p and not g)
    fn = sum(wi for g, p, wi in zip(gold, pred, w, strict=True) if g and not p)
    return prf_from_counts(tp, fp, fn)


# ---- T1: multi-label -------------------------------------------------------------------------


@dataclass(frozen=True)
class MultiLabelScores:
    micro: PRF
    macro_f1: float
    per_label: dict[str, PRF]


def multilabel_prf(
    gold: Sequence[set[str]],
    pred: Sequence[set[str]],
    weights: Sequence[float] | None = None,
    label_space: set[str] | None = None,
) -> MultiLabelScores:
    """Micro (pooled counts) and macro (mean of per-label F1) scores.

    The label space defaults to every label seen in gold or predictions, so predicting a
    label that never occurs costs macro F1 as well as micro precision.
    """
    w = _weights(len(gold), weights)
    empty: set[str] = set()
    space = label_space if label_space is not None else empty.union(*gold, *pred)
    per_label: dict[str, PRF] = {}
    for label in sorted(space):
        tp = sum(wi for g, p, wi in zip(gold, pred, w, strict=True) if label in g and label in p)
        fp = sum(
            wi for g, p, wi in zip(gold, pred, w, strict=True) if label in p and label not in g
        )
        fn = sum(
            wi for g, p, wi in zip(gold, pred, w, strict=True) if label in g and label not in p
        )
        per_label[label] = prf_from_counts(tp, fp, fn)
    micro = prf_from_counts(
        sum(s.tp for s in per_label.values()),
        sum(s.fp for s in per_label.values()),
        sum(s.fn for s in per_label.values()),
    )
    macro = _div(sum(s.f1 for s in per_label.values()), len(per_label))
    return MultiLabelScores(micro=micro, macro_f1=macro, per_label=per_label)


# ---- T2: duplicates --------------------------------------------------------------------------


def duplicate_prf(
    gold: Sequence[int | None],
    pred: Sequence[int | None],
    weights: Sequence[float] | None = None,
) -> PRF:
    """A duplicate counts only if the *right original* is named.

    Naming the wrong original is both a false positive (a wrong link was made) and a
    false negative (the right one was missed), as in standard entity-linking scoring.
    """
    w = _weights(len(gold), weights)
    tp = fp = fn = 0.0
    for g, p, wi in zip(gold, pred, w, strict=True):
        if p is not None and p == g:
            tp += wi
            continue
        if p is not None:
            fp += wi
        if g is not None:
            fn += wi
    return prf_from_counts(tp, fp, fn)


def duplicate_detection_prf(
    gold: Sequence[int | None],
    pred: Sequence[int | None],
    weights: Sequence[float] | None = None,
) -> PRF:
    """Looser view: was the issue flagged as a duplicate at all (original ignored)?"""
    return binary_prf([g is not None for g in gold], [p is not None for p in pred], weights)


def recall_at_k(gold: Sequence[int], ranked: Sequence[Sequence[int]], k: int) -> float:
    """Share of duplicates whose true original appears in the top k candidates."""
    if not gold:
        return 0.0
    return sum(g in list(r)[:k] for g, r in zip(gold, ranked, strict=True)) / len(gold)


def mean_reciprocal_rank(gold: Sequence[int], ranked: Sequence[Sequence[int]]) -> float:
    """Mean of 1/rank of the true original (0 when it isn't retrieved at all)."""
    if not gold:
        return 0.0
    total = 0.0
    for g, r in zip(gold, ranked, strict=True):
        candidates = list(r)
        if g in candidates:
            total += 1.0 / (candidates.index(g) + 1)
    return total / len(gold)


# ---- T3: component ---------------------------------------------------------------------------


def accuracy(
    gold: Sequence[str], pred: Sequence[str | None], weights: Sequence[float] | None = None
) -> float:
    w = _weights(len(gold), weights)
    return _div(sum(wi for g, p, wi in zip(gold, pred, w, strict=True) if g == p), sum(w))


def top_k_accuracy(
    gold: Sequence[str],
    ranked: Sequence[Sequence[str]],
    k: int,
    weights: Sequence[float] | None = None,
) -> float:
    w = _weights(len(gold), weights)
    hits = sum(wi for g, r, wi in zip(gold, ranked, w, strict=True) if g in list(r)[:k])
    return _div(hits, sum(w))


# ---- System metrics --------------------------------------------------------------------------


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile (numpy's default), q in [0, 100]."""
    if not values:
        return 0.0
    s = sorted(values)
    pos = (len(s) - 1) * q / 100
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)
