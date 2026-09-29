"""The retrieval corpus: every collected issue, stored so it can only be read *as of* a time.

Each entry keeps the creation-time title and body (reconstructed exactly as for agent
snapshots) plus the timestamped events needed to replay labels, renames and state. Nothing
else from after creation is stored, so the corpus cannot leak what the API's current
fields would (bot "Linked PRs" sections, later edits, comments).

This is where AGENTS.md §7.2 is enforced for retrieval: `visible(as_of)` and `get(as_of)`
are the only ways in, and both refuse issues created at or after `as_of`.
"""

from bisect import bisect_left
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from triagelab.data.build import exclusion_reason
from triagelab.data.models import LabelEvent, RawIssue, StateEvent, TitleRename
from triagelab.data.snapshot import IssueAsOf, body_at_creation, replay, title_at_creation
from triagelab.data.storage import append_jsonl, read_jsonl


class IndexedIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    number: int
    url: str
    created_at: datetime
    title: str  # at creation
    body: str  # at creation
    title_renames: tuple[TitleRename, ...]
    label_events: tuple[LabelEvent, ...]
    state_events: tuple[StateEvent, ...]


class NotVisibleError(LookupError):
    """The issue did not exist yet (or isn't in the corpus) at the requested time."""


def to_indexed(issue: RawIssue) -> IndexedIssue:
    return IndexedIssue(
        number=issue.number,
        url=issue.url,
        created_at=issue.created_at,
        title=title_at_creation(issue),
        body=body_at_creation(issue),
        title_renames=issue.title_renames,
        label_events=issue.label_events,
        state_events=issue.state_events,
    )


class Corpus:
    """Issues ordered by creation time, readable only as of a given moment."""

    def __init__(self, issues: Iterable[IndexedIssue]) -> None:
        self._issues = sorted(issues, key=lambda i: (i.created_at, i.number))
        self._created = [i.created_at for i in self._issues]
        self._by_number = {i.number: i for i in self._issues}

    def __len__(self) -> int:
        return len(self._issues)

    @property
    def issues(self) -> Sequence[IndexedIssue]:
        """All entries, oldest first. Index builders use this; *queries* must use visible()."""
        return self._issues

    def visible_count(self, as_of: datetime) -> int:
        """How many issues were created strictly before `as_of` (a prefix, since sorted)."""
        return bisect_left(self._created, as_of)

    def visible(self, as_of: datetime) -> Sequence[IndexedIssue]:
        return self._issues[: self.visible_count(as_of)]

    def get(self, number: int, as_of: datetime) -> IssueAsOf:
        issue = self._by_number.get(number)
        if issue is None or issue.created_at >= as_of:
            # One message for "later", "a PR" and "older than the index": telling them apart
            # would reveal whether an issue exists in the future.
            raise NotVisibleError(
                f"#{number} is not available as of {as_of.isoformat()}: it was opened later, "
                "is a pull request, or is older than the indexed history"
            )
        return replay(issue, issue.title, issue.body, as_of)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        append_jsonl(path, self._issues)

    @classmethod
    def load(cls, path: Path) -> "Corpus":
        return cls(read_jsonl(path, IndexedIssue))


def build_corpus(issues: Iterable[RawIssue]) -> Corpus:
    """Every issue whose creation-time text is provable (bot-authored ones included:
    they are real history a triager could search, unlike eval examples)."""
    kept: list[IndexedIssue] = []
    for issue in issues:
        reason = exclusion_reason(issue)
        if reason is None or reason == "bot_author":
            kept.append(to_indexed(issue))
    return Corpus(kept)
