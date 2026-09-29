"""Metric tests: every expected value below is computed by hand in the comment beside it."""

import pytest

from triagelab.eval.metrics import (
    accuracy,
    binary_prf,
    duplicate_detection_prf,
    duplicate_prf,
    mean_reciprocal_rank,
    multilabel_prf,
    percentile,
    prf_from_counts,
    recall_at_k,
    top_k_accuracy,
)


def test_prf_from_counts() -> None:
    s = prf_from_counts(tp=3, fp=1, fn=2)  # P = 3/4, R = 3/5, F1 = 2*.75*.6/1.35 = 0.6667
    assert s.precision == pytest.approx(0.75)
    assert s.recall == pytest.approx(0.6)
    assert s.f1 == pytest.approx(2 / 3)
    assert s.support == 5


def test_zero_division_is_zero_not_error() -> None:
    s = prf_from_counts(0, 0, 0)
    assert (s.precision, s.recall, s.f1) == (0.0, 0.0, 0.0)


def test_binary_prf() -> None:
    gold = [True, True, False, False, True]
    pred = [True, False, True, False, True]  # tp=2, fp=1, fn=1 -> P=R=F1=2/3
    s = binary_prf(gold, pred)
    assert (s.tp, s.fp, s.fn) == (2, 1, 1)
    assert s.f1 == pytest.approx(2 / 3)


def test_binary_prf_weighted() -> None:
    # weights: the missed positive counts 3x -> tp=1, fp=0, fn=3 -> P=1, R=0.25, F1=0.4
    s = binary_prf([True, True], [True, False], weights=[1.0, 3.0])
    assert s.precision == pytest.approx(1.0)
    assert s.recall == pytest.approx(0.25)
    assert s.f1 == pytest.approx(0.4)


def test_multilabel_micro_and_macro() -> None:
    gold = [{"bug", "stdlib"}, {"feature"}, {"bug"}]
    pred = [{"bug"}, {"feature", "stdlib"}, set()]
    # bug:     tp=1 (item0), fn=1 (item2), fp=0 -> P=1, R=.5, F1=2/3
    # stdlib:  tp=0, fn=1 (item0), fp=1 (item1)  -> F1=0
    # feature: tp=1                              -> F1=1
    # micro: tp=2, fp=1, fn=2 -> P=2/3, R=1/2, F1=4/7
    # macro: (2/3 + 0 + 1) / 3 = 5/9
    s = multilabel_prf(gold, pred)
    assert s.per_label["bug"].f1 == pytest.approx(2 / 3)
    assert s.per_label["stdlib"].f1 == 0.0
    assert s.micro.f1 == pytest.approx(4 / 7)
    assert s.macro_f1 == pytest.approx(5 / 9)


def test_multilabel_label_space_restricts_scoring() -> None:
    s = multilabel_prf([{"bug"}], [{"bug", "noise"}], label_space={"bug"})
    assert s.micro.precision == 1.0  # "noise" is outside the space and not counted
    assert set(s.per_label) == {"bug"}


def test_duplicate_prf_requires_the_right_original() -> None:
    gold = [10, 20, None, None, 30]
    pred = [10, 99, 40, None, None]
    # item0 correct -> tp; item1 wrong original -> fp AND fn; item2 spurious -> fp;
    # item4 missed -> fn.  tp=1, fp=2, fn=2 -> P=1/3, R=1/3, F1=1/3
    s = duplicate_prf(gold, pred)
    assert (s.tp, s.fp, s.fn) == (1, 2, 2)
    assert s.f1 == pytest.approx(1 / 3)
    # Detection only: flagged-vs-not. tp=2 (0,1), fp=1 (2), fn=1 (4) -> F1 = 2/3
    assert duplicate_detection_prf(gold, pred).f1 == pytest.approx(2 / 3)


def test_recall_at_k_and_mrr() -> None:
    gold = [5, 7, 9]
    ranked = [[5, 1, 2], [1, 7, 3], [1, 2, 3]]
    assert recall_at_k(gold, ranked, 1) == pytest.approx(1 / 3)
    assert recall_at_k(gold, ranked, 2) == pytest.approx(2 / 3)
    # MRR = (1/1 + 1/2 + 0) / 3 = 0.5
    assert mean_reciprocal_rank(gold, ranked) == pytest.approx(0.5)


def test_accuracy_and_top_k() -> None:
    gold = ["stdlib", "docs", "build"]
    assert accuracy(gold, ["stdlib", None, "docs"]) == pytest.approx(1 / 3)
    ranked = [["stdlib"], ["tests", "docs"], ["docs", "tests", "infra", "build"]]
    assert top_k_accuracy(gold, ranked, 1) == pytest.approx(1 / 3)
    assert top_k_accuracy(gold, ranked, 3) == pytest.approx(2 / 3)  # "build" is 4th


def test_weighted_accuracy() -> None:
    # correct item weighs 1, wrong item weighs 3 -> 1/4
    assert accuracy(["a", "b"], ["a", "x"], weights=[1.0, 3.0]) == pytest.approx(0.25)


def test_percentile_matches_linear_interpolation() -> None:
    values = [10.0, 20.0, 30.0, 40.0]
    assert percentile(values, 50) == pytest.approx(25.0)
    assert percentile(values, 95) == pytest.approx(38.5)  # pos = 3*0.95 = 2.85
    assert percentile([], 50) == 0.0


def test_mismatched_weights_are_rejected() -> None:
    with pytest.raises(ValueError, match="weights"):
        binary_prf([True], [True], weights=[1.0, 2.0])
