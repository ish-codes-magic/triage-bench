"""Calibration metrics on hand-computed cases."""

import pytest

from triagelab.eval.calibration import aurc, brier, ece, reliability_bins, risk_coverage

# Four answers: two at 0.9 (one right), one right at 0.6, one wrong at 0.3.
CONF = [0.9, 0.9, 0.6, 0.3]
RIGHT = [True, False, True, False]


def test_equal_width_bins_and_ece() -> None:
    bins = reliability_bins(CONF, RIGHT, n_bins=10, strategy="width")
    assert [(b.lo, b.n, b.confidence, b.accuracy) for b in bins] == [
        (0.3, 1, 0.3, 0.0),
        (0.6, 1, 0.6, 1.0),
        (0.9, 2, 0.9, 0.5),
    ]
    # 1/4 * |0 - 0.3| + 1/4 * |1 - 0.6| + 2/4 * |0.5 - 0.9| = 0.075 + 0.1 + 0.2
    assert ece(CONF, RIGHT, 10, "width") == pytest.approx(0.375)


def test_equal_mass_bins_and_ece() -> None:
    bins = reliability_bins(CONF, RIGHT, n_bins=2, strategy="mass")
    assert [(b.n, b.confidence, b.accuracy) for b in bins] == [
        (2, pytest.approx(0.45), 0.5),
        (2, pytest.approx(0.9), 0.5),
    ]
    # 2/4 * |0.5 - 0.45| + 2/4 * |0.5 - 0.9| = 0.025 + 0.2
    assert ece(CONF, RIGHT, 2, "mass") == pytest.approx(0.225)


def test_brier() -> None:
    # (0.01 + 0.81 + 0.16 + 0.09) / 4
    assert brier(CONF, RIGHT) == pytest.approx(0.2675)


def test_risk_coverage_keeps_ties_together() -> None:
    points = risk_coverage(CONF, RIGHT)
    assert [(p.coverage, p.accuracy, p.threshold) for p in points] == [
        (0.5, 0.5, 0.9),  # both 0.9 answers enter together
        (0.75, pytest.approx(2 / 3), 0.6),
        (1.0, 0.5, 0.3),
    ]
    # 0.5 * (1 - 0.5) + 0.25 * (1 - 2/3) + 0.25 * (1 - 0.5)
    assert aurc(CONF, RIGHT) == pytest.approx(0.25 + 0.25 / 3 + 0.125)


def test_perfect_calibration_and_the_top_edge() -> None:
    assert ece([0.5, 0.5, 0.5, 0.5], [True, False, True, False]) == 0.0
    top = reliability_bins([1.0, 1.0], [True, True], n_bins=10)
    assert len(top) == 1
    assert top[0].lo == 0.9  # confidence 1.0 lands in the last bin, not an 11th one


def test_invalid_input_is_refused() -> None:
    with pytest.raises(ValueError, match="same length"):
        brier([0.5], [True, False])
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        ece([1.5], [True])
    assert reliability_bins([], []) == []
