import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from triagelab.data.collect import (
    collect_index_history,
    collect_repo,
    enumerate_issue_numbers,
    fetch_issues,
    index_history_path,
    raw_paths,
)
from triagelab.data.github import GraphQLResult, TransientGitHubError
from triagelab.data.models import PRFiles, RawIssue
from triagelab.data.profile import load_profile
from triagelab.data.storage import read_jsonl

from .data_fixtures import COLLECTED_AT, node

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE = load_profile(REPO_ROOT / "configs" / "repos" / "python__cpython.yaml")


class FakeGitHub:
    """Answers search, issue-batch and PR-file queries from an in-memory 'repository'.

    Issue N is created on `base + N days`; issues in `deleted` return null like GitHub does.
    """

    def __init__(
        self, count: int, *, base: date = date(2025, 5, 19), fail_batches_over: int = 0
    ) -> None:
        self.created = {n: base + timedelta(days=n % 400) for n in range(1, count + 1)}
        self.deleted: set[int] = set()
        self.fail_batches_over = fail_batches_over
        self.points_used = 0
        self.issue_batches: list[int] = []

    def query(self, query: str, variables: dict[str, Any] | None = None) -> GraphQLResult:
        self.points_used += 1
        variables = variables or {}
        if "search(" in query:
            lo, hi = re.search(r"created:(\S+)\.\.(\S+)", variables["q"]).groups()  # type: ignore[union-attr]
            hits = sorted(n for n, d in self.created.items() if str(d) >= lo and str(d) <= hi)
            start = int(variables["cursor"] or 0)
            page = hits[start : start + 100]
            more = start + 100 < len(hits)
            search = {
                "issueCount": len(hits),
                "pageInfo": {"hasNextPage": more, "endCursor": str(start + 100)},
                "nodes": [{"number": n} for n in page],
            }
            return GraphQLResult(data={"search": search}, errors=[])
        numbers = [int(n) for n in re.findall(r"[ip](\d+): ", query)]
        if "issue(number" in query:
            self.issue_batches.append(len(numbers))
            if self.fail_batches_over and len(numbers) > self.fail_batches_over:
                raise TransientGitHubError("HTTP 502")
            repo = {
                f"i{n}": None
                if n in self.deleted
                else node(number=n, createdAt=f"{self.created[n]}T00:00:00Z")
                for n in numbers
            }
            return GraphQLResult(data={"repository": repo}, errors=[])
        repo = {
            f"p{n}": {"number": n, "files": {"totalCount": 1, "nodes": [{"path": "Lib/foo.py"}]}}
            for n in numbers
        }
        return GraphQLResult(data={"repository": repo}, errors=[])


def test_search_ranges_over_1000_results_are_split() -> None:
    gh = FakeGitHub(1500)
    numbers = enumerate_issue_numbers(
        gh, "python/cpython", date(2025, 5, 19), date(2026, 8, 18), print
    )
    assert numbers == list(range(1, 1501))


def test_failing_batch_is_halved_until_it_succeeds() -> None:
    gh = FakeGitHub(10, fail_batches_over=2)
    issues, missing = fetch_issues(gh, "python/cpython", list(range(1, 9)), COLLECTED_AT)
    assert [i.number for i in issues] == list(range(1, 9))
    assert missing == []
    assert gh.issue_batches[0] == 8  # tried whole, then halved
    assert max(gh.issue_batches[1:]) <= 4


def test_single_issue_that_keeps_failing_propagates() -> None:
    gh = FakeGitHub(3, fail_batches_over=0)
    gh.fail_batches_over = -1  # every batch, even of one, fails
    with pytest.raises(TransientGitHubError):
        fetch_issues(gh, "python/cpython", [1], COLLECTED_AT)


def test_collect_is_resumable_and_skips_deleted_issues(tmp_path: Path) -> None:
    gh = FakeGitHub(60)
    gh.deleted = {7}
    first = collect_repo(gh, PROFILE, tmp_path, log=lambda _: None, batch_size=25)
    assert first.issues_new == 59
    assert first.issues_missing == 1

    again = collect_repo(gh, PROFILE, tmp_path, log=lambda _: None, batch_size=25)
    assert again.issues_new == 0  # nothing re-fetched
    issues_path, prs_path = raw_paths(tmp_path, PROFILE)
    assert len(read_jsonl(issues_path, RawIssue)) == 59
    # Fixture issues all link the fixture's merged main-branch PR "gh-1000:"... but only
    # issue 1000 matches its own number, so no PR qualifies here.
    assert read_jsonl(prs_path, PRFiles) == []


def test_index_history_is_collected_separately_from_the_dataset(tmp_path: Path) -> None:
    gh = FakeGitHub(60, base=date(2024, 3, 1))  # issues fall before history_start
    found, new, _ = collect_index_history(gh, PROFILE, tmp_path, log=lambda _: None)
    assert new == found > 0
    assert index_history_path(tmp_path, PROFILE).is_file()
    issues_path, _ = raw_paths(tmp_path, PROFILE)
    assert not issues_path.exists()  # the dataset file is untouched
