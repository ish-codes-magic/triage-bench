"""Build and load the retrieval index for a repo (corpus + optional dense vectors)."""

import json
from collections.abc import Iterator
from pathlib import Path

from triagelab.data.build import exclusion_reason
from triagelab.data.collect import index_history_path, raw_paths
from triagelab.data.models import RawIssue
from triagelab.data.profile import RepoProfile
from triagelab.retrieval.corpus import Corpus, IndexedIssue, to_indexed
from triagelab.retrieval.dense import DenseIndex, Encoder
from triagelab.retrieval.embeddings import load_matrix, store_dir
from triagelab.retrieval.search import HybridSearcher


def index_dir(data_dir: Path, profile: RepoProfile) -> Path:
    return data_dir / "index" / profile.slug


def corpus_path(data_dir: Path, profile: RepoProfile) -> Path:
    return index_dir(data_dir, profile) / "corpus.jsonl"


def _stream_raw(path: Path) -> Iterator[RawIssue]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield RawIssue.model_validate_json(line)


def build_corpus_from_raw(data_dir: Path, profile: RepoProfile) -> Corpus:
    """Dataset issues plus retrieval-only history, streamed so only compact entries are held.

    If an issue appears in both files (it shouldn't), the dataset copy wins.
    """
    issues_path, _ = raw_paths(data_dir, profile)
    entries: dict[int, IndexedIssue] = {}
    for path in (index_history_path(data_dir, profile), issues_path):
        for issue in _stream_raw(path):
            reason = exclusion_reason(issue)
            if reason is None or reason == "bot_author":
                entries[issue.number] = to_indexed(issue)
    return Corpus(entries.values())


def load_searcher(
    data_dir: Path, profile: RepoProfile, *, encoder: Encoder | None = None
) -> HybridSearcher:
    """BM25 always; dense too when an encoder is given and its vectors are built."""
    corpus = Corpus.load(corpus_path(data_dir, profile))
    if encoder is None:
        return HybridSearcher(corpus)
    matrix = load_matrix(corpus, store_dir(index_dir(data_dir, profile), encoder.name))
    return HybridSearcher(corpus, dense=DenseIndex(matrix), encoder=encoder)


def write_meta(data_dir: Path, profile: RepoProfile, meta: dict[str, object]) -> None:
    path = index_dir(data_dir, profile) / "index.json"
    path.write_text(json.dumps(meta, indent=2, default=str) + "\n", encoding="utf-8")
