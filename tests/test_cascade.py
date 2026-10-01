"""The cascade on hand-built tiers: signals, curve points, τ choice, cross-fitting."""

from datetime import UTC, datetime

import pytest

from triagelab.data.models import IssueSnapshot
from triagelab.decisions.cascade import Cascade, agreement_signal, self_signal
from triagelab.eval.dataset import EvalExample, Gold
from triagelab.hashing import stable_hash
from triagelab.triage import TriageResult

TYPES = ["type-bug", "type-crash"]
REFS = [f"o/r#{n}" for n in range(1, 5)]


def example(ref: str) -> EvalExample:
    n = int(ref.split("#")[1])
    snap = IssueSnapshot(
        issue_ref=ref, repo="o/r", number=n, title="t", body="b",
        author_association="NONE", created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )  # fmt: skip
    gold = Gold(
        labels=frozenset({"type-bug"}), label_groups={"type-bug": "type"}, human_triaged=True,
        duplicate_of=None, component="c1", needs_info=False,
    )  # fmt: skip
    return EvalExample(snapshot=snap, gold=gold, split="dev", weight=1.0)


def pred(ref: str, component: str, conf: float, cost: float) -> TriageResult:
    return TriageResult(
        issue_ref=ref,
        labels=["type-bug"],
        label_confidence={"type-bug": 1.0},
        component=component,
        component_confidence=conf,
        cost_usd=cost,
    )


EXAMPLES = [example(r) for r in REFS]
# The cheap tier is right on #1 and #2, wrong on #3 (unsure) and #4 (confidently wrong).
CHEAP = {
    r: pred(r, c, conf, 0.001)
    for r, c, conf in zip(REFS, ["c1", "c1", "c2", "c2"], [0.9, 0.8, 0.3, 0.7], strict=True)
}
FULL = {r: pred(r, "c1", 0.9, 0.01) for r in REFS}  # always right, ten times the price


def cascade(signal: dict[str, float] | None = None) -> Cascade:
    sig = signal or {r: self_signal(CHEAP[r], TYPES) for r in REFS}
    return Cascade(EXAMPLES, CHEAP, FULL, sig, {}, ["t3_accuracy"])


def test_signals() -> None:
    assert [self_signal(CHEAP[r], TYPES) for r in REFS] == [0.9, 0.8, 0.3, 0.7]
    gate = pred("o/r#1", "c1", 0.6, 0.0)
    assert agreement_signal(CHEAP["o/r#1"], gate, TYPES) == 0.6  # agrees: the gate's conf.
    assert agreement_signal(CHEAP["o/r#3"], gate, TYPES) == 0.0  # disagrees: escalate
    failed = CHEAP["o/r#1"].model_copy(update={"error": "no_answer"})
    assert self_signal(failed, TYPES) == 0.0


@pytest.mark.parametrize(
    ("tau", "escalated", "accuracy", "cost"),
    [
        (0.0, 0.0, 0.5, 1.0),  # cheap only: 4 x $0.001
        (0.7, 0.25, 0.75, 3.5),  # #3 escalated: + $0.01
        (0.8, 0.5, 1.0, 6.0),  # #3 and #4 escalated
        (1.01, 1.0, 1.0, 11.0),  # everything escalated; the cheap tier was still paid
    ],
)
def test_curve_points(tau: float, escalated: float, accuracy: float, cost: float) -> None:
    p = cascade().point(tau)
    assert p.escalated == escalated
    assert p.metrics["t3_accuracy"] == accuracy
    assert p.cost_per_1000 == pytest.approx(cost)


def test_tau_is_the_cheapest_that_matches_the_full_agent() -> None:
    c = cascade()
    assert c.thresholds() == [0.0, 0.3, 0.7, 0.8, 0.9, 1.01]
    assert c.choose_tau(EXAMPLES) == 0.8
    assert c.choose_tau(EXAMPLES, tolerance=0.3) == 0.7  # 0.75 is within 0.3 of 1.0


def test_cross_fitting_routes_each_issue_by_the_other_folds_tau() -> None:
    c = cascade()
    taus, pooled = c.cross_fitted()
    fold = {r: int(stable_hash(r), 16) % 2 for r in REFS}
    tau_for = {r: taus[fold[r]] for r in REFS}
    sig = {r: self_signal(CHEAP[r], TYPES) for r in REFS}
    routed = [CHEAP[r] if sig[r] >= tau_for[r] else FULL[r] for r in REFS]
    expected = sum(p.component == "c1" for p in routed) / 4
    assert pooled.metrics["t3_accuracy"] == expected
    assert pooled.escalated == sum(sig[r] < tau_for[r] for r in REFS) / 4


def test_unknown_metrics_are_refused() -> None:
    with pytest.raises(ValueError, match="unknown metrics"):
        Cascade(EXAMPLES, CHEAP, FULL, {}, {}, ["t9_vibes"])
