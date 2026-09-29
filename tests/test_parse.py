from datetime import UTC, datetime

from triagelab.data.parse import parse_issue, parse_pr_files

from .data_fixtures import COLLECTED_AT, ORIGINAL_BODY, REPO, node, raw


def test_core_fields_and_current_values() -> None:
    issue = raw()
    assert issue.number == 1000
    assert issue.created_at == datetime(2026, 6, 1, 10, tzinfo=UTC)
    assert issue.labels_current == ("type-bug", "stdlib", "3.15")
    assert "gh-linked-prs" in issue.body  # the *current* body still carries the bot's section


def test_original_body_comes_from_the_oldest_revision() -> None:
    issue = raw()
    assert issue.original_body is not None
    assert issue.original_body.body == ORIGINAL_BODY
    assert issue.original_body.at == issue.created_at


def test_unedited_issue_has_no_original_body_record() -> None:
    assert raw(lastEditedAt=None).original_body is None


def test_label_events_keep_actor_and_bot_flag() -> None:
    events = raw().label_events
    assert [(e.label, e.actor.login, e.actor.is_bot) for e in events] == [
        ("type-bug", "reporter", False),
        ("stdlib", "triager", False),
        ("3.15", "bedevere-app", True),
    ]


def test_deleted_author_becomes_anonymous_non_bot() -> None:
    issue = raw(author=None)
    assert issue.author.login is None
    assert not issue.author.is_bot


def test_linked_prs_from_cross_references_are_deduplicated_and_sorted() -> None:
    prs = raw().linked_prs
    assert [(p.number, p.base_ref, p.via) for p in prs] == [
        (1002, "main", "cross_reference"),
        (1003, "3.14", "cross_reference"),
    ]


def test_closing_reference_wins_over_cross_reference_for_the_same_pr() -> None:
    closing = {
        "nodes": [
            {
                "number": 1002,
                "title": "gh-1000: Fix",
                "merged": True,
                "mergedAt": "2026-06-05T09:00:00Z",
                "baseRefName": "main",
            }
        ]
    }
    prs = raw(closedByPullRequestsReferences=closing).linked_prs
    assert prs[0].via == "closing_reference"


def test_duplicate_closure_is_parsed() -> None:
    n = node(
        stateReason="DUPLICATE", duplicateOf={"number": 900, "createdAt": "2026-01-01T00:00:00Z"}
    )
    n["timelineItems"]["nodes"].append(
        {
            "__typename": "MarkedAsDuplicateEvent",
            "createdAt": "2026-06-03T00:00:00Z",
            "actor": {"__typename": "User", "login": "triager"},
            "canonical": {
                "__typename": "Issue",
                "number": 900,
                "createdAt": "2026-01-01T00:00:00Z",
            },
        }
    )
    issue = parse_issue(REPO, n, COLLECTED_AT)
    assert issue.duplicate_of is not None
    assert issue.duplicate_of.number == 900
    assert issue.duplicate_marks[0].canonical == 900
    assert not issue.duplicate_marks[0].unmarked


def test_title_renames_are_kept_in_order() -> None:
    renames = raw().title_renames
    assert [(r.previous, r.current) for r in renames] == [
        ("foo() crashes", "foo() crashes on empty input (renamed)")
    ]


def test_pr_files() -> None:
    pr = parse_pr_files(
        "python/cpython",
        {
            "number": 1002,
            "files": {"totalCount": 2, "nodes": [{"path": "Lib/foo.py"}, {"path": "x"}]},
        },
    )
    assert pr.files == ("Lib/foo.py", "x")
    assert pr.files_total == 2
