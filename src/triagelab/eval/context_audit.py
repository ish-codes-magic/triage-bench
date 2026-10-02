"""Audit a finished run for leaks: was every past issue the model saw visible at the time?

The `as_of` guard is unit-tested where it is enforced (the MCP server and the corpus).
This is the other half: a check of what actually happened in a run, from its traces.
Every past issue that reached the model, whether pasted into the prompt (the stuffed
agent's `<similar_issues>` block) or returned by `search_similar_issues` / `get_issue`,
must:

  - not be the issue being triaged;
  - have been created strictly before it;
  - show the labels it had at that moment, re-derived here from the corpus.

It reads traces rather than re-running anything, so it also covers runs made elsewhere
(the test-set runs come from CI).
"""

import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from triagelab.data.models import IssueSnapshot
from triagelab.retrieval.corpus import Corpus, NotVisibleError

ISSUE_TOOLS = ("search_similar_issues", "get_issue")
_BLOCK = re.compile(r"<similar_issues>(.*?)</similar_issues>", re.S)
# One pasted row, as written by `AgentTriager._stuffed`.
_ROW = re.compile(r"^- #(\d+) \[(?:open|closed); labels: ([^\]]*)\]", re.M)
_NUMBER = re.compile(r'^\{"number": (\d+)')


class Shown(BaseModel):
    """A past issue as the model saw it. `labels` is None if the trace cut them off."""

    number: int
    labels: tuple[str, ...] | None


class ContextAudit(BaseModel):
    issues: int = 0  # issues of the run that had any past issue in their context
    shown: int = 0  # past issues that reached the model
    itself: int = 0  # ... that were the issue being triaged
    not_visible: int = 0  # ... created at or after it, or missing from the corpus
    wrong_labels: int = 0  # ... whose labels differ from the as-of replay
    labels_unchecked: int = 0  # ... whose labels the trace had truncated

    @property
    def clean(self) -> bool:
        return self.itself == 0 and self.not_visible == 0 and self.wrong_labels == 0


def pasted(prompt: str) -> list[Shown]:
    """The issues in a prompt's `<similar_issues>` block."""
    found: list[Shown] = []
    for block in _BLOCK.findall(prompt):
        for number, labels in _ROW.findall(block):
            names = tuple(sorted(x.strip() for x in labels.split(",") if x.strip()))
            found.append(Shown(number=int(number), labels=() if names == ("none",) else names))
    return found


def returned(tool: str, output: str) -> list[Shown]:
    """The issues in one tool result. Results end with a budget note, and long ones are cut."""
    try:
        data, _ = json.JSONDecoder().raw_decode(output)
    except json.JSONDecodeError:
        cut = _NUMBER.match(output)  # a truncated get_issue: the number comes first
        return [Shown(number=int(cut.group(1)), labels=None)] if cut else []
    rows: list[dict[str, Any]] = data["results"] if tool == "search_similar_issues" else [data]
    return [Shown(number=int(r["number"]), labels=tuple(sorted(r["labels"]))) for r in rows]


def _shown_per_issue(traces: Path) -> Iterator[tuple[str, Shown]]:
    with traces.open(encoding="utf-8") as f:
        for line in f:
            event = json.loads(line)
            ref = str(event.get("issue_ref", ""))
            if event["event"] == "llm":
                for message in event["new_messages"]:
                    content = message.get("content")
                    if isinstance(content, str):
                        for item in pasted(content):
                            yield ref, item
            elif event["event"] == "tool" and event["name"] in ISSUE_TOOLS:
                # A refused call (e.g. an issue from the future) showed the model nothing.
                shown = [] if event["is_error"] else returned(event["name"], event["output"])
                for item in shown:
                    yield ref, item


def audit_run(traces: Path, issues: Mapping[str, IssueSnapshot], corpus: Corpus) -> ContextAudit:
    """Check every past issue in `traces` against what `corpus` allows at that moment."""
    audit = ContextAudit()
    with_context: set[str] = set()
    for ref, item in _shown_per_issue(traces):
        issue = issues[ref]
        with_context.add(ref)
        audit.shown += 1
        if item.number == issue.number:
            audit.itself += 1
            continue
        try:
            allowed = corpus.get(item.number, issue.created_at)
        except NotVisibleError:
            audit.not_visible += 1
            continue
        if item.labels is None:
            audit.labels_unchecked += 1
        elif item.labels != allowed.labels:
            audit.wrong_labels += 1
    audit.issues = len(with_context)
    return audit


def render(audit: ContextAudit, run_id: str) -> str:
    verdict = "clean" if audit.clean else "LEAK"
    return (
        f"{run_id}: {verdict}. {audit.shown} past issues reached the model across "
        f"{audit.issues} issues: {audit.itself} were the issue itself, {audit.not_visible} "
        f"were not older than it, {audit.wrong_labels} showed labels from later "
        f"({audit.labels_unchecked} had their labels cut off by truncation, unchecked)."
    )
