"""Hybrid search over the time-aware corpus: BM25 + dense, fused by reciprocal rank.

Every query takes a mandatory `as_of`; both rankers only see documents created strictly
before it (corpus order makes that a prefix), and the query issue itself can be excluded.
"""

from collections.abc import Set
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from triagelab.retrieval.bm25 import TimeAwareBM25
from triagelab.retrieval.corpus import Corpus, IndexedIssue
from triagelab.retrieval.dense import DenseIndex, Encoder
from triagelab.retrieval.fusion import reciprocal_rank_fusion
from triagelab.retrieval.text import tokenize

Mode = Literal["bm25", "dense", "hybrid"]

# Long bodies are mostly pasted logs; the head carries the report. Titles count twice.
_DOC_TOKENS = 1000
_QUERY_TOKENS = 400


def document_text(issue: IndexedIssue) -> str:
    return f"{issue.title}\n{issue.title}\n{issue.body}"


class Hit(BaseModel):
    number: int
    score: float
    bm25_rank: int | None
    dense_rank: int | None


class HybridSearcher:
    def __init__(
        self,
        corpus: Corpus,
        *,
        dense: DenseIndex | None = None,
        encoder: Encoder | None = None,
        depth: int = 50,
        rrf_k: int = 60,
    ) -> None:
        if (dense is None) != (encoder is None):
            raise ValueError("dense index and encoder go together")
        if dense is not None and len(dense) != len(corpus):
            raise ValueError(f"dense index has {len(dense)} rows for {len(corpus)} documents")
        self.corpus = corpus
        self._bm25 = TimeAwareBM25([tokenize(document_text(i), _DOC_TOKENS) for i in corpus.issues])
        self._dense, self._encoder = dense, encoder
        self._depth, self._rrf_k = depth, rrf_k
        self._index_of = {issue.number: idx for idx, issue in enumerate(corpus.issues)}

    @property
    def modes(self) -> tuple[Mode, ...]:
        return ("bm25", "dense", "hybrid") if self._dense is not None else ("bm25",)

    def search(
        self,
        query: str,
        *,
        as_of: datetime,
        k: int,
        exclude: Set[int] = frozenset(),
        mode: Mode = "hybrid",
    ) -> list[Hit]:
        if mode not in self.modes:
            mode = "bm25"
        visible = self.corpus.visible_count(as_of)
        excluded = {self._index_of[n] for n in exclude if n in self._index_of}

        lexical: list[int] = []
        if mode in ("bm25", "hybrid"):
            q_tokens = tokenize(query, _QUERY_TOKENS)
            lexical = [i for i, _ in self._bm25.top(q_tokens, visible, self._depth, excluded)]
        semantic: list[int] = []
        if mode in ("dense", "hybrid") and self._dense is not None and self._encoder is not None:
            q_vec = self._encoder.encode_queries([query])[0]
            semantic = [i for i, _ in self._dense.top(q_vec, visible, self._depth, excluded)]

        rankings = [r for r in (lexical, semantic) if r]
        fused = reciprocal_rank_fusion(rankings, k=self._rrf_k) if rankings else []
        lex_rank = {idx: r for r, idx in enumerate(lexical, start=1)}
        sem_rank = {idx: r for r, idx in enumerate(semantic, start=1)}
        issues = self.corpus.issues
        return [
            Hit(
                number=issues[idx].number,
                score=score,
                bm25_rank=lex_rank.get(idx),
                dense_rank=sem_rank.get(idx),
            )
            for idx, score in fused[:k]
        ]
