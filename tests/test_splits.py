import random
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from triagelab.data.ground_truth import SilverTruth
from triagelab.data.profile import Minimums, load_profile
from triagelab.data.splits import (
    assign_splits,
    stratified_sample,
    stratum_weights,
    window_of,
)

from .data_fixtures import raw

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE = load_profile(REPO_ROOT / "configs" / "repos" / "python__cpython.yaml")


def truth(number: int, *, dup: bool = False, info: bool = False, comp: bool = False) -> SilverTruth:
    return SilverTruth(
        number=number,
        labels=(),
        human_triaged=False,
        duplicate_of=1 if dup else None,
        duplicate_source="state_reason" if dup else None,
        component="stdlib" if comp else None,
        component_votes={},
        fix_prs=(),
        needs_info=info,
        needs_info_at=None,
    )


def pool_of(n: int, dups: int, infos: int, comps: int) -> list[SilverTruth]:
    return [
        truth(i, dup=i < dups, info=dups <= i < dups + infos, comp=i % 3 == 0 and i < comps * 3)
        for i in range(n)
    ]


def test_windows_are_half_open_and_ordered() -> None:
    w = PROFILE.windows
    assert window_of(w.eval_start - timedelta(days=1), PROFILE) == "train"
    assert window_of(w.eval_start, PROFILE) == "dev"
    assert window_of(w.test_start - timedelta(days=1), PROFILE) == "dev"
    assert window_of(w.test_start, PROFILE) == "test"
    assert window_of(w.eval_end, PROFILE) == "test"
    assert window_of(w.eval_end + timedelta(days=1), PROFILE) == "out"


def test_sample_meets_minimums_and_size() -> None:
    pool = pool_of(800, dups=20, infos=30, comps=200)
    chosen = stratified_sample(
        pool, 100, Minimums(duplicate=12, needs_info=12, component=30), random.Random(0)
    )
    by = {t.number: t for t in pool}
    assert len(chosen) == 100
    assert sum(by[c].duplicate_of is not None for c in chosen) >= 12
    assert sum(by[c].needs_info for c in chosen) >= 12
    assert sum(by[c].component is not None for c in chosen) >= 30


def test_sample_takes_everything_available_when_positives_are_scarce() -> None:
    pool = pool_of(300, dups=4, infos=0, comps=10)
    chosen = stratified_sample(
        pool, 50, Minimums(duplicate=12, needs_info=12, component=30), random.Random(0)
    )
    assert {0, 1, 2, 3} <= set(chosen)  # all 4 duplicates
    assert len(chosen) == 50


def test_sample_is_deterministic_for_a_seed() -> None:
    pool = pool_of(500, dups=15, infos=15, comps=100)
    mins = Minimums(duplicate=12, needs_info=12, component=30)
    assert stratified_sample(pool, 100, mins, random.Random(7)) == stratified_sample(
        pool, 100, mins, random.Random(7)
    )
    assert stratified_sample(pool, 100, mins, random.Random(7)) != stratified_sample(
        pool, 100, mins, random.Random(8)
    )


def test_weights_recover_the_natural_base_rate() -> None:
    # 20 duplicates in 1,000 (2%); oversample them to 12 of 100 (12%).
    pool = pool_of(1000, dups=20, infos=0, comps=0)
    chosen = stratified_sample(
        pool, 100, Minimums(duplicate=12, needs_info=0, component=0), random.Random(1)
    )
    w = stratum_weights(pool, chosen)
    by = {t.number: t for t in pool}
    weighted_rate = sum(w[c] * (by[c].duplicate_of is not None) for c in chosen) / sum(w.values())
    assert sum(by[c].duplicate_of is not None for c in chosen) / 100 == pytest.approx(0.12)
    assert weighted_rate == pytest.approx(0.02)
    assert sum(w.values()) == pytest.approx(1000)  # weights sum to the pool size


def test_assign_splits_by_time_with_exclusions() -> None:
    base = raw()
    w = PROFILE.windows

    def at(d: date) -> datetime:
        return datetime.combine(d, datetime.min.time(), tzinfo=UTC)

    issues = [
        base.model_copy(update={"number": 1, "created_at": at(w.history_start)}),
        base.model_copy(update={"number": 2, "created_at": at(w.eval_start)}),
        base.model_copy(update={"number": 3, "created_at": at(w.test_start)}),
        base.model_copy(update={"number": 4, "created_at": at(w.eval_start)}),
    ]
    truths = {i.number: truth(i.number) for i in issues}
    result = {a.number: a for a in assign_splits(issues, truths, {4: "bot_author"}, PROFILE)}
    assert result[1].split == "train"
    assert result[2].split == "dev"
    assert result[3].split == "test"
    assert result[4].split == "excluded"
    assert result[4].exclusion_reason == "bot_author"
    assert Counter(a.split for a in result.values()) == {
        "train": 1,
        "dev": 1,
        "test": 1,
        "excluded": 1,
    }
