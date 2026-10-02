"""The routed system (M8): typed backends take the decisions they are good at, and a full
triage system does the rest.

    base system (e.g. the stuffed agent)  -> a complete TriageResult
    type backend (e.g. LLM, logprobs)     -> overwrites the type label
    component backend (LLM, verbalized)   -> overwrites the component

Every part is an ordinary experiment config, so the routed system is itself a config
(`system.kind: routed`), and each part stays separately measurable. A backend that
abstains leaves the base system's answer in place.
"""

import time
from collections.abc import Mapping, Sequence

from triagelab.data.models import IssueSnapshot
from triagelab.decisions.questions import QuestionId
from triagelab.triage import Triager, TriageResult


def route(
    base: TriageResult,
    decided: Mapping[QuestionId, TriageResult],
    types: Sequence[str],
) -> TriageResult:
    """`base` with the type label and/or component replaced by the backends' answers."""
    update: dict[str, object] = {}
    by = dict(base.decided_by)
    t = decided.get("type")
    if t is not None and t.labels:
        answer = t.labels[0]
        kept = [label for label in base.labels if label not in types]
        confidence = {k: v for k, v in base.label_confidence.items() if k not in types}
        update["labels"] = [answer, *kept]
        update["label_confidence"] = {answer: t.label_confidence.get(answer, 0.0), **confidence}
        by["type"] = t.decided_by.get("type", "llm")
    c = decided.get("component")
    if c is not None and c.component:
        others = [x for x in base.component_candidates if x != c.component]
        update["component"] = c.component
        update["component_confidence"] = c.component_confidence
        update["component_candidates"] = [c.component, *others][:3]
        by["component"] = c.decided_by.get("component", "llm")
    parts = list(decided.values())
    return base.model_copy(
        update={
            **update,
            "decided_by": by,
            "cost_usd": base.cost_usd + sum(p.cost_usd for p in parts),
            "tokens_in": base.tokens_in + sum(p.tokens_in for p in parts),
            "tokens_out": base.tokens_out + sum(p.tokens_out for p in parts),
        }
    )


class RoutedTriager:
    name = "routed"

    def __init__(
        self, base: Triager, deciders: Mapping[QuestionId, Triager], types: Sequence[str]
    ) -> None:
        self._base = base
        self._deciders = dict(deciders)
        self._types = list(types)

    def triage(self, issue: IssueSnapshot) -> TriageResult:
        started = time.perf_counter()
        base = self._base.triage(issue)
        decided: dict[QuestionId, TriageResult] = {
            qid: decider.triage(issue) for qid, decider in self._deciders.items()
        }
        result = route(base, decided, self._types)
        return result.model_copy(
            update={"latency_ms": round((time.perf_counter() - started) * 1000)}
        )
