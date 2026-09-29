"""Precomputed document embeddings, stored by issue number in resumable chunks.

Embedding ~13k issues on a laptop CPU takes about half an hour, long enough that an
interruption is likely. Vectors are written in chunks keyed by issue number, so:
  - a stopped build resumes with only the missing issues;
  - adding older history later doesn't invalidate vectors already computed;
  - the matrix is re-assembled in whatever order the corpus has at load time.
"""

from collections.abc import Callable
from pathlib import Path

import numpy as np

from triagelab.retrieval.corpus import Corpus
from triagelab.retrieval.dense import Encoder, Matrix
from triagelab.retrieval.search import document_text


def store_dir(index_dir: Path, encoder_name: str) -> Path:
    return index_dir / f"emb-{encoder_name.replace('/', '__')}"


def _chunks(directory: Path) -> list[Path]:
    return sorted(directory.glob("chunk-*.npz")) if directory.is_dir() else []


def embedded_numbers(directory: Path) -> set[int]:
    numbers: set[int] = set()
    for chunk in _chunks(directory):
        with np.load(chunk) as data:
            numbers.update(int(n) for n in data["numbers"])
    return numbers


def embed_corpus(
    corpus: Corpus,
    encoder: Encoder,
    directory: Path,
    *,
    chunk_size: int = 256,
    log: Callable[[str], None] = lambda _: None,
) -> int:
    """Embed every corpus document not yet stored; returns how many were added."""
    directory.mkdir(parents=True, exist_ok=True)
    done = embedded_numbers(directory)
    todo = [i for i in corpus.issues if i.number not in done]
    next_id = len(_chunks(directory))
    for start in range(0, len(todo), chunk_size):
        batch = todo[start : start + chunk_size]
        vectors = encoder.encode_documents([document_text(i) for i in batch])
        # Write-then-rename: a job killed mid-write leaves a stray .tmp (ignored by
        # _chunks), never a truncated chunk that would break every later load.
        final = directory / f"chunk-{next_id:05d}.npz"
        tmp = final.with_suffix(".npz.tmp")
        with tmp.open("wb") as fh:
            np.savez(
                fh,
                numbers=np.array([i.number for i in batch], dtype=np.int64),
                vectors=vectors.astype(np.float32),
            )
        tmp.replace(final)
        next_id += 1
        log(f"  embedded {min(start + chunk_size, len(todo))}/{len(todo)}")
    return len(todo)


def load_matrix(corpus: Corpus, directory: Path) -> Matrix:
    """Vectors in corpus order; fails loudly if any document has no vector."""
    by_number: dict[int, np.ndarray] = {}
    for chunk in _chunks(directory):
        with np.load(chunk) as data:
            for number, vector in zip(data["numbers"], data["vectors"], strict=True):
                by_number[int(number)] = vector
    missing = [i.number for i in corpus.issues if i.number not in by_number]
    if missing:
        raise ValueError(
            f"{len(missing)} documents have no embedding (e.g. {missing[:5]}); run the build"
        )
    return np.stack([by_number[i.number] for i in corpus.issues]).astype(np.float32)
