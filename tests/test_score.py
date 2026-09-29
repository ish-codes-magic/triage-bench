from datetime import UTC, datetime

import pytest

from triagelab.data.models import IssueSnapshot
from triagelab.eval.dataset import EvalExample, Gold
from triagelab.eval.score import METRICS, score
from triagelab.triage import TriageResult


def example(
    n: int,
    *,
    labels: dict[str, str],
    triaged: bool = True,
    dup: int | None = None,
    comp: str | None = None,
    info: bool = False,
    weight: float = 1.0,
) -> EvalExample:
    return EvalExample(
        snapshot=IssueSnapshot(
            issue_ref=f"o/r#{n}",
            repo="o/r",
            number=n,
            title="t",
            body="b",
            author_association="NONE",
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        ),
        gold=Gold(
            labels=frozenset(labels),
            label_groups=labels,
            human_triaged=triaged,
            duplicate_of=dup,
            component=comp,
            needs_info=info,
        ),
        split="dev",
        weight=weight,
    )


EXAMPLES = [
    example(1, labels={"type-bug": "type", "stdlib": "area"}, comp="stdlib", dup=None),
    example(2, labels={"type-feature": "type"}, comp=None, info=True),
    example(3, labels={}, triaged=False, dup=1, comp="docs"),
    example(4, labels={"type-bug": "type", "docs": "area"}, comp="docs"),
]


def perfect(e: EvalExample) -> TriageResult:
    g = e.gold
    return TriageResult(
        issue_ref=e.snapshot.issue_ref,
        labels=sorted(g.labels),
        component=g.component,
        duplicate_of=g.duplicate_of,
        needs_info=g.needs_info,
    )


def test_perfect_predictions_score_one_everywhere() -> None:
    card = score(EXAMPLES, [perfect(e) for e in EXAMPLES], resamples=100)
    for name in ("t1_micro_f1", "t1_macro_f1", "t2_link_f1", "t3_accuracy", "t4_f1"):
        assert card.metrics[name].point == pytest.approx(1.0), name


def test_t1_ignores_untriaged_issues() -> None:
    preds = [perfect(e) for e in EXAMPLES]
    preds[2] = preds[2].model_copy(
        update={"labels": ["type-bug", "wild-guess"]}
    )  # issue 3 is untriaged
    assert score(EXAMPLES, preds, resamples=50).metrics["t1_micro_f1"].point == pytest.approx(1.0)


def test_t3_scored_only_where_a_gold_component_exists() -> None:
    preds = [perfect(e) for e in EXAMPLES]
    preds[1] = preds[1].model_copy(update={"component": "build"})  # issue 2 has no gold component
    assert score(EXAMPLES, preds, resamples=50).metrics["t3_accuracy"].point == pytest.approx(1.0)
    preds[0] = preds[0].model_copy(update={"component": "docs"})  # now 2 of 3 right
    assert score(EXAMPLES, preds, resamples=50).metrics["t3_accuracy"].point == pytest.approx(2 / 3)


def test_top3_uses_ranked_candidates() -> None:
    preds = [
        perfect(e).model_copy(
            update={"component": "x", "component_candidates": ["x", "y", e.gold.component or "z"]}
        )
        for e in EXAMPLES
    ]
    card = score(EXAMPLES, preds, resamples=50)
    assert card.metrics["t3_accuracy"].point == 0.0
    assert card.metrics["t3_top3_accuracy"].point == pytest.approx(1.0)


def test_metrics_without_positives_are_undefined_not_zero() -> None:
    no_dups = [
        e.model_copy(update={"gold": e.gold.model_copy(update={"duplicate_of": None})})
        for e in EXAMPLES
    ]
    card = score(no_dups, [perfect(e) for e in no_dups], resamples=50)
    assert card.metrics["t2_link_f1"].point is None


def test_every_example_needs_a_prediction() -> None:
    with pytest.raises(ValueError, match="no prediction"):
        score(EXAMPLES, [perfect(e) for e in EXAMPLES[:2]], resamples=10)


def test_system_stats() -> None:
    preds = [
        perfect(e).model_copy(update={"cost_usd": 0.01, "latency_ms": 100 * (i + 1)})
        for i, e in enumerate(EXAMPLES)
    ]
    preds[0] = preds[0].model_copy(update={"error": "invalid JSON"})
    s = score(EXAMPLES, preds, resamples=10).system
    assert s.issues == 4
    assert s.errors == 1
    assert s.cost_usd_total == pytest.approx(0.04)
    assert s.latency_ms_p50 == pytest.approx(250.0)


def test_metric_registry_is_the_reported_set() -> None:
    assert list(METRICS)[:2] == ["t1_micro_f1", "t1_macro_f1"]
