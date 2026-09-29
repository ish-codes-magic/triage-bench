"""Gold labels in evaluation: re-scoring, label-noise measurement and a human baseline.

- `with_gold`: the examples a person adjudicated, with the gold answer in place of the
  silver one. Every stored prediction can be re-scored against it offline, for free.
- `human_predictions`: the person's *blind* pass as predictions, so a human reading the
  same creation-time issue is scored by the same metric code as every system.
- `agreement_by_task`: Cohen's kappa per task between two answer sets, for
  silver-vs-gold (label noise, AGENTS.md §7.5) and blind-vs-final (what the evidence
  changed).
"""

from collections.abc import Callable, Sequence

from pydantic import BaseModel

from triagelab.data.profile import RepoProfile
from triagelab.eval.agreement import cohen_kappa, exact_agreement
from triagelab.eval.dataset import EvalExample, Gold
from triagelab.labeling.gold import Decision, GoldRecord
from triagelab.triage import TriageResult


def label_group(label: str, profile: RepoProfile) -> str:
    tax = profile.taxonomy
    if label in tax.type:
        return "type"
    if label in tax.area:
        return "area"
    return "family"


def gold_from(decision: Decision, profile: RepoProfile) -> Gold:
    return Gold(
        labels=frozenset(decision.labels),
        label_groups={label: label_group(label, profile) for label in decision.labels},
        human_triaged=True,  # a person labeled it, by definition
        duplicate_of=decision.duplicate_of,
        component=decision.component,
        needs_info=decision.needs_info,
    )


def usable(records: dict[str, GoldRecord]) -> dict[str, GoldRecord]:
    return {ref: r for ref, r in records.items() if r.final is not None and not r.unusable}


def with_gold(
    examples: Sequence[EvalExample], records: dict[str, GoldRecord], profile: RepoProfile
) -> list[EvalExample]:
    """Only adjudicated, usable issues, each with its gold answer."""
    done = usable(records)
    out: list[EvalExample] = []
    for e in examples:
        record = done.get(e.snapshot.issue_ref)
        if record is not None and record.final is not None:
            out.append(e.model_copy(update={"gold": gold_from(record.final, profile)}))
    return out


def human_predictions(records: dict[str, GoldRecord]) -> list[TriageResult]:
    """The blind pass as a system's predictions (it never names duplicates)."""
    return [
        TriageResult(
            issue_ref=r.issue_ref,
            labels=list(r.blind.labels),
            component=r.blind.component,
            component_candidates=[r.blind.component] if r.blind.component else [],
            needs_info=r.blind.needs_info,
            decided_by=dict.fromkeys(("labels", "component", "needs_info"), "human"),
            latency_ms=round(r.blind_seconds * 1000),
        )
        for r in usable(records).values()
    ]


class TaskAgreement(BaseModel):
    task: str
    n: int
    kappa: float | None
    exact: float | None


def _type_label(gold: Gold) -> str | None:
    types = sorted(label for label, g in gold.label_groups.items() if g == "type")
    return types[0] if types else None


def agreement_by_task(
    pairs: Sequence[tuple[Gold, Gold]], vocabulary: Sequence[str]
) -> list[TaskAgreement]:
    """Kappa per task between two answers for the same issues (e.g. silver and gold)."""

    def task(
        name: str, keep: Callable[[Gold, Gold], bool], value: Callable[[Gold], object]
    ) -> TaskAgreement:
        kept = [(a, b) for a, b in pairs if keep(a, b)]
        xs, ys = [value(a) for a, _ in kept], [value(b) for _, b in kept]
        return TaskAgreement(
            task=name, n=len(kept), kappa=cohen_kappa(xs, ys), exact=exact_agreement(xs, ys)
        )

    labels = sorted(set(vocabulary))
    presence_a = [label in a.labels for a, _ in pairs if a.human_triaged for label in labels]
    presence_b = [label in b.labels for a, b in pairs if a.human_triaged for label in labels]
    triaged = sum(1 for a, _ in pairs if a.human_triaged)
    return [
        task("T1 type label", lambda a, b: a.human_triaged, _type_label),
        TaskAgreement(
            task="T1 labels (pooled per-label presence)",
            n=triaged,
            kappa=cohen_kappa(presence_a, presence_b),
            exact=exact_agreement(presence_a, presence_b),
        ),
        task("T2 is a duplicate", lambda a, b: True, lambda g: g.duplicate_of is not None),
        task(
            "T3 component",
            lambda a, b: a.component is not None and b.component is not None,
            lambda g: g.component,
        ),
        task("T4 needs info", lambda a, b: True, lambda g: g.needs_info),
    ]


def render_agreement(rows: Sequence[TaskAgreement], title: str) -> str:
    def f(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.2f}"

    lines = [
        f"| {title} | n | Cohen's kappa | exact agreement |",
        "|---|---|---|---|",
        *[f"| {r.task} | {r.n} | {f(r.kappa)} | {f(r.exact)} |" for r in rows],
    ]
    return "\n".join(lines)
