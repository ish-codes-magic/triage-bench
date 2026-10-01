"""Calibration metrics, written by hand (AGENTS.md §1.3, §12.5).

A decision is *calibrated* when, among answers given with confidence c, a fraction c is
right. Everything here works on two parallel sequences: `conf` (the confidence a backend
gave its answer) and `correct` (whether the answer was right).

  reliability bins   equal-width (confidence in [0, 0.1), ...) or equal-mass (each bin
                     the same number of answers, so sparse regions don't hide behind
                     empty bins)
  ECE                sum over bins of (bin share) * |accuracy - mean confidence|
  Brier score        mean squared gap between confidence and the 0/1 outcome; unlike ECE
                     it also rewards *discrimination* (confident when right, unsure when
                     wrong), not just average honesty
  risk-coverage      answer only the most confident X%: how accurate is that subset? The
                     area under the risk curve (AURC) summarises it; lower is better
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

BinStrategy = Literal["width", "mass"]


@dataclass(frozen=True)
class Bin:
    lo: float
    hi: float
    n: int
    confidence: float  # mean confidence in the bin
    accuracy: float  # share of correct answers in the bin


def _check(conf: Sequence[float], correct: Sequence[bool]) -> None:
    if len(conf) != len(correct):
        raise ValueError("conf and correct must have the same length")
    if any(not 0.0 <= c <= 1.0 for c in conf):
        raise ValueError("confidences must lie in [0, 1]")


def _bin(
    members: Sequence[int], conf: Sequence[float], correct: Sequence[bool], lo: float, hi: float
) -> Bin:
    n = len(members)
    return Bin(
        lo=lo,
        hi=hi,
        n=n,
        confidence=sum(conf[i] for i in members) / n,
        accuracy=sum(correct[i] for i in members) / n,
    )


def reliability_bins(
    conf: Sequence[float],
    correct: Sequence[bool],
    n_bins: int = 10,
    strategy: BinStrategy = "width",
) -> list[Bin]:
    """Non-empty bins, in order of confidence."""
    _check(conf, correct)
    if not conf:
        return []
    if strategy == "width":
        groups: dict[int, list[int]] = {}
        for i, c in enumerate(conf):
            # The top edge belongs to the last bin: confidence 1.0 isn't a bin of its own.
            groups.setdefault(min(int(c * n_bins), n_bins - 1), []).append(i)
        return [
            _bin(groups[b], conf, correct, b / n_bins, (b + 1) / n_bins) for b in sorted(groups)
        ]
    order = sorted(range(len(conf)), key=lambda i: conf[i])
    size = len(order) / n_bins
    bins: list[Bin] = []
    for b in range(n_bins):
        members = order[round(b * size) : round((b + 1) * size)]
        if members:
            bins.append(_bin(members, conf, correct, conf[members[0]], conf[members[-1]]))
    return bins


def ece(
    conf: Sequence[float],
    correct: Sequence[bool],
    n_bins: int = 10,
    strategy: BinStrategy = "width",
) -> float:
    bins = reliability_bins(conf, correct, n_bins, strategy)
    total = sum(b.n for b in bins)
    return sum(b.n / total * abs(b.accuracy - b.confidence) for b in bins) if total else 0.0


def brier(conf: Sequence[float], correct: Sequence[bool]) -> float:
    _check(conf, correct)
    return sum((c - float(y)) ** 2 for c, y in zip(conf, correct, strict=True)) / len(conf)


@dataclass(frozen=True)
class CoveragePoint:
    coverage: float  # share of answers kept
    accuracy: float  # accuracy of the kept answers
    threshold: float  # the lowest confidence kept


def risk_coverage(conf: Sequence[float], correct: Sequence[bool]) -> list[CoveragePoint]:
    """Accuracy of the k most confident answers, for every k.

    Ties are kept together: a threshold can't separate answers of equal confidence, so a
    point is only emitted where the confidence changes (and at full coverage).
    """
    _check(conf, correct)
    order = sorted(range(len(conf)), key=lambda i: -conf[i])
    points: list[CoveragePoint] = []
    hits = 0
    for k, i in enumerate(order, start=1):
        hits += correct[i]
        last = k == len(order)
        if last or conf[order[k]] < conf[i]:
            points.append(CoveragePoint(k / len(order), hits / k, conf[i]))
    return points


def aurc(conf: Sequence[float], correct: Sequence[bool]) -> float:
    """Area under the risk (1 - accuracy) vs coverage curve, with step interpolation."""
    area, prev = 0.0, 0.0
    for p in risk_coverage(conf, correct):
        area += (p.coverage - prev) * (1 - p.accuracy)
        prev = p.coverage
    return area
