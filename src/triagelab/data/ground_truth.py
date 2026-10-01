"""Silver ground truth: one documented, tested rule per task (AGENTS.md §7.3).

Every function here is pure: it reads a `RawIssue` (and the repo profile) and returns a
label plus *where the label came from*, so label noise can be analysed later. The rules
are restated in plain words in data/DATASET_CARD.md.
"""

import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from triagelab.data.models import PRFiles, RawIssue
from triagelab.data.profile import RepoProfile

# A label added by the author within this window of creation came from the issue form
# (or the author labelling their own report), not from a triager.
_AT_CREATION = timedelta(seconds=60)
# "Duplicate of #123" is GitHub's own convention; only trust it from people with triage rights.
_DUPLICATE_COMMENT = re.compile(r"^\s*duplicate of #(\d+)\b", re.IGNORECASE | re.MULTILINE)
_TRIAGE_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

LabelSource = Literal["author", "triager", "bot", "unknown"]
DuplicateSource = Literal["state_reason", "marked", "comment"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LabelTruth(_Frozen):
    name: str
    group: Literal["type", "area", "family"]
    source: LabelSource


class SilverTruth(_Frozen):
    """Derived ('silver') labels for one issue, each with its evidence."""

    number: int
    labels: tuple[LabelTruth, ...]
    human_triaged: bool
    duplicate_of: int | None
    duplicate_source: DuplicateSource | None
    component: str | None
    component_votes: dict[str, int]
    fix_prs: tuple[int, ...]
    needs_info: bool
    needs_info_at: datetime | None


def fix_prs(issue: RawIssue, profile: RepoProfile) -> list[int]:
    """Merged PRs into the main branch that fixed this issue.

    A PR counts if GitHub links it as closing the issue, or (CPython's convention) its
    title starts with "gh-<issue>:". Backports target release branches, so requiring the
    main branch keeps one fix from voting several times.
    """
    title_rx = profile.linked_pr_regex(issue.number)
    return [
        pr.number
        for pr in issue.linked_prs
        if pr.merged
        and pr.base_ref == profile.main_branch
        and (pr.via == "closing_reference" or title_rx.match(pr.title))
    ]


def _source(issue: RawIssue, label: str) -> LabelSource:
    """Who applied the label that is present now: the latest 'added' event for it."""
    added = [e for e in issue.label_events if e.added and e.label == label]
    if not added:
        return "unknown"
    last = max(added, key=lambda e: e.at)
    if last.actor.is_bot:
        return "bot"
    if last.actor.login is not None and last.actor.login == issue.author.login:
        return "author"
    return "triager"


def t1_labels(issue: RawIssue, profile: RepoProfile) -> tuple[LabelTruth, ...]:
    """T1: taxonomy labels present at collection time, with who applied each."""
    tax = profile.taxonomy
    out: list[LabelTruth] = []
    for name in sorted(set(issue.labels_current)):
        if not tax.contains(name):
            continue  # status/process/version labels are not triage targets
        group: Literal["type", "area", "family"] = (
            "type" if name in tax.type else "area" if name in tax.area else "family"
        )
        out.append(LabelTruth(name=name, group=group, source=_source(issue, name)))
    return tuple(out)


def human_triaged(issue: RawIssue, profile: RepoProfile) -> bool:
    """Did someone other than the author (and not a bot) add or remove a triage label?

    Issues nobody triaged have "no label" for lack of attention, not because none
    applies, so T1 metrics on silver labels should be read on triaged issues.
    """
    relevant = set(profile.needs_info_labels)
    for e in issue.label_events:
        if not (profile.taxonomy.contains(e.label) or e.label in relevant):
            continue
        if e.actor.is_bot or e.actor.login is None:
            continue
        if e.actor.login != issue.author.login:
            return True
    return False


def t2_duplicate(issue: RawIssue) -> tuple[int | None, DuplicateSource | None]:
    """T2: the original this issue duplicates, preferring GitHub's structured signals.

    Order: closed-as-duplicate state reason, then the latest still-active "marked as
    duplicate" event, then a "Duplicate of #N" comment from someone with triage rights.
    The original must be older: issue numbers are allocated in creation order, so
    `original < issue.number` guarantees it existed when this issue was opened.
    """

    def earlier(n: int | None) -> bool:
        return n is not None and n < issue.number

    original = issue.duplicate_of
    if issue.state_reason == "DUPLICATE" and original is not None and earlier(original.number):
        return original.number, "state_reason"

    active: int | None = None
    for mark in sorted(issue.duplicate_marks, key=lambda m: m.at):
        if mark.unmarked:
            if mark.canonical == active or mark.canonical is None:
                active = None
        else:
            active = mark.canonical
    if earlier(active):
        return active, "marked"

    for comment in sorted(issue.comments, key=lambda c: c.at):
        if comment.author_association not in _TRIAGE_ASSOCIATIONS or comment.author.is_bot:
            continue
        if (m := _DUPLICATE_COMMENT.search(comment.body)) and earlier(int(m.group(1))):
            return int(m.group(1)), "comment"
    return None, None


def component_of(path: str, profile: RepoProfile) -> tuple[str, str] | None:
    """(component, role) for a changed file, or None if unmapped or ignored."""
    comp = profile.component_of(path)
    return (comp.name, comp.role) if comp else None


def t3_component(
    issue: RawIssue, pr_files: dict[int, PRFiles], profile: RepoProfile
) -> tuple[str | None, dict[str, int], tuple[int, ...]]:
    """T3: majority component over files changed by the issue's fixing PRs.

    Primary components (stdlib, interpreter-core, ...) decide the vote. Supporting ones
    (tests, docs) only count when a fix touches nothing else, because almost every fix
    also adds a test. A tie means the fix spans components, so the label is skipped.
    """
    prs = tuple(fix_prs(issue, profile))
    primary: Counter[str] = Counter()
    supporting: Counter[str] = Counter()
    for pr in prs:
        for path in pr_files[pr].files if pr in pr_files else ():
            mapped = component_of(path, profile)
            if mapped is not None:
                (primary if mapped[1] == "primary" else supporting)[mapped[0]] += 1
    votes = primary or supporting
    ranked = votes.most_common(2)
    if not ranked or (len(ranked) == 2 and ranked[0][1] == ranked[1][1]):
        return None, dict(primary + supporting), prs
    return ranked[0][0], dict(primary + supporting), prs


def t4_needs_info(issue: RawIssue, profile: RepoProfile) -> tuple[bool, datetime | None]:
    """T4: did a human ever apply a needs-info label (even if it was later removed)?"""
    wanted = set(profile.needs_info_labels)
    times = [
        e.at for e in issue.label_events if e.added and e.label in wanted and not e.actor.is_bot
    ]
    if times:
        return True, min(times)
    return bool(wanted & set(issue.labels_current)), None


def derive(issue: RawIssue, pr_files: dict[int, PRFiles], profile: RepoProfile) -> SilverTruth:
    dup, dup_source = t2_duplicate(issue)
    component, votes, prs = t3_component(issue, pr_files, profile)
    needs_info, needs_info_at = t4_needs_info(issue, profile)
    return SilverTruth(
        number=issue.number,
        labels=t1_labels(issue, profile),
        human_triaged=human_triaged(issue, profile),
        duplicate_of=dup,
        duplicate_source=dup_source,
        component=component,
        component_votes=votes,
        fix_prs=prs,
        needs_info=needs_info,
        needs_info_at=needs_info_at,
    )
