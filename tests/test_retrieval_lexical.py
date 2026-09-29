"""BM25 and RRF against hand-computed values, plus the time-awareness property."""

import math

import pytest

from triagelab.retrieval.bm25 import TimeAwareBM25
from triagelab.retrieval.fusion import reciprocal_rank_fusion
from triagelab.retrieval.text import tokenize


def test_tokenize_splits_identifiers_and_drops_stopwords() -> None:
    assert tokenize("The asyncio.run() call RAISES RuntimeError in 3.14") == [
        "asyncio",
        "run",
        "call",
        "raises",
        "runtimeerror",
        "14",
    ]


DOCS = [["cat", "sat"], ["dog", "sat"], ["cat", "cat", "ran"]]


def test_bm25_matches_hand_computation() -> None:
    bm25 = TimeAwareBM25(DOCS, k1=1.2, b=0.75)
    # All 3 docs visible: N=3, avgdl=(2+2+3)/3=7/3. "cat" appears in docs 0 and 2 (n_t=2).
    idf = math.log(1 + (3 - 2 + 0.5) / (2 + 0.5))

    def term(tf: int, dl: int) -> float:
        return idf * tf * 2.2 / (tf + 1.2 * (1 - 0.75 + 0.75 * dl / (7 / 3)))

    scores = bm25.scores(["cat"], visible=3)
    assert scores[0] == pytest.approx(term(1, 2))
    assert scores[2] == pytest.approx(term(2, 3))
    assert 1 not in scores


def test_statistics_come_only_from_visible_docs() -> None:
    bm25 = TimeAwareBM25(DOCS)
    # As of doc 2's creation only docs 0-1 exist: "cat" has n_t=1 of N=2, avgdl=2.
    idf_past = math.log(1 + (2 - 1 + 0.5) / (1 + 0.5))
    expected = idf_past * 1 * 2.2 / (1 + 1.2 * (1 - 0.75 + 0.75 * 2 / 2))
    assert bm25.scores(["cat"], visible=2) == pytest.approx({0: expected})


def test_future_docs_never_change_past_rankings() -> None:
    past = TimeAwareBM25(DOCS[:2])
    with_future = TimeAwareBM25([*DOCS, ["cat", "cat", "cat", "sat"]])
    for query in (["cat"], ["sat"], ["cat", "sat"]):
        assert with_future.scores(query, visible=2) == pytest.approx(past.scores(query, visible=2))


def test_top_excludes_and_breaks_ties_by_index() -> None:
    bm25 = TimeAwareBM25([["x"], ["x"], ["y"]])
    assert [i for i, _ in bm25.top(["x"], visible=3, k=5)] == [0, 1]
    assert [i for i, _ in bm25.top(["x"], visible=3, k=5, exclude={0})] == [1]


def test_rrf_matches_hand_computation() -> None:
    # A: [1, 2, 3]; B: [3, 1]. k=60.
    fused = dict(reciprocal_rank_fusion([[1, 2, 3], [3, 1]], k=60))
    assert fused[1] == pytest.approx(1 / 61 + 1 / 62)
    assert fused[3] == pytest.approx(1 / 63 + 1 / 61)
    assert fused[2] == pytest.approx(1 / 62)


def test_rrf_rewards_agreement_over_a_single_top_hit() -> None:
    ranking = reciprocal_rank_fusion([[7, 1], [8, 1], [9, 1]])
    assert ranking[0][0] == 1  # second everywhere beats first once


def test_rrf_weights() -> None:
    fused = dict(reciprocal_rank_fusion([[1], [2]], weights=[2.0, 1.0], k=0))
    assert fused == {1: 2.0, 2: 1.0}
