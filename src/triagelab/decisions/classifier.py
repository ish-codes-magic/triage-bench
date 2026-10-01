"""An embedding classifier as a decision backend: the cheap, strong baseline (AGENTS.md §11).

Each question gets its own logistic-regression head over arctic-embed-s vectors of the
issue text, trained on the silver train split. The confidence is the predicted
probability of the chosen option, renormalised over the options the question offers.
It costs nothing per call and needs no network, so it's the floor every LLM backend
has to beat on accuracy *and* calibration.
"""
# scikit-learn ships no type stubs; the untyped model stays inside `Head`.
# pyright: reportMissingTypeStubs=false

import hashlib
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression

from triagelab.decisions.base import Decision, DecisionError
from triagelab.retrieval.dense import Encoder, Matrix


@dataclass(frozen=True)
class Head:
    """One question's classifier: its classes and a fitted model."""

    classes: tuple[str, ...]
    model: Any  # sklearn LogisticRegression

    def probabilities(self, vectors: Matrix) -> list[dict[str, float]]:
        rows: Any = self.model.predict_proba(vectors)
        return [
            {c: float(p) for c, p in zip(self.classes, row, strict=True)}
            for row in np.asarray(rows, dtype=np.float64)
        ]


def fit_head(vectors: Matrix, answers: Sequence[str], *, c: float = 1.0) -> Head:
    if len(set(answers)) < 2:
        raise DecisionError("a head needs at least two distinct answers to learn from")
    model: Any = LogisticRegression(C=c, max_iter=2000)
    model.fit(vectors, list(answers))
    return Head(classes=tuple(str(k) for k in model.classes_), model=model)


class CachedEncoder:
    """Document embeddings keyed by a hash of the text, persisted between runs.

    Training re-encodes ~4k issues otherwise (about 10 minutes on CPU).
    """

    def __init__(self, encoder: Encoder, path: Path) -> None:
        self._encoder = encoder
        self._path = path
        self._vectors: dict[str, np.ndarray] = {}
        if path.is_file():
            with np.load(path) as data:
                keys, vectors = data["keys"], data["vectors"]
                self._vectors = {str(k): v for k, v in zip(keys, vectors, strict=True)}

    @property
    def name(self) -> str:
        return self._encoder.name

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def encode_documents(self, texts: Sequence[str]) -> Matrix:
        keys = [self._key(t) for t in texts]
        missing = sorted(
            {k: t for k, t in zip(keys, texts, strict=True) if k not in self._vectors}.items()
        )
        if missing:
            fresh = self._encoder.encode_documents([t for _, t in missing])
            self._vectors.update({k: v for (k, _), v in zip(missing, fresh, strict=True)})
            self._save()
        return np.stack([self._vectors[k] for k in keys]).astype(np.float32)

    def encode_queries(self, texts: Sequence[str]) -> Matrix:
        return self._encoder.encode_queries(texts)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp.npz")
        keys = sorted(self._vectors)
        np.savez(tmp, keys=np.array(keys), vectors=np.stack([self._vectors[k] for k in keys]))
        tmp.replace(self._path)


class ClassifierBackend:
    def __init__(self, encoder: Encoder, heads: Mapping[str, Head]) -> None:
        self._encoder = encoder
        self._heads = dict(heads)

    @property
    def name(self) -> str:
        return "classifier"

    def choose(self, state: str, question: str, options: Sequence[str]) -> Decision:
        head = self._heads.get(question)
        if head is None:
            raise DecisionError(f"no trained head for {question!r}")
        started = time.perf_counter()
        probs = head.probabilities(self._encoder.encode_documents([state]))[0]
        dist = {o: probs[o] for o in options if o in probs}
        total = sum(dist.values())
        latency_ms = round((time.perf_counter() - started) * 1000)
        if total <= 0:
            return Decision(answer="", confidence=0.0, backend=self.name, latency_ms=latency_ms)
        dist = {o: p / total for o, p in dist.items()}
        best = max(dist, key=lambda o: dist[o])
        return Decision(
            answer=best,
            confidence=dist[best],
            backend=self.name,
            latency_ms=latency_ms,
            distribution=dist,
        )

    def yes_no(self, state: str, question: str) -> Decision:
        d = self.choose(state, question, ["yes", "no"])
        return d.model_copy(update={"answer": d.answer == "yes"}) if d.answer else d

    def score(self, state: str, question: str, lo: float, hi: float) -> Decision:
        raise DecisionError("the classifier backend answers categorical questions only")
