"""Parse GitHub GraphQL responses into typed records. Pure functions, no I/O.

GraphQL returns nested, partly-nullable JSON (deleted accounts become `null` authors,
cross-references can come from issues rather than PRs). All of that is resolved here,
once, so everything downstream works with complete, typed records.
"""

from datetime import datetime
from typing import Any, cast

from triagelab.data.models import (
    Actor,
    BodyRevision,
    Comment,
    DuplicateMark,
    IssueRef,
    LabelEvent,
    LinkedPR,
    PRFiles,
    RawIssue,
    StateEvent,
    TitleRename,
)

Json = dict[str, Any]


def _nodes(connection: Any) -> list[Json]:
    if not isinstance(connection, dict):
        return []
    nodes = cast(list[Any], cast(Json, connection).get("nodes") or [])
    return [cast(Json, n) for n in nodes if isinstance(n, dict)]


def parse_actor(node: Any) -> Actor:
    if not isinstance(node, dict):
        return Actor(login=None, is_bot=False)  # deleted ("ghost") account
    actor = cast(Json, node)
    return Actor(login=actor.get("login"), is_bot=actor.get("__typename") == "Bot")


def _linked_pr(node: Json, via: str) -> LinkedPR:
    return LinkedPR.model_validate(
        {
            "number": node["number"],
            "title": node.get("title") or "",
            "merged": bool(node.get("merged")),
            "merged_at": node.get("mergedAt"),
            "base_ref": node.get("baseRefName"),
            "via": via,
        }
    )


def parse_issue(repo: str, node: Json, collected_at: datetime) -> RawIssue:
    labels: list[LabelEvent] = []
    states: list[StateEvent] = []
    dup_marks: list[DuplicateMark] = []
    renames: list[TitleRename] = []
    prs: dict[int, LinkedPR] = {}

    for pr in _nodes(node.get("closedByPullRequestsReferences")):
        prs[pr["number"]] = _linked_pr(pr, "closing_reference")

    timeline = cast(Json, node.get("timelineItems") or {})
    for ev in _nodes(timeline):
        kind = ev.get("__typename")
        at = ev.get("createdAt")
        if kind in ("LabeledEvent", "UnlabeledEvent"):
            label = cast(Json, ev.get("label") or {})
            labels.append(
                LabelEvent.model_validate(
                    {
                        "at": at,
                        "label": label.get("name", ""),
                        "added": kind == "LabeledEvent",
                        "actor": parse_actor(ev.get("actor")),
                    }
                )
            )
        elif kind in ("ClosedEvent", "ReopenedEvent"):
            dup = ev.get("duplicateOf")
            states.append(
                StateEvent.model_validate(
                    {
                        "at": at,
                        "kind": "closed" if kind == "ClosedEvent" else "reopened",
                        "state_reason": ev.get("stateReason"),
                        "duplicate_of": cast(Json, dup).get("number")
                        if isinstance(dup, dict)
                        else None,
                    }
                )
            )
        elif kind in ("MarkedAsDuplicateEvent", "UnmarkedAsDuplicateEvent"):
            canon = cast(Json, ev.get("canonical") or {})
            is_issue = canon.get("__typename") == "Issue"
            dup_marks.append(
                DuplicateMark.model_validate(
                    {
                        "at": at,
                        "canonical": canon.get("number") if is_issue else None,
                        "canonical_created_at": canon.get("createdAt") if is_issue else None,
                        "unmarked": kind == "UnmarkedAsDuplicateEvent",
                        "actor": parse_actor(ev.get("actor")) if "actor" in ev else None,
                    }
                )
            )
        elif kind == "RenamedTitleEvent":
            renames.append(
                TitleRename.model_validate(
                    {"at": at, "previous": ev["previousTitle"], "current": ev["currentTitle"]}
                )
            )
        elif kind == "CrossReferencedEvent":
            source = cast(Json, ev.get("source") or {})
            if source.get("__typename") == "PullRequest" and source["number"] not in prs:
                prs[source["number"]] = _linked_pr(source, "cross_reference")

    original: BodyRevision | None = None
    if node.get("lastEditedAt") is not None:
        oldest = _nodes(node.get("originalBody"))
        if oldest:
            rev = oldest[0]
            original = BodyRevision.model_validate(
                {
                    "at": rev["editedAt"],
                    "body": rev.get("diff") or "",
                    "editor": parse_actor(rev.get("editor")),
                }
            )

    comments_conn = cast(Json, node.get("comments") or {})
    dup_of = node.get("duplicateOf")
    return RawIssue.model_validate(
        {
            "repo": repo,
            "number": node["number"],
            "url": node.get("url") or "",
            "title": node.get("title") or "",
            "body": node.get("body") or "",
            "created_at": node["createdAt"],
            "closed_at": node.get("closedAt"),
            "state": node.get("state") or "",
            "state_reason": node.get("stateReason"),
            "author": parse_actor(node.get("author")),
            "author_association": node.get("authorAssociation") or "NONE",
            "last_edited_at": node.get("lastEditedAt"),
            "original_body": original,
            "labels_current": tuple(n["name"] for n in _nodes(node.get("labels"))),
            "duplicate_of": _issue_ref(dup_of),
            "label_events": tuple(labels),
            "state_events": tuple(states),
            "duplicate_marks": tuple(dup_marks),
            "title_renames": tuple(renames),
            "comments": tuple(
                Comment.model_validate(
                    {
                        "at": c["createdAt"],
                        "author": parse_actor(c.get("author")),
                        "author_association": c.get("authorAssociation") or "NONE",
                        "body": c.get("body") or "",
                    }
                )
                for c in _nodes(comments_conn)
            ),
            "comments_total": int(comments_conn.get("totalCount") or 0),
            "timeline_total": int(timeline.get("totalCount") or 0),
            "linked_prs": tuple(sorted(prs.values(), key=lambda p: p.number)),
            "collected_at": collected_at,
        }
    )


def _issue_ref(node: Any) -> IssueRef | None:
    if not isinstance(node, dict):
        return None
    ref = cast(Json, node)
    return IssueRef.model_validate({"number": ref["number"], "created_at": ref["createdAt"]})


def parse_pr_files(repo: str, node: Json) -> PRFiles:
    files = cast(Json, node.get("files") or {})
    return PRFiles(
        repo=repo,
        number=node["number"],
        files=tuple(n["path"] for n in _nodes(files)),
        files_total=int(files.get("totalCount") or 0),
    )
