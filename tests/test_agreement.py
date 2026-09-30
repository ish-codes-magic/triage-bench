"""Agreement metrics: hand-computed cases, edge cases, and a cross-check with scikit-learn."""

import random

import pytest
from sklearn.metrics import cohen_kappa_score  # pyright: ignore[reportUnknownVariableType]

from triagelab.eval.agreement import (
    adjacent_agreement,
    cohen_kappa,
    exact_agreement,
    weighted_kappa,
)


def test_cohen_kappa_by_hand() -> None:
    # p_o = 3/4. Rater a says yes 2/4, b says yes 1/4:
    # p_e = (2/4)(1/4) + (2/4)(3/4) = 1/8 + 3/8 = 1/2, so kappa = (3/4 - 1/2) / (1/2) = 1/2.
    assert cohen_kappa([1, 1, 0, 0], [1, 0, 0, 0]) == pytest.approx(0.5)


def test_cohen_kappa_extremes() -> None:
    assert cohen_kappa(["a", "b", "c"], ["a", "b", "c"]) == pytest.approx(1.0)
    # Systematic disagreement on a balanced binary task: p_o = 0, p_e = 1/2, kappa = -1.
    assert cohen_kappa([0, 1, 0, 1], [1, 0, 1, 0]) == pytest.approx(-1.0)
    assert cohen_kappa(["x", "x"], ["x", "x"]) is None  # chance agreement is already 1
    assert cohen_kappa([], []) is None


def test_weighted_kappa_by_hand() -> None:
    # Two items, scores swapped on a 1-2 scale: every weight is 1.
    # observed = 1; expected = sum over i != j of 1 * (1/2)(1/2) = 1/2; kappa = 1 - 1/(1/2) = -1.
    assert weighted_kappa([1, 2], [2, 1], [1, 2]) == pytest.approx(-1.0)
    assert weighted_kappa([1, 2, 3, 4], [1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)


def test_near_misses_cost_less_than_far_misses() -> None:
    truth = [1, 2, 3, 4, 1, 2, 3, 4]
    near = [2, 2, 3, 3, 1, 2, 4, 4]  # three items off by one
    far = [4, 2, 3, 1, 1, 2, 4, 4]  # one item off by one, two off by three
    k_near = weighted_kappa(truth, near, [1, 2, 3, 4])
    k_far = weighted_kappa(truth, far, [1, 2, 3, 4])
    assert k_near is not None
    assert k_far is not None
    assert k_near > k_far


def test_matches_scikit_learn_on_random_ratings() -> None:
    rng = random.Random(0)
    for _ in range(20):
        a = [rng.randint(1, 4) for _ in range(40)]
        b = [min(4, max(1, x + rng.choice([-1, 0, 0, 1, 2]))) for x in a]
        assert cohen_kappa(a, b) == pytest.approx(cohen_kappa_score(a, b))
        expected = cohen_kappa_score(a, b, weights="quadratic", labels=[1, 2, 3, 4])
        assert weighted_kappa(a, b, [1, 2, 3, 4]) == pytest.approx(expected)


def test_plain_agreement_rates() -> None:
    assert exact_agreement([1, 2, 3, 4], [1, 2, 4, 4]) == pytest.approx(0.75)
    assert adjacent_agreement([1, 2, 3, 4], [1, 3, 1, 4]) == pytest.approx(0.75)  # 3 vs 1 is 2 off
    assert exact_agreement([], []) is None


def test_mismatched_or_unknown_ratings_are_errors() -> None:
    with pytest.raises(ValueError, match="same items"):
        cohen_kappa([1, 2], [1])
    with pytest.raises(ValueError, match="outside the categories"):
        weighted_kappa([1, 5], [1, 2], [1, 2, 3, 4])
