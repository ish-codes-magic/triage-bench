"""Leakage guards (AGENTS.md §7.2): nothing from after an issue's creation may reach the agent.

These run as their own CI check (`pytest -m leakage`). If one fails, the evaluation is
invalid until it is fixed; don't mark these xfail or skip them.
"""

from datetime import timedelta
from typing import Any

import pytest

from triagelab.data.models import (
    BodyRevision,
    Comment,
    IssueRef,
    IssueSnapshot,
    LabelEvent,
    RawIssue,
    StateEvent,
)
from triagelab.data.snapshot import SnapshotError, to_snapshot, view_as_of

from .data_fixtures import ORIGINAL_BODY, raw

pytestmark = pytest.mark.leakage

# The complete agent input. Changing this set is a leakage decision: update AGENTS.md §3
# and the dataset card, not just this test.
ALLOWED_SNAPSHOT_FIELDS = {
    "issue_ref",
    "repo",
    "number",
    "title",
    "body",
    "author_association",
    "created_at",
}

# RawIssue fields a snapshot may read. Everything else is post-creation (or current-state)
# information and must have no effect on the snapshot.
CREATION_INPUTS = {
    "repo",
    "number",
    "created_at",
    "author_association",
    "title",  # only via title_renames when renamed
    "body",  # only via original_body when edited
    "title_renames",
    "original_body",
    "last_edited_at",
}


def test_snapshot_has_exactly_the_allowed_fields() -> None:
    assert set(IssueSnapshot.model_fields) == ALLOWED_SNAPSHOT_FIELDS


def test_snapshot_uses_the_original_body_not_the_bot_edited_one() -> None:
    snap = to_snapshot(raw())
    assert snap.body == ORIGINAL_BODY
    assert "gh-linked-prs" not in snap.body
    assert "1002" not in snap.body  # the fixing PR's number must not appear


def test_snapshot_uses_the_title_before_any_rename() -> None:
    assert to_snapshot(raw()).title == "foo() crashes"


def _post_creation_mutations(issue: RawIssue) -> dict[str, Any]:
    later = issue.created_at + timedelta(days=3)
    bot = issue.author.model_copy(update={"login": "some-bot", "is_bot": True})
    return {
        "url": "https://example.invalid/changed",
        "closed_at": later,
        "state": "OPEN",
        "state_reason": "DUPLICATE",
        "author": bot,
        "labels_current": ("type-feature", "LEAKED-LABEL"),
        "duplicate_of": IssueRef(number=1, created_at=issue.created_at - timedelta(days=1)),
        "label_events": (LabelEvent(at=later, label="LEAKED-LABEL", added=True, actor=bot),),
        "state_events": (StateEvent(at=later, kind="closed", state_reason="COMPLETED"),),
        "duplicate_marks": (),
        "comments": (
            Comment(at=later, author=bot, author_association="MEMBER", body="Fixed in gh-9999"),
        ),
        "comments_total": 99,
        "timeline_total": 99,
        "linked_prs": (),
        "collected_at": later + timedelta(days=30),
    }


def test_every_post_creation_field_is_covered_by_the_invariance_test() -> None:
    # Adding a field to RawIssue forces a decision here: creation input, or mutated below.
    mutated = set(_post_creation_mutations(raw()))
    assert mutated | CREATION_INPUTS == set(RawIssue.model_fields)


@pytest.mark.parametrize("field", sorted(_post_creation_mutations(raw())))
def test_changing_post_creation_field_never_changes_the_snapshot(field: str) -> None:
    issue = raw()
    changed = issue.model_copy(update={field: _post_creation_mutations(issue)[field]})
    assert to_snapshot(changed) == to_snapshot(issue)


def test_current_body_edits_are_invisible_once_the_original_is_known() -> None:
    issue = raw()
    edited = issue.model_copy(update={"body": "EDIT: this is a duplicate of #1, fixed in gh-1002"})
    assert to_snapshot(edited).body == ORIGINAL_BODY


def test_edited_issue_without_history_is_rejected_not_guessed() -> None:
    with pytest.raises(SnapshotError, match="no revision history"):
        to_snapshot(raw().model_copy(update={"original_body": None}))


def test_oldest_revision_must_be_the_creation_revision() -> None:
    issue = raw()
    late = BodyRevision(at=issue.created_at + timedelta(hours=2), body="later text", editor=None)
    with pytest.raises(SnapshotError, match="not the creation revision"):
        to_snapshot(issue.model_copy(update={"original_body": late}))


def test_as_of_view_replays_only_earlier_events() -> None:
    issue = raw()
    # Fixture: type-bug at +1s (author), stdlib at +3h (triager), 3.15 at +3h00m05s (bot),
    # renamed at +4h, closed on day 4.
    early = view_as_of(issue, issue.created_at + timedelta(hours=1))
    assert early.labels == ("type-bug",)
    assert early.title == "foo() crashes"
    assert early.state == "open"

    late = view_as_of(issue, issue.created_at + timedelta(days=10))
    assert set(late.labels) == {"type-bug", "stdlib", "3.15"}
    assert late.title == "foo() crashes on empty input (renamed)"
    assert late.state == "closed"
    assert late.body == ORIGINAL_BODY  # never a later revision


def test_as_of_view_refuses_issues_that_did_not_exist_yet() -> None:
    issue = raw()
    with pytest.raises(SnapshotError, match="did not exist yet"):
        view_as_of(issue, issue.created_at)
