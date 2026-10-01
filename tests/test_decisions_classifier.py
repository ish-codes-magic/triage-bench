"""The classifier decision backend: heads, renormalised confidences, the embedding cache."""

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from triagelab.decisions.base import DecisionError
from triagelab.decisions.classifier import CachedEncoder, ClassifierBackend, fit_head
from triagelab.retrieval.dense import Matrix

WORDS = ("crash", "segfault", "docs", "typo", "slow")


class KeywordEncoder:
    """Deterministic 'embeddings': one dimension per keyword. Counts what it encodes."""

    name = "keywords"

    def __init__(self) -> None:
        self.encoded = 0

    def encode_documents(self, texts: Sequence[str]) -> Matrix:
        self.encoded += len(texts)
        return np.array([[float(w in t) for w in WORDS] for t in texts], dtype=np.float32)

    def encode_queries(self, texts: Sequence[str]) -> Matrix:
        return self.encode_documents(texts)


TRAIN = [
    ("python crash segfault", "type-crash"),
    ("segfault in ctypes", "type-crash"),
    ("crash on exit", "type-crash"),
    ("typo in docs", "type-docs"),
    ("docs wrong", "type-docs"),
    ("docs typo again", "type-docs"),
    ("slow sort", "type-bug"),
    ("wrong result", "type-bug"),
    ("bad output slow", "type-bug"),
]
QUESTION = "Which type label fits?"


def trained(encoder: KeywordEncoder) -> ClassifierBackend:
    vectors = encoder.encode_documents([t for t, _ in TRAIN])
    head = fit_head(vectors, [a for _, a in TRAIN], c=10.0)
    return ClassifierBackend(encoder, {QUESTION: head})


def test_choice_is_renormalised_over_the_offered_options() -> None:
    backend = trained(KeywordEncoder())
    d = backend.choose("segfault crash", QUESTION, ["type-crash", "type-docs", "type-bug"])
    assert d.answer == "type-crash"
    assert sum(d.distribution.values()) == pytest.approx(1.0)
    assert d.confidence == d.distribution["type-crash"]
    assert (d.backend, d.cost_usd) == ("classifier", 0.0)
    two = backend.choose("segfault crash", QUESTION, ["type-docs", "type-bug"])
    assert set(two.distribution) == {"type-docs", "type-bug"}  # only what was asked
    assert sum(two.distribution.values()) == pytest.approx(1.0)


def test_unknown_questions_and_numbers_are_refused() -> None:
    backend = trained(KeywordEncoder())
    with pytest.raises(DecisionError, match="no trained head"):
        backend.choose("x", "Which component?", ["a", "b"])
    with pytest.raises(DecisionError):
        backend.score("x", QUESTION, 0, 1)


def test_a_single_class_head_is_a_constant_answer() -> None:
    head = fit_head(np.ones((3, 2), dtype=np.float32), ["a", "a", "a"])
    assert head.probabilities(np.zeros((2, 2), dtype=np.float32)) == [{"a": 1.0}, {"a": 1.0}]
    with pytest.raises(DecisionError):
        fit_head(np.ones((0, 2), dtype=np.float32), [])


def test_cached_encoder_encodes_each_text_once_across_instances(tmp_path: Path) -> None:
    inner = KeywordEncoder()
    cache = CachedEncoder(inner, tmp_path / "emb.npz")
    first = cache.encode_documents(["docs typo", "crash", "docs typo"])
    assert inner.encoded == 2  # the duplicate is encoded once
    again = CachedEncoder(inner, tmp_path / "emb.npz").encode_documents(["crash", "docs typo"])
    assert inner.encoded == 2  # read back from disk
    np.testing.assert_array_equal(again, first[[1, 0]])


def test_a_long_encode_is_saved_batch_by_batch(tmp_path: Path) -> None:
    class Dies(KeywordEncoder):
        def encode_documents(self, texts: Sequence[str]) -> Matrix:
            if self.encoded >= 2:
                raise KeyboardInterrupt  # killed mid-way
            return super().encode_documents(texts)

    cache = CachedEncoder(Dies(), tmp_path / "emb.npz", batch=2)
    with pytest.raises(KeyboardInterrupt):
        cache.encode_documents(["a", "b", "c", "d"])
    inner = KeywordEncoder()
    CachedEncoder(inner, tmp_path / "emb.npz").encode_documents(["a", "b", "c", "d"])
    assert inner.encoded == 2  # the first batch survived the interruption
