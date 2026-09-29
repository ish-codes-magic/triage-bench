"""Synthetic GitHub GraphQL nodes shaped like real CPython responses (captured 2026-09-29).

Synthetic rather than real issue text, so tests don't depend on third-party content and
every edge case is present on purpose.
"""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from triagelab.data.models import RawIssue
from triagelab.data.parse import parse_issue

REPO = "python/cpython"
COLLECTED_AT = datetime(2026, 9, 29, 12, tzinfo=UTC)
ORIGINAL_BODY = "### Bug description:\n\n`foo()` crashes on empty input."
CURRENT_BODY = (
    "# Bug report\n\n" + ORIGINAL_BODY + "\n\n<!-- gh-linked-prs -->\n### Linked PRs\n"
    "* gh-1002\n<!-- /gh-linked-prs -->\n"
)

_AUTHOR = {"__typename": "User", "login": "reporter"}
_TRIAGER = {"__typename": "User", "login": "triager"}
_BOT = {"__typename": "Bot", "login": "bedevere-app"}

BASE_NODE: dict[str, Any] = {
    "number": 1000,
    "url": "https://github.com/python/cpython/issues/1000",
    "title": "foo() crashes on empty input (renamed)",
    "body": CURRENT_BODY,
    "createdAt": "2026-06-01T10:00:00Z",
    "closedAt": "2026-06-05T10:00:00Z",
    "state": "CLOSED",
    "stateReason": "COMPLETED",
    "lastEditedAt": "2026-06-02T09:00:00Z",
    "authorAssociation": "NONE",
    "author": _AUTHOR,
    "labels": {"nodes": [{"name": "type-bug"}, {"name": "stdlib"}, {"name": "3.15"}]},
    "duplicateOf": None,
    "originalBody": {
        "nodes": [{"editedAt": "2026-06-01T10:00:00Z", "diff": ORIGINAL_BODY, "editor": _AUTHOR}]
    },
    "comments": {
        "totalCount": 1,
        "nodes": [
            {
                "createdAt": "2026-06-01T12:00:00Z",
                "body": "Thanks, confirmed.",
                "authorAssociation": "MEMBER",
                "author": _TRIAGER,
            }
        ],
    },
    "closedByPullRequestsReferences": {"nodes": []},
    "timelineItems": {
        "totalCount": 7,
        "nodes": [
            {  # issue-form label, applied by the author's own submission
                "__typename": "LabeledEvent",
                "createdAt": "2026-06-01T10:00:01Z",
                "label": {"name": "type-bug"},
                "actor": _AUTHOR,
            },
            {  # triager adds an area label a few hours later
                "__typename": "LabeledEvent",
                "createdAt": "2026-06-01T13:00:00Z",
                "label": {"name": "stdlib"},
                "actor": _TRIAGER,
            },
            {  # bot adds a process label
                "__typename": "LabeledEvent",
                "createdAt": "2026-06-01T13:00:05Z",
                "label": {"name": "3.15"},
                "actor": _BOT,
            },
            {
                "__typename": "RenamedTitleEvent",
                "createdAt": "2026-06-01T14:00:00Z",
                "previousTitle": "foo() crashes",
                "currentTitle": "foo() crashes on empty input (renamed)",
            },
            {  # the main fix, linked by CPython's "gh-<issue>:" title convention
                "__typename": "CrossReferencedEvent",
                "createdAt": "2026-06-02T08:00:00Z",
                "source": {
                    "__typename": "PullRequest",
                    "number": 1002,
                    "title": "gh-1000: Fix foo() on empty input",
                    "merged": True,
                    "mergedAt": "2026-06-05T09:00:00Z",
                    "baseRefName": "main",
                },
            },
            {  # its backport: must not vote a second time
                "__typename": "CrossReferencedEvent",
                "createdAt": "2026-06-05T09:30:00Z",
                "source": {
                    "__typename": "PullRequest",
                    "number": 1003,
                    "title": "[3.14] gh-1000: Fix foo() on empty input (GH-1002)",
                    "merged": True,
                    "mergedAt": "2026-06-05T11:00:00Z",
                    "baseRefName": "3.14",
                },
            },
            {
                "__typename": "ClosedEvent",
                "createdAt": "2026-06-05T10:00:00Z",
                "stateReason": "COMPLETED",
                "duplicateOf": None,
            },
        ],
    },
}


def node(**overrides: Any) -> dict[str, Any]:
    """A deep copy of BASE_NODE with top-level fields overridden."""
    n = deepcopy(BASE_NODE)
    n.update(overrides)
    return n


def raw(**overrides: Any) -> RawIssue:
    return parse_issue(REPO, node(**overrides), COLLECTED_AT)
