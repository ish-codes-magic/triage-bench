"""Time-based splits with stratified dev/test sampling (AGENTS.md §7.4).

- Time decides membership: train < eval_start <= dev < test_start <= test <= eval_end.
  Later issues never inform earlier ones, mirroring how triage happens in reality.
- Within the dev and test windows, a small sample is drawn so every task has enough
  positives: duplicates are ~3% of issues, so a uniform sample of 50 would contain one.
- Each sampled issue gets a post-stratification weight N_h / n_h (pool size over sample
  size in its stratum). Selection is uniform *within* each stratum, so weighted metrics
  estimate what the natural (unstratified) population would score.
"""

import random
from collections import Counter
from collections.abc import Sequence
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from triagelab.data.ground_truth import SilverTruth
from triagelab.data.models import RawIssue
from triagelab.data.profile import Minimums, RepoProfile

Split = Literal["train", "dev", "test", "dev_reserve", "test_reserve", "excluded"]
Flag = Literal["duplicate", "needs_info", "component"]
FLAGS: tuple[Flag, ...] = ("duplicate", "needs_info", "component")


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    number: int
    split: Split
    stratum: str
    weight: float | None  # set for dev/test samples only
    exclusion_reason: str | None = None


def flags_of(truth: SilverTruth) -> dict[Flag, bool]:
    return {
        "duplicate": truth.duplicate_of is not None,
        "needs_info": truth.needs_info,
        "component": truth.component is not None,
    }


def stratum_of(truth: SilverTruth) -> str:
    f = flags_of(truth)
    return "|".join(f"{name}={int(f[name])}" for name in FLAGS)


def window_of(created: date, profile: RepoProfile) -> Literal["train", "dev", "test", "out"]:
    w = profile.windows
    if w.history_start <= created < w.eval_start:
        return "train"
    if w.eval_start <= created < w.test_start:
        return "dev"
    if w.test_start <= created <= w.eval_end:
        return "test"
    return "out"


def stratified_sample(
    pool: Sequence[SilverTruth], n: int, minimums: Minimums, rng: random.Random
) -> list[int]:
    """Pick `n` issue numbers: first satisfy each flag's minimum, then fill uniformly.

    Candidates are sorted before shuffling, so the result depends only on the seed.
    """
    chosen: set[int] = set()
    by_number = {t.number: t for t in pool}
    for flag in FLAGS:
        have = sum(flags_of(by_number[c])[flag] for c in chosen)
        need = min(getattr(minimums, flag) - have, n - len(chosen))
        if need <= 0:
            continue
        candidates = sorted(t.number for t in pool if flags_of(t)[flag] and t.number not in chosen)
        rng.shuffle(candidates)
        chosen.update(candidates[:need])
    rest = sorted(t.number for t in pool if t.number not in chosen)
    rng.shuffle(rest)
    chosen.update(rest[: max(0, n - len(chosen))])
    return sorted(chosen)


def stratum_weights(pool: Sequence[SilverTruth], chosen: Sequence[int]) -> dict[int, float]:
    """N_h / n_h for each chosen issue's stratum."""
    pool_sizes = Counter(stratum_of(t) for t in pool)
    picked = {t.number: stratum_of(t) for t in pool if t.number in set(chosen)}
    sample_sizes = Counter(picked.values())
    return {num: pool_sizes[s] / sample_sizes[s] for num, s in picked.items()}


def assign_splits(
    issues: Sequence[RawIssue],
    truths: dict[int, SilverTruth],
    exclusions: dict[int, str],
    profile: RepoProfile,
) -> list[Assignment]:
    """Assign every collected issue to exactly one split.

    `exclusions` maps issue numbers to why they can't be evaluated (e.g. a creation-time
    body that can't be reconstructed, or a bot author); those never enter any split.
    """
    rng = random.Random(profile.splits.seed)
    out: list[Assignment] = []
    pools: dict[str, list[SilverTruth]] = {"dev": [], "test": []}
    for issue in sorted(issues, key=lambda i: i.number):
        truth = truths[issue.number]
        if issue.number in exclusions:
            out.append(
                Assignment(
                    number=issue.number,
                    split="excluded",
                    stratum=stratum_of(truth),
                    weight=None,
                    exclusion_reason=exclusions[issue.number],
                )
            )
            continue
        window = window_of(issue.created_at.date(), profile)
        if window == "train":
            out.append(
                Assignment(
                    number=issue.number, split="train", stratum=stratum_of(truth), weight=None
                )
            )
        elif window in pools:
            pools[window].append(truth)

    spec = profile.splits
    plans: tuple[tuple[Split, Split, int, Minimums], ...] = (
        ("dev", "dev_reserve", spec.dev_size, spec.dev_min_positives),
        ("test", "test_reserve", spec.test_size, spec.test_min_positives),
    )
    for name, reserve, size, minimums in plans:
        pool = pools[name]
        chosen = stratified_sample(pool, size, minimums, rng)
        weights = stratum_weights(pool, chosen)
        for truth in pool:
            sampled = truth.number in weights
            out.append(
                Assignment(
                    number=truth.number,
                    split=name if sampled else reserve,
                    stratum=stratum_of(truth),
                    weight=weights.get(truth.number),
                )
            )
    return sorted(out, key=lambda a: a.number)
