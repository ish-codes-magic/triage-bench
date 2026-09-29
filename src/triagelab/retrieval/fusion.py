"""Reciprocal rank fusion (Cormack, Clarke & Buettcher, 2009), written by hand.

    score(d) = sum over rankers r of  w_r / (k + rank_r(d))      (rank starts at 1)

Only ranks are used, never raw scores, so BM25 scores (unbounded) and cosine similarities
([-1, 1]) combine without any calibration. k = 60 is the paper's default; it damps the
advantage of being first, so agreement between rankers matters more than one top hit.
"""

from collections.abc import Sequence


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[int]],
    *,
    k: int = 60,
    weights: Sequence[float] | None = None,
) -> list[tuple[int, float]]:
    """Fuse ranked lists of item ids into one ranking of (id, fused score), best first."""
    w = weights if weights is not None else [1.0] * len(rankings)
    if len(w) != len(rankings):
        raise ValueError("one weight per ranking")
    scores: dict[int, float] = {}
    for ranking, weight in zip(rankings, w, strict=True):
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + weight / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
