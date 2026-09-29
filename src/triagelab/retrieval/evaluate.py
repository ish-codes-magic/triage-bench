"""Standalone retrieval quality (AGENTS.md §8): can search find a duplicate's original?

Queries are silver duplicates, each searched *as of its own creation* with itself excluded.
Two views are reported:
  - all queries: the original may predate the index (history starts at the profile's
    `index_start`), in which case no retriever can find it. This is what an agent faces;
  - reachable queries: the original is in the index and visible at query time, which
    isolates ranking quality from index coverage.
Retrievers are compared with a paired bootstrap over the same reachable queries (§12.2):
a difference counts only if its interval excludes zero.
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
from triagelab.eval.bootstrap import Statistic, bootstrap_ci, paired_bootstrap
from triagelab.eval.metrics import mean_reciprocal_rank, recall_at_k
from triagelab.retrieval.corpus import NotVisibleError
from triagelab.retrieval.search import HybridSearcher, Mode

KS = (1, 5, 10, 20)
COMPARED: tuple[tuple[str, int], ...] = (("mrr", 0), ("recall", 10))  # (stat, k)
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


class Rankings(BaseModel):
    """One retriever's ranked lists for every query: the raw material for scores and deltas."""

    mode: str
    gold: list[int]
    ranked: list[list[int]]
    reachable: list[bool]

    def reachable_only(self) -> tuple[list[int], list[list[int]]]:
        idx = [i for i, r in enumerate(self.reachable) if r]
        return [self.gold[i] for i in idx], [self.ranked[i] for i in idx]


class Comparison(BaseModel):
    """B - A on the same reachable queries, with a paired-bootstrap interval."""

    a: str
    b: str
    metric: str
    delta: float
    low: float
    high: float
    significant: bool


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


def _statistic(stat: str, k: int, gold: list[int], ranked: list[list[int]]) -> Statistic:
    """Recall@k (stat="recall") or MRR (stat="mrr") over a resample of query indices."""

    def fn(idx: Sequence[int]) -> float:
        g = [gold[i] for i in idx]
        r = [ranked[i] for i in idx]
        return recall_at_k(g, r, k) if stat == "recall" else mean_reciprocal_rank(g, r)

    return fn


def _scored(
    stat: str, k: int, gold: list[int], ranked: list[list[int]], seed: int, resamples: int
) -> Score:
    ci = bootstrap_ci(len(gold), _statistic(stat, k, gold, ranked), resamples=resamples, seed=seed)
    return Score(point=ci.point, low=ci.low, high=ci.high)


def rank(searcher: HybridSearcher, queries: Sequence[RetrievalQuery], *, mode: Mode) -> Rankings:
    """Search each query as of its own creation, excluding itself."""
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
    return Rankings(mode=mode, gold=gold, ranked=ranked, reachable=reachable)


def score(rankings: Rankings, *, resamples: int = 1000, seed: int = 0) -> RetrievalReport:
    gold, ranked = rankings.gold, rankings.ranked
    gold_r, ranked_r = rankings.reachable_only()
    return RetrievalReport(
        mode=rankings.mode,
        queries=len(gold),
        reachable=len(gold_r),
        recall_all={k: _scored("recall", k, gold, ranked, seed, resamples) for k in KS},
        mrr_all=_scored("mrr", 0, gold, ranked, seed, resamples),
        recall_reachable={k: _scored("recall", k, gold_r, ranked_r, seed, resamples) for k in KS},
        mrr_reachable=_scored("mrr", 0, gold_r, ranked_r, seed, resamples),
    )


def compare(a: Rankings, b: Rankings, *, resamples: int = 1000, seed: int = 0) -> list[Comparison]:
    """Paired B - A deltas on reachable queries (unreachable ones score 0 for everyone)."""
    if a.gold != b.gold or a.reachable != b.reachable:
        raise ValueError(f"{a.mode} and {b.mode} were ranked on different queries")
    gold, ranked_a = a.reachable_only()
    _, ranked_b = b.reachable_only()
    out: list[Comparison] = []
    for stat, k in COMPARED:
        d = paired_bootstrap(
            len(gold),
            _statistic(stat, k, gold, ranked_a),
            _statistic(stat, k, gold, ranked_b),
            resamples=resamples,
            seed=seed,
        )
        out.append(
            Comparison(
                a=a.mode,
                b=b.mode,
                metric="MRR" if stat == "mrr" else f"Recall@{k}",
                delta=d.delta,
                low=d.low,
                high=d.high,
                significant=d.significant,
            )
        )
    return out


def compare_all(
    rankings: Sequence[Rankings], *, resamples: int = 1000, seed: int = 0
) -> list[Comparison]:
    """Every later retriever against every earlier one (bm25, then dense, then hybrid)."""
    return [
        c
        for i, a in enumerate(rankings)
        for b in rankings[i + 1 :]
        for c in compare(a, b, resamples=resamples, seed=seed)
    ]


def render(
    reports: Sequence[RetrievalReport],
    repo: str,
    *,
    comparisons: Sequence[Comparison] = (),
    notes: Sequence[str] = (),
) -> str:
    def cell(s: Score) -> str:
        return f"{s.point:.2f} [{s.low:.2f}, {s.high:.2f}]"

    def delta(c: Comparison) -> str:
        text = f"{c.delta:+.3f} [{c.low:+.3f}, {c.high:+.3f}]"
        return f"**{text}**" if c.significant else text

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
        *(["", *notes] if notes else []),
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
    if comparisons:
        metrics = list(dict.fromkeys(c.metric for c in comparisons))
        pairs = list(dict.fromkeys((c.b, c.a) for c in comparisons))
        by_key = {(c.b, c.a, c.metric): c for c in comparisons}
        lines += [
            "",
            "## Paired differences (reachable queries)",
            "",
            "B - A on the same queries, paired bootstrap. **Bold**: the interval excludes 0.",
            "",
            "| B - A | " + " | ".join(metrics) + " |",
            "|---|" + "---|" * len(metrics),
            *[
                f"| {b} - {a} | " + " | ".join(delta(by_key[(b, a, m)]) for m in metrics) + " |"
                for b, a in pairs
            ],
        ]
    return "\n".join(lines) + "\n"
