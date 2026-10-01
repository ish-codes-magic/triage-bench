"""The cascade (AGENTS.md §11, E7): a cheap answer stands when its gate is confident;
otherwise the full agent decides.

Offline and exact: every tier's answers are stored predictions, so a cascade at any
threshold τ is a recombination of runs, with no model calls. Two granularities:

  Cascade          whole issues: the cheap tier (e.g. the stuffed agent) triages every
                   issue; when the gate's signal < τ the issue escalates to the full agent.
  DecisionCascade  one decision (H3): a decision backend answers, e.g. the type label;
                   when its confidence < τ the agent's answer is used instead.

Gates for issue-level cascades:
  self       the cheap tier's own confidences: min(type-label conf., component conf.)
  agreement  a decision backend asked the same questions: if its type and component both
             agree with the cheap tier, its min confidence; otherwise 0. A backend's
             confidence is about *its* answer, so disagreement is the signal.

τ is chosen on dev only: the cheapest τ that keeps every metric at the full agent's level
(within a tolerance), with 2-fold cross-fitting so the estimate doesn't flatter the choice.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from triagelab.eval.dataset import EvalExample
from triagelab.eval.score import METRICS, align, statistic
from triagelab.hashing import stable_hash
from triagelab.triage import TriageResult

GateKind = Literal["self", "agreement"]
ESCALATE_ALL = 1.01  # above any confidence


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
    escalated: float  # share of items sent to the full agent
    metrics: dict[str, float]
    cost_per_1000: float


class Thresholded(ABC):
    """τ-sweeps, τ choice and cross-fitting over items (issue refs) with a signal each."""

    def __init__(self, refs: Sequence[str], signal: Mapping[str, float], metrics: Sequence[str]):
        self._refs = list(refs)
        self._signal = signal
        self.metrics = list(metrics)

    def refs(self) -> list[str]:
        return list(self._refs)

    @abstractmethod
    def routed(self, tau_for: Mapping[str, float], refs: Sequence[str]) -> CascadePoint:
        """The point where item r is kept iff signal[r] >= tau_for[r]."""

    def escalates(self, ref: str, tau: float) -> bool:
        return self._signal[ref] < tau

    def point(self, tau: float, refs: Sequence[str] | None = None) -> CascadePoint:
        chosen = self._refs if refs is None else list(refs)
        p = self.routed(dict.fromkeys(chosen, tau), chosen)
        return CascadePoint(tau, p.escalated, p.metrics, p.cost_per_1000)

    def thresholds(self) -> list[float]:
        """Every τ that changes a routing: each distinct signal, plus 'escalate all'."""
        return [*sorted({0.0, *(self._signal[r] for r in self._refs)}), ESCALATE_ALL]

    def curve(self, refs: Sequence[str] | None = None) -> list[CascadePoint]:
        return [self.point(t, refs) for t in self.thresholds()]

    def choose_tau(self, refs: Sequence[str], tolerance: float = 0.0) -> float:
        """The cheapest τ whose metrics all stay within `tolerance` of the full agent's."""
        target = self.point(ESCALATE_ALL, refs).metrics
        ok = [
            p
            for p in self.curve(refs)
            if all(p.metrics[m] >= target[m] - tolerance for m in self.metrics)
        ]
        return min(ok, key=lambda p: (p.cost_per_1000, -p.tau)).tau

    def cross_fitted(
        self, tolerance: float = 0.0, folds: int = 2
    ) -> tuple[list[float], CascadePoint]:
        """Choose τ on the other folds, route each fold by it, and pool: an estimate of how
        the chosen τ does on issues it wasn't chosen on."""
        parts = [
            [r for r in self._refs if int(stable_hash(r), 16) % folds == k] for k in range(folds)
        ]
        taus: list[float] = []
        tau_for: dict[str, float] = {}
        for k, part in enumerate(parts):
            rest = [r for j, p in enumerate(parts) if j != k for r in p]
            tau = self.choose_tau(rest, tolerance)
            taus.append(tau)
            tau_for.update(dict.fromkeys(part, tau))
        return taus, self.routed(tau_for, self._refs)


def _metric_values(
    examples: Sequence[EvalExample], preds: Sequence[TriageResult], metrics: Sequence[str]
) -> dict[str, float]:
    data = align(examples, preds)
    out: dict[str, float] = {}
    for m in metrics:
        v = statistic(METRICS[m], data)(range(len(examples)))
        out[m] = float("nan") if v is None else v
    return out


class Cascade(Thresholded):
    """Issue-level: the tiers' predictions and the gate signal, on issues all of them have."""

    def __init__(
        self,
        examples: Sequence[EvalExample],
        cheap: Mapping[str, TriageResult],
        full: Mapping[str, TriageResult],
        signal: Mapping[str, float],
        gate_cost: Mapping[str, float],
        metrics: Sequence[str],
    ) -> None:
        unknown = set(metrics) - set(METRICS)
        if unknown:
            raise ValueError(f"unknown metrics: {sorted(unknown)}")
        shared = set(cheap) & set(full) & set(signal)
        self.examples = [e for e in examples if e.snapshot.issue_ref in shared]
        self._by_ref = {e.snapshot.issue_ref: e for e in self.examples}
        super().__init__([e.snapshot.issue_ref for e in self.examples], signal, metrics)
        self._cheap, self._full, self._gate_cost = cheap, full, gate_cost

    def combined(self, tau_for: Mapping[str, float], refs: Sequence[str]) -> list[TriageResult]:
        return [self._full[r] if self.escalates(r, tau_for[r]) else self._cheap[r] for r in refs]

    def routed(self, tau_for: Mapping[str, float], refs: Sequence[str]) -> CascadePoint:
        examples = [self._by_ref[r] for r in refs]
        escalated = [r for r in refs if self.escalates(r, tau_for[r])]
        cost = sum(self._cheap[r].cost_usd + self._gate_cost.get(r, 0.0) for r in refs)
        cost += sum(self._full[r].cost_usd for r in escalated)
        n = max(len(refs), 1)
        return CascadePoint(
            tau=float("nan"),
            escalated=len(escalated) / n,
            metrics=_metric_values(examples, self.combined(tau_for, refs), self.metrics),
            cost_per_1000=1000 * cost / n,
        )


@dataclass(frozen=True)
class DecisionPair:
    """One issue's answer to one question from the backend and from the agent."""

    backend_correct: bool
    confidence: float
    agent_correct: bool
    backend_cost: float
    agent_cost: float


class DecisionCascade(Thresholded):
    """Decision-level (H3): the backend's answer stands when it is confident enough;
    otherwise the agent's. Escalating a decision means running the agent on the issue."""

    def __init__(self, pairs: Mapping[str, DecisionPair]) -> None:
        super().__init__(sorted(pairs), {r: p.confidence for r, p in pairs.items()}, ["accuracy"])
        self._pairs = pairs

    def routed(self, tau_for: Mapping[str, float], refs: Sequence[str]) -> CascadePoint:
        right = cost = 0.0
        escalated = 0
        for r in refs:
            p = self._pairs[r]
            if self.escalates(r, tau_for[r]):
                escalated += 1
                right += p.agent_correct
                cost += p.backend_cost + p.agent_cost
            else:
                right += p.backend_correct
                cost += p.backend_cost
        n = max(len(refs), 1)
        return CascadePoint(float("nan"), escalated / n, {"accuracy": right / n}, 1000 * cost / n)
