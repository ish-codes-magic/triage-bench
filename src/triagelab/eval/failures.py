"""Which tasks a system got wrong on which issues: the input to failure analysis (§12.6).

A failure is per issue and per task, with a short human-readable difference, e.g.
T1 "missing: stdlib; extra: docs". Ground truth is whatever the examples carry (silver,
or gold via `eval.gold_labels.with_gold`). T1 only counts human-triaged issues and T3
only issues with a known component, the same subsets the scorer uses.
"""

from collections.abc import Sequence

from pydantic import BaseModel

from triagelab.eval.dataset import EvalExample
from triagelab.triage import TriageResult


class Failure(BaseModel):
    issue_ref: str
    trace_id: str
    tasks: list[str]  # e.g. ["T1", "T3"]
    details: dict[str, str]  # task -> what differed


def _labels(e: EvalExample, p: TriageResult) -> str | None:
    if not e.gold.human_triaged:
        return None
    truth, predicted = set(e.gold.labels), set(p.labels)
    if truth == predicted:
        return None
    missing, extra = sorted(truth - predicted), sorted(predicted - truth)
    parts = [
        f"missing: {', '.join(missing)}" if missing else "",
        f"extra: {', '.join(extra)}" if extra else "",
    ]
    return "; ".join(x for x in parts if x)


def _duplicate(e: EvalExample, p: TriageResult) -> str | None:
    truth, predicted = e.gold.duplicate_of, p.duplicate_of
    if truth == predicted:
        return None
    if truth is None:
        return f"false duplicate: said #{predicted}"
    if predicted is None:
        found = "among candidates" if truth in p.duplicate_candidates else "not found"
        return f"missed duplicate of #{truth} ({found})"
    return f"wrong original: said #{predicted}, truth #{truth}"


def _component(e: EvalExample, p: TriageResult) -> str | None:
    if e.gold.component is None or e.gold.component == p.component:
        return None
    return f"said {p.component}, truth {e.gold.component}"


def _needs_info(e: EvalExample, p: TriageResult) -> str | None:
    if e.gold.needs_info == p.needs_info:
        return None
    return "said needs info, it didn't" if p.needs_info else "missed that it needed info"


CHECKS = {"T1": _labels, "T2": _duplicate, "T3": _component, "T4": _needs_info}


def find_failures(
    examples: Sequence[EvalExample], predictions: Sequence[TriageResult]
) -> list[Failure]:
    by_ref = {p.issue_ref: p for p in predictions}
    failures: list[Failure] = []
    for e in examples:
        p = by_ref.get(e.snapshot.issue_ref)
        if p is None:
            continue
        details = {task: d for task, check in CHECKS.items() if (d := check(e, p)) is not None}
        if details:
            failures.append(
                Failure(
                    issue_ref=e.snapshot.issue_ref,
                    trace_id=p.trace_id,
                    tasks=list(details),
                    details=details,
                )
            )
    return failures
