"""Standalone retrieval quality (AGENTS.md §8): can search find a duplicate's original?

Queries are silver duplicates, each searched *as of its own creation* with itself excluded.
Two views are reported:
  - all queries: the original may predate the index (collected history starts 2025-05-19),
    in which case no retriever can find it. This is what an agent would face;
  - reachable queries: the original is in the index and visible at query time, which
    isolates ranking quality from index coverage.
Test-window duplicates are excluded here: retrieval choices made in M3 must not see them.
"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from triagelab.baselines.text import issue_text
from triagelab.data.build import dataset_paths
from triagelab.data.models import IssueSnapshot
from triagelab.data.profile import RepoProfile
from triagelab.data.storage import read_parquet
from triagelab.eval.bootstrap import bootstrap_ci
from triagelab.eval.metrics import mean_reciprocal_rank, recall_at_k
from triagelab.retrieval.corpus import NotVisibleError
from triagelab.retrieval.search import HybridSearcher, Mode

KS = (1, 5, 10, 20)
ALLOWED_SPLITS = frozenset({"train", "dev", "dev_reserve"})


class RetrievalQuery(BaseModel):
    number: int
    split: str
    created_at: datetime
    text: str
    original: int


class Score(BaseModel):
    point: float
    low: float
    high: float


class RetrievalReport(BaseModel):
    mode: str
    queries: int
    reachable: int
    recall_all: dict[int, Score]
    mrr_all: Score
    recall_reachable: dict[int, Score]
    mrr_reachable: Score


def duplicate_queries(data_dir: Path, profile: RepoProfile) -> list[RetrievalQuery]:
    paths = dataset_paths(data_dir, Path(), profile)
    split_of = {r["number"]: r["split"] for r in read_parquet(paths.splits)}
    originals = {
        r["number"]: r["duplicate_of"]
        for r in read_parquet(paths.silver)
        if r["duplicate_of"] is not None and split_of.get(r["number"]) in ALLOWED_SPLITS
    }
    queries: list[RetrievalQuery] = []
    for row in read_parquet(paths.snapshots):
        if row["number"] in originals:
            snap = IssueSnapshot.model_validate(row)
            queries.append(
                RetrievalQuery(
                    number=snap.number,
                    split=split_of[snap.number],
                    created_at=snap.created_at,
                    text=issue_text(snap),
                    original=originals[snap.number],
                )
            )
    return sorted(queries, key=lambda q: q.number)


def _scored(
    stat: str, k: int, gold: list[int], ranked: list[list[int]], seed: int, resamples: int
) -> Score:
    """Bootstrap interval for Recall@k (stat="recall") or MRR (stat="mrr") over queries."""

    def fn(idx: Sequence[int]) -> float:
        g = [gold[i] for i in idx]
        r = [ranked[i] for i in idx]
        return recall_at_k(g, r, k) if stat == "recall" else mean_reciprocal_rank(g, r)

    ci = bootstrap_ci(len(gold), fn, resamples=resamples, seed=seed)
    return Score(point=ci.point, low=ci.low, high=ci.high)


def evaluate(
    searcher: HybridSearcher,
    queries: Sequence[RetrievalQuery],
    *,
    mode: Mode,
    resamples: int = 1000,
    seed: int = 0,
) -> RetrievalReport:
    gold: list[int] = []
    ranked: list[list[int]] = []
    reachable: list[bool] = []
    for q in queries:
        hits = searcher.search(q.text, as_of=q.created_at, k=max(KS), exclude={q.number}, mode=mode)
        gold.append(q.original)
        ranked.append([h.number for h in hits])
        try:
            searcher.corpus.get(q.original, q.created_at)
            reachable.append(True)
        except NotVisibleError:
            reachable.append(False)

    reach_idx = [i for i, r in enumerate(reachable) if r]
    gold_r = [gold[i] for i in reach_idx]
    ranked_r = [ranked[i] for i in reach_idx]
    return RetrievalReport(
        mode=mode,
        queries=len(queries),
        reachable=len(reach_idx),
        recall_all={k: _scored("recall", k, gold, ranked, seed, resamples) for k in KS},
        mrr_all=_scored("mrr", 0, gold, ranked, seed, resamples),
        recall_reachable={k: _scored("recall", k, gold_r, ranked_r, seed, resamples) for k in KS},
        mrr_reachable=_scored("mrr", 0, gold_r, ranked_r, seed, resamples),
    )


def render(reports: Sequence[RetrievalReport], repo: str) -> str:
    def cell(s: Score) -> str:
        return f"{s.point:.2f} [{s.low:.2f}, {s.high:.2f}]"

    first = reports[0]
    lines = [
        f"# Duplicate retrieval: {repo}",
        "",
        f"Queries: {first.queries} silver duplicates from the train and dev windows (test window "
        f"excluded), each searched as of its own creation. Reachable: {first.reachable} "
        f"({first.reachable / max(first.queries, 1):.0%}) have their original inside the "
        "indexed history at query time; the rest predate the collected window and cannot "
        "be found by any retriever. 95% bootstrap intervals. Generated by "
        "`triagelab retrieval eval`.",
        "",
        "## Reachable queries (ranking quality)",
        "",
        "| retriever | Recall@1 | Recall@5 | Recall@10 | Recall@20 | MRR |",
        "|---|---|---|---|---|---|",
        *[
            f"| {r.mode} | "
            + " | ".join(cell(r.recall_reachable[k]) for k in KS)
            + f" | {cell(r.mrr_reachable)} |"
            for r in reports
        ],
        "",
        "## All queries (what an agent faces)",
        "",
        "| retriever | Recall@1 | Recall@5 | Recall@10 | Recall@20 | MRR |",
        "|---|---|---|---|---|---|",
        *[
            f"| {r.mode} | "
            + " | ".join(cell(r.recall_all[k]) for k in KS)
            + f" | {cell(r.mrr_all)} |"
            for r in reports
        ],
    ]
    return "\n".join(lines) + "\n"
