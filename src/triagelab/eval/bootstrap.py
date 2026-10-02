"""Bootstrap confidence intervals, written by hand (AGENTS.md §1.3, §12.2).

With 100 dev and 50 test issues, the interval is most of the story. We resample *issues*
with replacement and recompute the metric on each resample; the 2.5th and 97.5th
percentiles of those recomputed values form the 95% interval (percentile bootstrap).

A statistic receives the list of resampled issue indices and returns a float, or None
when the metric is undefined on that resample (e.g. no positives drawn). Undefined
resamples are dropped and counted, not silently scored as zero.
"""

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from triagelab.eval.metrics import percentile

Statistic = Callable[[Sequence[int]], float | None]


@dataclass(frozen=True)
class Interval:
    point: float
    low: float
    high: float
    valid_resamples: int

    def __str__(self) -> str:
        return f"{self.point:.3f} [{self.low:.3f}, {self.high:.3f}]"


@dataclass(frozen=True)
class PairedDelta:
    """Difference B - A with a paired-bootstrap interval."""

    delta: float
    low: float
    high: float
    share_b_better: float  # fraction of resamples where B scored higher
    valid_resamples: int

    @property
    def significant(self) -> bool:
        """AGENTS.md §12.2: only call it a change if the interval excludes zero."""
        return self.low > 0 or self.high < 0


def _resample(n: int, rng: random.Random) -> list[int]:
    return [rng.randrange(n) for _ in range(n)]


def bootstrap_ci(
    n: int,
    statistic: Statistic,
    *,
    resamples: int = 1000,
    confidence: float = 0.95,
    seed: int = 0,
) -> Interval:
    point = statistic(range(n))
    if point is None or n == 0:
        return Interval(point=float("nan"), low=float("nan"), high=float("nan"), valid_resamples=0)
    rng = random.Random(seed)
    values = [v for _ in range(resamples) if (v := statistic(_resample(n, rng))) is not None]
    tail = 100 * (1 - confidence) / 2
    return Interval(
        point=point,
        low=percentile(values, tail),
        high=percentile(values, 100 - tail),
        valid_resamples=len(values),
    )


def paired_bootstrap(
    n: int,
    statistic_a: Statistic,
    statistic_b: Statistic,
    *,
    resamples: int = 1000,
    confidence: float = 0.95,
    seed: int = 0,
) -> PairedDelta:
    """Compare two systems scored on the *same* issues.

    Each resample draws one set of issues and scores both systems on it, so issue
    difficulty cancels out and only the per-issue difference between systems varies.
    That is far more sensitive than comparing two independent intervals.
    """
    a, b = statistic_a(range(n)), statistic_b(range(n))
    if a is None or b is None or n == 0:
        return PairedDelta(float("nan"), float("nan"), float("nan"), float("nan"), 0)
    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(resamples):
        idx = _resample(n, rng)
        va, vb = statistic_a(idx), statistic_b(idx)
        if va is not None and vb is not None:
            deltas.append(vb - va)
    tail = 100 * (1 - confidence) / 2
    return PairedDelta(
        delta=b - a,
        low=percentile(deltas, tail),
        high=percentile(deltas, 100 - tail),
        share_b_better=sum(d > 0 for d in deltas) / len(deltas) if deltas else float("nan"),
        valid_resamples=len(deltas),
    )


def zero_failure_bound(n: int, confidence: float = 0.95) -> float:
    """The largest failure rate still consistent with seeing 0 failures in `n` trials.

    A bootstrap interval is useless for a perfect score: every resample of 50 correct
    answers is 50 correct answers, so the interval is [1.00, 1.00] (M8: the routed
    system's type label on the CPython test split). The exact answer comes from asking
    which failure rate p would still have produced `n` clean trials with probability
    1 - confidence:

        (1 - p) ** n = 1 - confidence

    For 95% confidence it is close to 3 / n, the "rule of three". For n = 50 it is
    0.058, so the honest claim is "accuracy above 0.94", not 1.00.
    """
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if n == 0:
        return 1.0  # no trials: every failure rate is still possible
    return 1.0 - (1.0 - confidence) ** (1.0 / n)
