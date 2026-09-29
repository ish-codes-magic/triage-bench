"""Dense retrieval: cosine similarity over precomputed, L2-normalised embeddings.

Model-agnostic: anything implementing `Encoder` plugs in. The matrix rows are in corpus
order (oldest first), so "visible as of t" is simply the first `visible` rows, and no
future document can influence a query's result (dense scores are per-document, with no
collection statistics).
"""

from collections.abc import Sequence, Set
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

Matrix = NDArray[np.float32]


class Encoder(Protocol):
    """Turns text into L2-normalised vectors (one row per text)."""

    @property
    def name(self) -> str: ...

    def encode_documents(self, texts: Sequence[str]) -> Matrix: ...

    def encode_queries(self, texts: Sequence[str]) -> Matrix: ...


def l2_normalise(matrix: Matrix) -> Matrix:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return (matrix / np.maximum(norms, 1e-12)).astype(np.float32)


class DenseIndex:
    def __init__(self, matrix: Matrix) -> None:
        self._matrix = l2_normalise(matrix)

    def __len__(self) -> int:
        return int(self._matrix.shape[0])

    @property
    def dim(self) -> int:
        return int(self._matrix.shape[1])

    def top(
        self, query: Matrix, visible: int, k: int, exclude: Set[int] = frozenset()
    ) -> list[tuple[int, float]]:
        """Top-k (row index, cosine) among the first `visible` rows."""
        n = min(visible, len(self))
        if n == 0:
            return []
        q = l2_normalise(query.reshape(1, -1))[0]
        sims = self._matrix[:n] @ q
        order = np.argsort(-sims, kind="stable")
        out: list[tuple[int, float]] = []
        for idx in order:
            i = int(idx)
            if i in exclude:
                continue
            out.append((i, float(sims[i])))
            if len(out) == k:
                break
        return out

    def save(self, path: str) -> None:
        np.save(path, self._matrix)

    @classmethod
    def load(cls, path: str) -> "DenseIndex":
        return cls(np.load(path).astype(np.float32))
