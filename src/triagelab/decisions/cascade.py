"""The cascade (AGENTS.md §11, E7): a cheap system answers every issue; uncertain issues go
to the full agent.

Offline and exact: every tier's answers are stored predictions, so a cascade at any
threshold τ is a recombination of runs, with no model calls. For one issue:

  signal = the gate's confidence that the cheap answer can stand
  signal >= τ  -> keep the cheap tier's result
  signal <  τ  -> escalate: the full agent's result, and its cost on top

Gates:
  self       the cheap tier's own confidences: min(type-label conf., component conf.)
  agreement  a decision backend (E6) asked the same questions: if its type and
             component both agree with the cheap tier, its min confidence; otherwise 0.
             A backend's confidence is about *its* answer, so disagreement is the signal.

τ is chosen on dev only: the cheapest τ whose accuracy is not below the full agent's,
with 2-fold cross-fitting so the reported numbers don't flatter the choice.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from triagelab.eval.dataset import EvalExample
from triagelab.eval.score import METRICS, align, statistic
from triagelab.hashing import stable_hash
from triagelab.triage import TriageResult

GateKind = Literal["self", "agreement"]


def _type_of(p: TriageResult, types: Sequence[str]) -> tuple[str | None, float]:
    found = [label for label in p.labels if label in types]
    if not found:
        return None, 0.0
    best = max(found, key=lambda label: p.label_confidence.get(label, 0.0))
    return best, p.label_confidence.get(best, 0.0)


def self_signal(cheap: TriageResult, types: Sequence[str]) -> float:
    if cheap.error is not None:
        return 0.0
    _, type_conf = _type_of(cheap, types)
    return min(type_conf, cheap.component_confidence or 0.0)


def agreement_signal(cheap: TriageResult, gate: TriageResult, types: Sequence[str]) -> float:
    if cheap.error is not None or gate.error is not None:
        return 0.0
    cheap_type, _ = _type_of(cheap, types)
    gate_type, gate_type_conf = _type_of(gate, types)
    if cheap_type is None or cheap_type != gate_type or cheap.component != gate.component:
        return 0.0
    return min(gate_type_conf, gate.component_confidence or 0.0)


@dataclass(frozen=True)
class CascadePoint:
    tau: float
    escalated: float  # share of issues sent to the full agent
    metrics: dict[str, float]
    cost_per_1000: float


class Cascade:
    """The tiers' predictions and the gate signal, over the issues all of them answered."""

    def __init__(
        self,
        examples: Sequence[EvalExample],
        cheap: Mapping[str, TriageResult],
        full: Mapping[str, TriageResult],
        signal: Mapping[str, float],
        gate_cost: Mapping[str, float],
        metrics: Sequence[str],
    ) -> None:
        refs = {e.snapshot.issue_ref for e in examples}
        shared = refs & set(cheap) & set(full) & set(signal)
        self.examples = [e for e in examples if e.snapshot.issue_ref in shared]
        self._cheap, self._full, self._signal = cheap, full, signal
        self._gate_cost = gate_cost
        self._metrics = list(metrics)
        unknown = set(self._metrics) - set(METRICS)
        if unknown:
            raise ValueError(f"unknown metrics: {sorted(unknown)}")

    def refs(self, subset: Sequence[EvalExample] | None = None) -> list[str]:
        return [e.snapshot.issue_ref for e in (self.examples if subset is None else subset)]

    def combined(self, tau: float, refs: Sequence[str]) -> list[TriageResult]:
        return [
            self._cheap[r] if self._signal[r] >= tau else self._full[r]  # escalate
            for r in refs
        ]

    def point(self, tau: float, subset: Sequence[EvalExample] | None = None) -> CascadePoint:
        examples = self.examples if subset is None else list(subset)
        refs = self.refs(examples)
        preds = self.combined(tau, refs)
        data = align(examples, preds)
        values = {m: statistic(METRICS[m], data)(range(len(examples))) for m in self._metrics}
        escalated = [r for r in refs if self._signal[r] < tau]
        cost = sum(self._cheap[r].cost_usd + self._gate_cost.get(r, 0.0) for r in refs) + sum(
            self._full[r].cost_usd for r in escalated
        )
        return CascadePoint(
            tau=tau,
            escalated=len(escalated) / len(refs) if refs else 0.0,
            metrics={m: float("nan") if v is None else v for m, v in values.items()},
            cost_per_1000=1000 * cost / len(refs) if refs else 0.0,
        )

    def thresholds(self) -> list[float]:
        """Every τ that changes the decision: each distinct signal, plus 'escalate all'."""
        return [*sorted({0.0, *(self._signal[r] for r in self.refs())}), 1.01]

    def curve(self, subset: Sequence[EvalExample] | None = None) -> list[CascadePoint]:
        return [self.point(t, subset) for t in self.thresholds()]

    def choose_tau(self, subset: Sequence[EvalExample], tolerance: float = 0.0) -> float:
        """The cheapest τ whose metrics all stay within `tolerance` of the full agent's."""
        target = self.point(1.01, subset).metrics  # 1.01 escalates everything
        ok = [
            p
            for p in self.curve(subset)
            if all(p.metrics[m] >= target[m] - tolerance for m in self._metrics)
        ]
        return min(ok, key=lambda p: (p.cost_per_1000, -p.tau)).tau

    def cross_fitted(
        self, tolerance: float = 0.0, folds: int = 2
    ) -> tuple[list[float], CascadePoint]:
        """Choose τ on each fold's complement, apply it to the fold; pool the folds.

        Returns the chosen τs and one point computed over all issues, each issue routed by
        the τ chosen *without* it.
        """
        parts = [
            [e for e in self.examples if int(stable_hash(e.snapshot.issue_ref), 16) % folds == k]
            for k in range(folds)
        ]
        taus: list[float] = []
        routed: dict[str, float] = {}
        for k, part in enumerate(parts):
            rest = [e for j, p in enumerate(parts) if j != k for e in p]
            tau = self.choose_tau(rest, tolerance)
            taus.append(tau)
            routed.update(dict.fromkeys(self.refs(part), tau))
        # One pass with a per-issue τ: reuse `point` by shifting each signal against its τ.
        shifted = {r: self._signal[r] - routed[r] for r in routed}
        pooled = Cascade(
            self.examples, self._cheap, self._full, shifted, self._gate_cost, self._metrics
        ).point(0.0)
        return taus, CascadePoint(
            tau=float("nan"),
            escalated=pooled.escalated,
            metrics=pooled.metrics,
            cost_per_1000=pooled.cost_per_1000,
        )
