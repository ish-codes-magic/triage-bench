"""Reconstruct issues as they were at a point in time. This is where leakage is prevented.

The API returns an issue's *current* title and body. On CPython most bodies are edited
after creation, typically by a bot appending a "Linked PRs" section that names the fix,
so the current text would leak the answer. We rebuild the creation-time text from edit
history instead, and refuse (rather than guess) when that history can't prove it.
"""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from triagelab.data.models import IssueSnapshot, RawIssue

# The oldest body revision is timestamped at creation; allow for clock skew between the
# issue record and its first edit-history entry.
_CREATION_TOLERANCE = timedelta(seconds=60)


class SnapshotError(ValueError):
    """The creation-time text can't be reconstructed with confidence."""


def title_at_creation(issue: RawIssue) -> str:
    renames = sorted(issue.title_renames, key=lambda r: r.at)
    return renames[0].previous if renames else issue.title


def body_at_creation(issue: RawIssue) -> str:
    if issue.last_edited_at is None:
        return issue.body  # never edited: the current body *is* the original
    original = issue.original_body
    if original is None:
        raise SnapshotError(f"#{issue.number} was edited but has no revision history")
    if abs(original.at - issue.created_at) > _CREATION_TOLERANCE:
        raise SnapshotError(
            f"#{issue.number}: oldest revision ({original.at}) is not the creation revision"
        )
    return original.body


def to_snapshot(issue: RawIssue) -> IssueSnapshot:
    """The agent's input. Uses nothing that happened after `issue.created_at`."""
    return IssueSnapshot(
        issue_ref=f"{issue.repo}#{issue.number}",
        repo=issue.repo,
        number=issue.number,
        title=title_at_creation(issue),
        body=body_at_creation(issue),
        author_association=issue.author_association,
        created_at=issue.created_at,
    )


class IssueAsOf(BaseModel):
    """A *past* issue as someone looking at time `as_of` could have seen it (for M3's index)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    number: int
    created_at: datetime
    title: str
    body: str
    labels: tuple[str, ...]
    state: Literal["open", "closed"]
    state_reason: str | None


def view_as_of(issue: RawIssue, as_of: datetime) -> IssueAsOf:
    """Replay labels, renames and state changes strictly before `as_of`.

    The body is always the creation-time body: we only keep the oldest revision, and any
    later revision could contain information from after `as_of`.
    """
    if issue.created_at >= as_of:
        raise SnapshotError(f"#{issue.number} did not exist yet at {as_of}")

    title = title_at_creation(issue)
    for rename in sorted(issue.title_renames, key=lambda r: r.at):
        if rename.at < as_of:
            title = rename.current

    labels: set[str] = set()
    for event in sorted(issue.label_events, key=lambda e: e.at):
        if event.at >= as_of:
            break
        if event.added:
            labels.add(event.label)
        else:
            labels.discard(event.label)

    state: Literal["open", "closed"] = "open"
    reason: str | None = None
    for event in sorted(issue.state_events, key=lambda e: e.at):
        if event.at >= as_of:
            break
        state = "closed" if event.kind == "closed" else "open"
        reason = event.state_reason if event.kind == "closed" else None

    return IssueAsOf(
        number=issue.number,
        created_at=issue.created_at,
        title=title,
        body=body_at_creation(issue),
        labels=tuple(sorted(labels)),
        state=state,
        state_reason=reason,
    )
