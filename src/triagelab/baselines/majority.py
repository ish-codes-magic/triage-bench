"""Majority baseline: always predict the most frequent answer seen in training.

The floor every other system must clear. If an LLM agent can't beat "every issue is a
type-bug in stdlib", the complexity isn't earning its cost.
"""

from collections import Counter
from collections.abc import Sequence

from triagelab.data.models import IssueSnapshot
from triagelab.eval.dataset import EvalExample
from triagelab.triage import TriageResult


class MajorityTriager:
    name = "majority"

    def __init__(self, train: Sequence[EvalExample]) -> None:
        triaged = [e for e in train if e.gold.human_triaged]
        self._labels: list[str] = []
        self._label_confidence: dict[str, float] = {}
        for group in ("type", "area"):
            counts = Counter(
                lab for e in triaged for lab, g in e.gold.label_groups.items() if g == group
            )
            if counts:
                label, count = counts.most_common(1)[0]
                self._labels.append(label)
                self._label_confidence[label] = count / len(triaged)

        components = Counter(e.gold.component for e in train if e.gold.component is not None)
        total = sum(components.values())
        ranked = [c for c, _ in components.most_common()]
        self._component = ranked[0] if ranked else None
        self._candidates = ranked[:3]
        self._component_confidence = components.most_common(1)[0][1] / total if total else None

        self._needs_info_rate = sum(e.gold.needs_info for e in train) / len(train) if train else 0.0

    def triage(self, issue: IssueSnapshot) -> TriageResult:
        return TriageResult(
            issue_ref=issue.issue_ref,
            labels=list(self._labels),
            label_confidence=dict(self._label_confidence),
            component=self._component,
            component_confidence=self._component_confidence,
            component_candidates=list(self._candidates),
            needs_info=self._needs_info_rate >= 0.5,
            needs_info_confidence=self._needs_info_rate,
            decided_by=dict.fromkeys(("labels", "component", "needs_info"), "majority"),
        )
