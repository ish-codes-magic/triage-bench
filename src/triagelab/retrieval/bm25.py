"""BM25 whose statistics only ever come from documents visible at query time.

A standard BM25 index computes IDF and average document length over *every* indexed
document, so issues filed after the query issue would still shape its ranking. That is
leakage by statistics (AGENTS.md §7.2). Here documents are stored oldest-first with
per-term posting lists, so for a query "as of" document index `n` the document
frequencies, collection size and average length are computed over exactly docs [0, n).

Scoring (Lucene-style, non-negative IDF):
    idf(t)     = ln(1 + (N - n_t + 0.5) / (n_t + 0.5))
    score(d,q) = sum over distinct t in q of
                 idf(t) * tf(t,d) * (k1 + 1) / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))
"""

import math
from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Sequence, Set
from itertools import accumulate


class TimeAwareBM25:
    def __init__(self, docs: Sequence[list[str]], *, k1: float = 1.2, b: float = 0.75) -> None:
        """`docs` must be tokenised and ordered oldest-first (the corpus order)."""
        self.k1, self.b = k1, b
        self._tf = [Counter(d) for d in docs]
        self._lengths = [len(d) for d in docs]
        self._cum_lengths = [0, *accumulate(self._lengths)]
        postings: defaultdict[str, list[int]] = defaultdict(list)
        for idx, tf in enumerate(self._tf):
            for term in tf:
                postings[term].append(idx)  # ascending, because idx only grows
        self._postings = dict(postings)

    def __len__(self) -> int:
        return len(self._tf)

    def scores(self, query: Sequence[str], visible: int) -> dict[int, float]:
        """BM25 score of every visible doc sharing a term with the query (doc idx -> score)."""
        n_docs = min(visible, len(self._tf))
        if n_docs == 0:
            return {}
        avgdl = self._cum_lengths[n_docs] / n_docs or 1.0
        out: dict[int, float] = {}
        for term in set(query):
            posting = self._postings.get(term)
            if not posting:
                continue
            n_t = bisect_left(posting, n_docs)  # docs < n_docs containing the term
            if n_t == 0:
                continue
            idf = math.log(1 + (n_docs - n_t + 0.5) / (n_t + 0.5))
            for idx in posting[:n_t]:
                tf = self._tf[idx][term]
                norm = self.k1 * (1 - self.b + self.b * self._lengths[idx] / avgdl)
                out[idx] = out.get(idx, 0.0) + idf * tf * (self.k1 + 1) / (tf + norm)
        return out

    def top(
        self, query: Sequence[str], visible: int, k: int, exclude: Set[int] = frozenset()
    ) -> list[tuple[int, float]]:
        ranked = sorted(
            ((i, s) for i, s in self.scores(query, visible).items() if i not in exclude),
            key=lambda pair: (-pair[1], pair[0]),
        )
        return ranked[:k]
