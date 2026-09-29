"""Embedding store and dense index, with a deterministic fake encoder (no model download)."""

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from triagelab.retrieval.corpus import Corpus, build_corpus
from triagelab.retrieval.dense import DenseIndex, Matrix
from triagelab.retrieval.embeddings import embed_corpus, embedded_numbers, load_matrix
from triagelab.retrieval.search import HybridSearcher

from .data_fixtures import raw


class HashEncoder:
    """Bag-of-letters vectors: similar strings get similar vectors, deterministically."""

    name = "test/hash"

    def __init__(self) -> None:
        self.calls = 0

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(26, dtype=np.float32)
        for ch in text.lower():
            if "a" <= ch <= "z":
                v[ord(ch) - 97] += 1
        return v

    def encode_documents(self, texts: Sequence[str]) -> Matrix:
        self.calls += len(texts)
        return np.stack([self._vec(t) for t in texts])

    def encode_queries(self, texts: Sequence[str]) -> Matrix:
        return np.stack([self._vec(t) for t in texts])


def corpus_of(n: int) -> Corpus:
    base = raw()
    assert base.original_body is not None
    issues = []
    for i in range(1, n + 1):
        created = base.created_at + timedelta(days=i - 1)
        body = "zzzz" if i == 2 else f"aaaa bbbb {i}"
        issues.append(
            base.model_copy(
                update={
                    "number": i,
                    "created_at": created,
                    "title_renames": (),
                    "title": body,
                    "original_body": base.original_body.model_copy(
                        update={"at": created, "body": body}
                    ),
                }
            )
        )
    return build_corpus(issues)


def test_build_is_resumable_and_keyed_by_number(tmp_path: Path) -> None:
    enc = HashEncoder()
    assert embed_corpus(corpus_of(5), enc, tmp_path, chunk_size=2) == 5
    assert embedded_numbers(tmp_path) == {1, 2, 3, 4, 5}
    assert embed_corpus(corpus_of(7), enc, tmp_path, chunk_size=2) == 2  # only the new ones
    assert enc.calls == 7
    matrix = load_matrix(corpus_of(7), tmp_path)
    assert matrix.shape == (7, 26)


def test_a_write_killed_midway_does_not_break_resume(tmp_path: Path) -> None:
    embed_corpus(corpus_of(2), HashEncoder(), tmp_path, chunk_size=2)
    (tmp_path / "chunk-00001.npz.tmp").write_bytes(b"truncated")  # what a kill leaves
    assert embedded_numbers(tmp_path) == {1, 2}
    assert embed_corpus(corpus_of(4), HashEncoder(), tmp_path, chunk_size=2) == 2
    assert load_matrix(corpus_of(4), tmp_path).shape == (4, 26)
    assert not list(tmp_path.glob("*.tmp"))  # the rename consumed it


def test_missing_vectors_fail_loudly(tmp_path: Path) -> None:
    embed_corpus(corpus_of(3), HashEncoder(), tmp_path)
    with pytest.raises(ValueError, match="no embedding"):
        load_matrix(corpus_of(4), tmp_path)


def test_dense_search_respects_as_of_and_hybrid_fuses(tmp_path: Path) -> None:
    corpus = corpus_of(4)
    enc = HashEncoder()
    embed_corpus(corpus, enc, tmp_path)
    searcher = HybridSearcher(corpus, dense=DenseIndex(load_matrix(corpus, tmp_path)), encoder=enc)
    as_of = corpus.issues[3].created_at  # issues 1-3 visible
    dense_hits = searcher.search("zzzz", as_of=as_of, k=3, mode="dense")
    assert dense_hits[0].number == 2
    assert 4 not in [h.number for h in dense_hits]
    hybrid = searcher.search("zzzz", as_of=as_of, k=3, mode="hybrid")
    assert hybrid[0].number == 2
    assert hybrid[0].dense_rank == 1
    assert hybrid[0].bm25_rank == 1


def test_dense_index_rejects_mismatched_corpus(tmp_path: Path) -> None:
    corpus = corpus_of(3)
    with pytest.raises(ValueError, match="rows"):
        HybridSearcher(
            corpus, dense=DenseIndex(np.ones((2, 4), dtype=np.float32)), encoder=HashEncoder()
        )
