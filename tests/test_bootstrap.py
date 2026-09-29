import math
import random
from collections.abc import Callable, Sequence

import pytest

from triagelab.eval.bootstrap import bootstrap_ci, paired_bootstrap


def mean_of(values: Sequence[float]) -> Callable[[Sequence[int]], float]:
    def stat(idx: Sequence[int]) -> float:
        return sum(values[i] for i in idx) / len(idx)

    return stat


def test_interval_brackets_the_point_estimate_and_is_deterministic() -> None:
    values = [float(i % 7) for i in range(100)]
    a = bootstrap_ci(100, mean_of(values), seed=3)
    b = bootstrap_ci(100, mean_of(values), seed=3)
    assert a == b
    assert a.low <= a.point <= a.high
    assert a.valid_resamples == 1000


def test_interval_width_matches_the_normal_approximation() -> None:
    # Bernoulli(0.3), n=400: SE = sqrt(.3*.7/400) = 0.0229 -> 95% half-width ~ 0.045
    rng = random.Random(0)
    values = [1.0 if rng.random() < 0.3 else 0.0 for _ in range(400)]
    ci = bootstrap_ci(400, mean_of(values), resamples=2000, seed=1)
    half_width = (ci.high - ci.low) / 2
    assert half_width == pytest.approx(1.96 * math.sqrt(0.3 * 0.7 / 400), rel=0.15)


def test_smaller_samples_give_wider_intervals() -> None:
    values = [float(i % 2) for i in range(200)]
    wide = bootstrap_ci(20, mean_of(values[:20]), seed=0)
    narrow = bootstrap_ci(200, mean_of(values), seed=0)
    assert (wide.high - wide.low) > (narrow.high - narrow.low)


def test_undefined_resamples_are_dropped_not_zeroed() -> None:
    values = [1.0] + [0.0] * 9

    def recall_like(idx: Sequence[int]) -> float | None:
        positives = [i for i in idx if values[i] == 1.0]
        return None if not positives else 1.0

    ci = bootstrap_ci(10, recall_like, seed=0)
    # P(no positive drawn in 10 draws) = 0.9^10 ~ 35%, so roughly 650 valid resamples.
    assert 550 < ci.valid_resamples < 750
    assert ci.low == ci.high == 1.0


def test_paired_identical_systems_have_zero_delta() -> None:
    values = [float(i % 3) for i in range(50)]
    d = paired_bootstrap(50, mean_of(values), mean_of(values))
    assert (d.delta, d.low, d.high) == (0.0, 0.0, 0.0)
    assert not d.significant


def test_paired_bootstrap_detects_a_consistent_improvement() -> None:
    a = [0.0] * 30 + [1.0] * 20  # 40% correct
    b = [1.0] * 40 + [0.0] * 10  # 80% correct, and right wherever a is right
    d = paired_bootstrap(50, mean_of(a), mean_of(b), seed=0)
    assert d.delta == pytest.approx(0.4)
    assert d.significant
    assert d.low > 0
    assert d.share_b_better == 1.0
