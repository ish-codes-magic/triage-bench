"""Gold labels in evaluation: conversion, overlay, human baseline and per-task agreement."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from triagelab.data.profile import load_profile
from triagelab.eval.dataset import Gold, load_split
from triagelab.eval.gold_labels import (
    agreement_by_task,
    gold_from,
    human_predictions,
    with_gold,
)
from triagelab.eval.score import score
from triagelab.labeling.gold import Decision, GoldRecord

from .smoke_dataset import PROFILE_PATH, write_smoke_dataset

PROFILE = load_profile(PROFILE_PATH)


def gold(labels: set[str], component: str | None, needs_info: bool, dup: int | None) -> Gold:
    return gold_from(
        Decision(
            labels=sorted(labels), component=component, needs_info=needs_info, duplicate_of=dup
        ),
        PROFILE,
    )


def test_gold_from_a_decision_uses_the_taxonomy_groups() -> None:
    g = gold({"type-bug", "stdlib", "topic-asyncio"}, "stdlib", False, None)
    assert g.label_groups == {"type-bug": "type", "stdlib": "area", "topic-asyncio": "family"}
    assert g.human_triaged


def test_agreement_by_task_by_hand() -> None:
    silver = [
        gold({"type-bug", "stdlib"}, "stdlib", False, None),
        gold({"type-feature", "docs"}, "docs", True, 5),
    ]
    human = [
        gold({"type-bug", "stdlib"}, "stdlib", False, None),
        gold({"type-feature", "docs"}, "docs", False, 5),  # disagrees on needs-info only
    ]
    vocabulary = ["type-bug", "type-feature", "stdlib", "docs"]
    pairs = list(zip(silver, human, strict=True))
    rows = {r.task: r for r in agreement_by_task(pairs, vocabulary)}
    assert rows["T1 type label"].kappa == pytest.approx(1.0)
    assert rows["T3 component"].kappa == pytest.approx(1.0)
    assert rows["T2 is a duplicate"].kappa == pytest.approx(1.0)
    # needs-info: p_o = 1/2; silver says yes 1/2, human never: p_e = 1/2, so kappa = 0.
    assert rows["T4 needs info"].kappa == pytest.approx(0.0)
    assert rows["T4 needs info"].exact == pytest.approx(0.5)


def record(ref: str, blind: Decision, final: Decision | None, unusable: bool = False) -> GoldRecord:
    return GoldRecord(
        issue_ref=ref, number=int(ref.rsplit("#", 1)[1]), split="dev", blind=blind, final=final,
        unusable=unusable, annotator="t", blind_seconds=30.0,
        updated_at=datetime(2026, 9, 30, tzinfo=UTC),
    )  # fmt: skip


def test_gold_overlay_and_human_baseline_score_like_any_system(tmp_path: Path) -> None:
    write_smoke_dataset(tmp_path)
    dev = load_split(tmp_path / "data", PROFILE, "dev")
    a, b, c = dev[0], dev[1], dev[2]
    blind = Decision(labels=["type-bug"], component="stdlib")
    final = Decision(labels=["type-bug", "stdlib"], component="stdlib")
    records = {
        a.snapshot.issue_ref: record(a.snapshot.issue_ref, blind, final),
        b.snapshot.issue_ref: record(b.snapshot.issue_ref, blind, None),  # not adjudicated
        c.snapshot.issue_ref: record(c.snapshot.issue_ref, blind, final, unusable=True),
    }
    examples = with_gold(dev, records, PROFILE)
    assert [e.snapshot.issue_ref for e in examples] == [a.snapshot.issue_ref]
    assert examples[0].gold.labels == {"type-bug", "stdlib"}
    human = human_predictions(records)
    assert [p.issue_ref for p in human] == [a.snapshot.issue_ref]
    card = score(examples, human, resamples=100)
    assert card.metrics["t3_accuracy"].point == pytest.approx(1.0)
    assert card.metrics["t1_type_micro_f1"].point == pytest.approx(1.0)
