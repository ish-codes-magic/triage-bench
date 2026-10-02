"""Consistency across repeated runs (AGENTS.md §12.3): right every time, or only on average?

Temperature 0 does not make a hosted model deterministic, and an agent that takes a
different path can end somewhere else. So the same config is run k times on the same
issues (`triagelab eval --sample 1`, `--sample 2`, ...), and each decision is summarised
four ways:

  accuracy    the share correct, averaged over the k runs: what one run would score
  pass^k      the share of issues correct in *all* k runs: what a user can rely on
  ever right  the share correct in at least one run: what picking the best run would fake
  unanimous   the share where all k runs gave the same answer, right or wrong

pass^k <= accuracy <= ever right always holds, and the gaps are the instability.
"""

from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from triagelab.data.profile import RepoProfile, load_profile
from triagelab.eval.bootstrap import Interval, bootstrap_ci
from triagelab.eval.dataset import EvalExample
from triagelab.eval.report import Labels, examples_for, load_run
from triagelab.triage import TriageResult

Answer = Hashable


def accuracy(correct: Sequence[Sequence[bool]]) -> float | None:
    """Rows are issues, columns are runs: the mean share of correct answers."""
    cells = [c for row in correct for c in row]
    return sum(cells) / len(cells) if cells else None


def pass_k(correct: Sequence[Sequence[bool]]) -> float | None:
    return sum(all(row) for row in correct) / len(correct) if correct else None


def ever_right(correct: Sequence[Sequence[bool]]) -> float | None:
    return sum(any(row) for row in correct) / len(correct) if correct else None


def unanimous(answers: Sequence[Sequence[Answer]]) -> float | None:
    """The share of issues whose k answers are all the same."""
    return sum(len(set(row)) == 1 for row in answers) / len(answers) if answers else None


@dataclass(frozen=True)
class DecisionRows:
    """One decision, for every issue that has a reference answer: k answers and the truth."""

    name: str
    answers: list[tuple[Answer, ...]]
    truth: list[Answer]

    def correct(self) -> list[tuple[bool, ...]]:
        return [tuple(a == t for a in row) for row, t in zip(self.answers, self.truth, strict=True)]


def _type_labels(labels: Iterable[str], profile: RepoProfile) -> tuple[str, ...]:
    return tuple(sorted(set(labels) & set(profile.taxonomy.type)))


def _every_issue(_: EvalExample) -> bool:
    return True


def _labelled(e: EvalExample) -> bool:
    """Labels are a reference only where a person (or the adjudicator) applied them."""
    return e.gold.human_triaged


def decisions(
    examples: Sequence[EvalExample], runs: Sequence[dict[str, TriageResult]], profile: RepoProfile
) -> list[DecisionRows]:
    """The four decisions of a triage result, lined up across runs.

    Only issues answered by every run are compared, and each decision only where it has
    a reference answer: labels on triaged issues, the component where one was derived,
    the duplicate link everywhere (no link is an answer too).
    """
    shared = [e for e in examples if all(e.snapshot.issue_ref in run for run in runs)]

    def rows(
        name: str,
        of_result: Callable[[TriageResult], Answer],
        of_gold: Callable[[EvalExample], Answer],
        keep: Callable[[EvalExample], bool],
    ) -> DecisionRows:
        kept = [e for e in shared if keep(e)]
        return DecisionRows(
            name=name,
            answers=[tuple(of_result(run[e.snapshot.issue_ref]) for run in runs) for e in kept],
            truth=[of_gold(e) for e in kept],
        )

    return [
        rows(
            "type label",
            lambda r: _type_labels(r.labels, profile),
            lambda e: _type_labels(e.gold.labels, profile),
            _labelled,
        ),
        rows(
            "all labels (exact set)",
            lambda r: frozenset(r.labels),
            lambda e: e.gold.labels,
            _labelled,
        ),
        rows(
            "component",
            lambda r: r.component,
            lambda e: e.gold.component,
            lambda e: e.gold.component is not None,
        ),
        rows(
            "duplicate link",
            lambda r: r.duplicate_of,
            lambda e: e.gold.duplicate_of,
            _every_issue,
        ),
    ]


class Group(BaseModel):
    name: str
    runs: list[str]  # run ids: the same config, repeated


class ConsistencySpec(BaseModel):
    """Which repeated runs to compare, e.g. reports/consistency/dev.yaml."""

    title: str
    groups: list[Group]


def _ci(interval: Interval) -> str:
    return f"{interval.point:.2f} [{interval.low:.2f}, {interval.high:.2f}]"


def _interval[T](
    rows: Sequence[T], fn: Callable[[Sequence[T]], float | None], resamples: int
) -> str:
    def statistic(idx: Sequence[int]) -> float | None:
        return fn([rows[i] for i in idx])

    return _ci(bootstrap_ci(len(rows), statistic, resamples=resamples))


def build_report(
    spec: ConsistencySpec, runs_dir: Path, labels: Labels, *, resamples: int = 1000
) -> str:
    lines = [
        "| system | decision | k | issues | accuracy per run | accuracy | pass^k | ever right "
        "| unanimous |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for group in spec.groups:
        loaded = [load_run(runs_dir / run_id) for run_id in group.runs]
        cfg, split, _ = loaded[0]
        profile = load_profile(cfg.dataset.profile)
        runs = [{p.issue_ref: p for p in preds} for _, _, preds in loaded]
        for d in decisions(examples_for(cfg, split, labels), runs, profile):
            correct = d.correct()
            if not correct:  # e.g. no issue of this split has a reference component
                continue
            per_run = ", ".join(
                f"{sum(row[k] for row in correct) / len(correct):.2f}"
                for k in range(len(group.runs))
            )
            lines.append(
                f"| {group.name} | {d.name} | {len(group.runs)} | {len(correct)} | {per_run} | "
                f"{_interval(correct, accuracy, resamples)} | "
                f"{_interval(correct, pass_k, resamples)} | "
                f"{_interval(correct, ever_right, resamples)} | "
                f"{_interval(d.answers, unanimous, resamples)} |"
            )
    lines += [
        "",
        f"{labels.capitalize()} labels. Each system was run k times on the same issues with "
        "the same config; only the model calls were repeated. Cells are point estimates "
        "with 95% bootstrap intervals over issues (1,000 resamples). "
        "Runs: "
        + "; ".join(f"{g.name}: " + ", ".join(f"`{r}`" for r in g.runs) for g in spec.groups)
        + ".",
    ]
    return "\n".join(lines) + "\n"
