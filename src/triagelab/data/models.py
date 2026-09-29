"""Data types for issues, from raw API history to the agent's input.

Two types matter most:
  - `RawIssue` is everything we collected, *including* what happened after the issue
    was opened (labels, comments, closure, linked PRs, every body revision).
  - `IssueSnapshot` is what the agent may see: the issue exactly as it existed at
    creation. It is the leakage contract, so it has no field that can carry post-creation
    information. `tests/test_leakage.py` pins its field set.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Actor(_Frozen):
    login: str | None  # None for deleted ("ghost") accounts
    is_bot: bool


class LabelEvent(_Frozen):
    at: datetime
    label: str
    added: bool  # False for an "unlabeled" event
    actor: Actor


class StateEvent(_Frozen):
    at: datetime
    kind: Literal["closed", "reopened"]
    state_reason: str | None = None
    duplicate_of: int | None = None


class DuplicateMark(_Frozen):
    at: datetime
    canonical: int | None  # the original issue; None if it isn't an issue in this repo
    canonical_created_at: datetime | None
    unmarked: bool  # True for an "unmarked as duplicate" event
    actor: Actor | None


class TitleRename(_Frozen):
    at: datetime
    previous: str
    current: str


class Comment(_Frozen):
    at: datetime
    author: Actor
    author_association: str
    body: str


class BodyRevision(_Frozen):
    at: datetime
    body: str
    editor: Actor | None


class LinkedPR(_Frozen):
    number: int
    title: str
    merged: bool
    merged_at: datetime | None
    base_ref: str | None
    via: Literal["closing_reference", "cross_reference"]


class IssueRef(_Frozen):
    number: int
    created_at: datetime


class RawIssue(_Frozen):
    """One issue with its full history, as returned by the API at collection time."""

    repo: str
    number: int
    url: str
    title: str  # current title (may have been renamed since creation)
    body: str  # current body (may have been edited since creation)
    created_at: datetime
    closed_at: datetime | None
    state: str
    state_reason: str | None
    author: Actor
    author_association: str  # as reported at collection time, not at creation
    last_edited_at: datetime | None
    original_body: BodyRevision | None  # oldest revision in the edit history, if edited
    labels_current: tuple[str, ...]
    duplicate_of: IssueRef | None
    label_events: tuple[LabelEvent, ...]
    state_events: tuple[StateEvent, ...]
    duplicate_marks: tuple[DuplicateMark, ...]
    title_renames: tuple[TitleRename, ...]
    comments: tuple[Comment, ...]
    comments_total: int
    timeline_total: int
    linked_prs: tuple[LinkedPR, ...]
    collected_at: datetime


class PRFiles(_Frozen):
    """Paths changed by one pull request (fetched separately, only for linked PRs)."""

    repo: str
    number: int
    files: tuple[str, ...]
    files_total: int


class IssueSnapshot(_Frozen):
    """The agent's entire view of an issue: how it looked the moment it was opened.

    Deliberately minimal (AGENTS.md §3). Adding a field here is a leakage decision and
    must be reflected in `tests/test_leakage.py`.
    """

    issue_ref: str  # "owner/repo#123"
    repo: str
    number: int
    title: str
    body: str
    author_association: str
    created_at: datetime
