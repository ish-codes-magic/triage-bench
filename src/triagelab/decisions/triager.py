"""A decision backend behind the `Triager` contract, so E6 runs like any experiment.

Each issue gets the configured questions (type label, component). The answers fill the
matching `TriageResult` fields, and their confidences go where every system puts them
(`label_confidence`, `component_confidence`), so the scorer, the run registry and the
calibration analysis read decision runs exactly as they read agent runs.
"""

import time
from collections.abc import Sequence

from triagelab.data.models import IssueSnapshot
from triagelab.data.profile import RepoProfile
from triagelab.decisions.base import Decision, DecisionBackend
from triagelab.decisions.questions import QuestionId, questions
from triagelab.prompting import issue_block
from triagelab.triage import TriageResult


def backend_kind(backend: DecisionBackend) -> str:
    """The coarse `decided_by` value of AGENTS.md §3: jev | llm | classifier | agent."""
    return "llm" if backend.name.startswith("llm") else backend.name


class DecisionTriager:
    name = "decisions"

    def __init__(
        self,
        backend: DecisionBackend,
        profile: RepoProfile,
        question_ids: Sequence[QuestionId],
        *,
        max_body_chars: int,
    ) -> None:
        self._backend = backend
        all_questions = questions(profile)
        self._questions = [all_questions[q] for q in question_ids]
        self._max_body_chars = max_body_chars

    def triage(self, issue: IssueSnapshot) -> TriageResult:
        started = time.perf_counter()
        state = issue_block(issue, self._max_body_chars)
        decisions: dict[QuestionId, Decision] = {
            q.id: self._backend.choose(state, q.text, q.options) for q in self._questions
        }
        result = TriageResult(
            issue_ref=issue.issue_ref,
            cost_usd=sum(d.cost_usd for d in decisions.values()),
            latency_ms=round((time.perf_counter() - started) * 1000),
            decided_by=dict.fromkeys(decisions, backend_kind(self._backend)),
        )
        if (t := decisions.get("type")) is not None and t.answer:
            result = result.model_copy(
                update={
                    "labels": [str(t.answer)],
                    "label_confidence": {str(t.answer): t.confidence},
                }
            )
        if (c := decisions.get("component")) is not None and c.answer:
            ranked = sorted(c.distribution, key=lambda o: -c.distribution[o]) or [str(c.answer)]
            result = result.model_copy(
                update={
                    "component": str(c.answer),
                    "component_confidence": c.confidence,
                    "component_candidates": ranked[:3],
                }
            )
        return result
