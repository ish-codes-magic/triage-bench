"""Collect a repo's issues (full history) and the files changed by their fixing PRs.

Resumable: records are appended to JSONL as each batch arrives, and a restart skips
everything already on disk. Adaptive: a batch that keeps failing (GitHub returns 502 for
queries that are too expensive) is split in half and retried, down to single issues.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast

from pydantic import BaseModel

from triagelab.data.github import GraphQLResult, TransientGitHubError
from triagelab.data.ground_truth import fix_prs
from triagelab.data.models import PRFiles, RawIssue
from triagelab.data.parse import parse_issue, parse_pr_files
from triagelab.data.profile import RepoProfile
from triagelab.data.queries import (
    SEARCH_ISSUE_NUMBERS,
    issues_batch_query,
    pr_files_batch_query,
)
from triagelab.data.storage import append_jsonl, read_jsonl, write_json

# GitHub search returns at most 1,000 results per query, so larger date ranges are split.
MAX_SEARCH_RESULTS = 1000

Log = Callable[[str], None]


class QueryClient(Protocol):
    points_used: int

    def query(self, query: str, variables: dict[str, Any] | None = None) -> GraphQLResult: ...


class CollectSummary(BaseModel):
    repo: str
    issues_found: int
    issues_new: int
    issues_missing: int
    prs_new: int
    points_used: int


def raw_paths(data_dir: Path, profile: RepoProfile) -> tuple[Path, Path]:
    base = data_dir / "raw" / profile.slug
    return base / "issues.jsonl", base / "pr_files.jsonl"


def enumerate_issue_numbers(
    client: QueryClient, repo: str, start: date, end: date, log: Log
) -> list[int]:
    """Numbers of all issues (not PRs) created in [start, end], via date-sliced search."""
    numbers: set[int] = set()
    pending = [(start, end)]
    while pending:
        lo, hi = pending.pop()
        query = f"repo:{repo} is:issue created:{lo.isoformat()}..{hi.isoformat()}"
        cursor: str | None = None
        first = True
        while True:
            search = client.query(SEARCH_ISSUE_NUMBERS, {"q": query, "cursor": cursor}).data[
                "search"
            ]
            if first and search["issueCount"] > MAX_SEARCH_RESULTS and lo < hi:
                mid = lo + (hi - lo) // 2
                pending += [(lo, mid), (mid + timedelta(days=1), hi)]
                break
            if first and search["issueCount"] > MAX_SEARCH_RESULTS:
                log(f"warning: {lo} alone has >{MAX_SEARCH_RESULTS} issues; results truncated")
            first = False
            numbers.update(n["number"] for n in search["nodes"] if n)
            if not search["pageInfo"]["hasNextPage"]:
                break
            cursor = search["pageInfo"]["endCursor"]
    return sorted(numbers)


def _owner_name(repo: str) -> dict[str, Any]:
    owner, name = repo.split("/")
    return {"owner": owner, "name": name}


def _repository(result: GraphQLResult) -> dict[str, dict[str, Any] | None]:
    return cast(dict[str, dict[str, Any] | None], result.data.get("repository") or {})


def fetch_issues(
    client: QueryClient, repo: str, numbers: list[int], collected_at: datetime
) -> tuple[list[RawIssue], list[int]]:
    """Fetch one batch; returns (issues, numbers GitHub no longer has, e.g. deleted)."""
    try:
        result = client.query(issues_batch_query(numbers), _owner_name(repo))
    except TransientGitHubError:
        if len(numbers) == 1:
            raise
        half = len(numbers) // 2
        a, missing_a = fetch_issues(client, repo, numbers[:half], collected_at)
        b, missing_b = fetch_issues(client, repo, numbers[half:], collected_at)
        return a + b, missing_a + missing_b
    repository = _repository(result)
    issues: list[RawIssue] = []
    missing: list[int] = []
    for n in numbers:
        node = repository.get(f"i{n}")
        if node is None:
            missing.append(n)
        else:
            issues.append(parse_issue(repo, node, collected_at))
    return issues, missing


def fetch_pr_files(client: QueryClient, repo: str, numbers: list[int]) -> list[PRFiles]:
    result = client.query(pr_files_batch_query(numbers), _owner_name(repo))
    repository = _repository(result)
    return [parse_pr_files(repo, node) for n in numbers if (node := repository.get(f"p{n}"))]


def _chunks(items: list[int], size: int) -> Iterator[list[int]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def collect_repo(
    client: QueryClient,
    profile: RepoProfile,
    data_dir: Path,
    *,
    log: Log,
    batch_size: int = 25,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CollectSummary:
    issues_path, prs_path = raw_paths(data_dir, profile)
    windows = profile.windows

    log(f"enumerating {profile.repo} issues created {windows.history_start}..{windows.eval_end}")
    numbers = enumerate_issue_numbers(
        client, profile.repo, windows.history_start, windows.eval_end, log
    )
    done = {issue.number for issue in read_jsonl(issues_path, RawIssue)}
    todo = [n for n in numbers if n not in done]
    log(f"{len(numbers)} issues found, {len(done)} already on disk, {len(todo)} to fetch")

    new = missing = 0
    for i, batch in enumerate(_chunks(todo, batch_size), start=1):
        issues, gone = fetch_issues(client, profile.repo, batch, now())
        new += append_jsonl(issues_path, issues)
        missing += len(gone)
        if i % 10 == 0 or new + missing == len(todo):
            log(f"  issues {new + missing}/{len(todo)}  (points used: {client.points_used})")

    all_issues = read_jsonl(issues_path, RawIssue)
    wanted = sorted({pr for issue in all_issues for pr in fix_prs(issue, profile)})
    have = {pr.number for pr in read_jsonl(prs_path, PRFiles)}
    pr_todo = [n for n in wanted if n not in have]
    log(f"{len(wanted)} fixing PRs linked, {len(pr_todo)} to fetch files for")
    prs_new = 0
    for batch in _chunks(pr_todo, 50):
        prs_new += append_jsonl(prs_path, fetch_pr_files(client, profile.repo, batch))

    summary = CollectSummary(
        repo=profile.repo,
        issues_found=len(numbers),
        issues_new=new,
        issues_missing=missing,
        prs_new=prs_new,
        points_used=client.points_used,
    )
    write_json(
        issues_path.parent / "manifest.json",
        {
            "last_collected_at": now().isoformat(),
            "windows": profile.windows.model_dump(mode="json"),
            **summary.model_dump(),
        },
    )
    return summary
