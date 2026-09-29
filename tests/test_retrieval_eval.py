"""Retrieval scoring and paired comparison, on hand-computed rankings."""

import pytest

from triagelab.retrieval.evaluate import Comparison, Rankings, compare, compare_all, render, score

# Query 3's original predates the index: unreachable, a miss for every retriever.
GOLD = [10, 20, 30]
REACHABLE = [True, True, False]


def rankings(mode: str, ranked: list[list[int]]) -> Rankings:
    return Rankings(mode=mode, gold=GOLD, ranked=ranked, reachable=REACHABLE)


WEAK = rankings("bm25", [[10, 1], [1, 20], [5, 6]])  # ranks 1, 2, miss
STRONG = rankings("dense", [[10], [20], [5]])  # ranks 1, 1, miss


def test_score_separates_all_queries_from_reachable_ones() -> None:
    report = score(WEAK, resamples=50)
    assert (report.queries, report.reachable) == (3, 2)
    assert report.recall_all[1].point == pytest.approx(1 / 3)
    assert report.mrr_all.point == pytest.approx((1 + 1 / 2 + 0) / 3)
    assert report.recall_reachable[1].point == pytest.approx(1 / 2)
    assert report.recall_reachable[5].point == pytest.approx(1.0)
    assert report.mrr_reachable.point == pytest.approx((1 + 1 / 2) / 2)


def test_compare_reports_b_minus_a_on_reachable_queries() -> None:
    by_metric = {c.metric: c for c in compare(WEAK, STRONG, resamples=200)}
    assert by_metric["MRR"].delta == pytest.approx(1.0 - 0.75)
    assert by_metric["Recall@10"].delta == pytest.approx(0.0)
    assert not by_metric["Recall@10"].significant  # identical on every query
    assert (by_metric["MRR"].a, by_metric["MRR"].b) == ("bm25", "dense")


def test_compare_refuses_rankings_over_different_queries() -> None:
    other = Rankings(mode="dense", gold=[10, 20, 99], ranked=[[], [], []], reachable=REACHABLE)
    with pytest.raises(ValueError, match="different queries"):
        compare(WEAK, other)


def test_compare_all_pairs_each_later_retriever_with_each_earlier_one() -> None:
    hybrid = rankings("hybrid", [[10], [1, 20], [5]])
    pairs = {(c.b, c.a) for c in compare_all([WEAK, STRONG, hybrid], resamples=20)}
    assert pairs == {("dense", "bm25"), ("hybrid", "bm25"), ("hybrid", "dense")}


def test_render_bolds_only_significant_deltas() -> None:
    def c(metric: str, low: float, high: float) -> Comparison:
        return Comparison(
            a="bm25", b="dense", metric=metric, delta=(low + high) / 2, low=low, high=high,
            significant=low > 0 or high < 0,
        )  # fmt: skip

    text = render(
        [score(WEAK, resamples=20), score(STRONG, resamples=20)],
        "o/r",
        comparisons=[c("MRR", 0.05, 0.25), c("Recall@10", -0.02, 0.10)],
        notes=["Dense encoder: `x`; query prefix: none."],
    )
    assert "| dense - bm25 | **+0.150 [+0.050, +0.250]** | +0.040 [-0.020, +0.100] |" in text
    assert "query prefix: none" in text
