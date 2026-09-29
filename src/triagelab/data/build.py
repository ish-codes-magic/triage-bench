"""Build the dataset: raw JSONL -> snapshots, silver labels, splits (Parquet) + a stats report.

Deterministic: the same raw files and profile always produce the same tables and the
same dataset hash, which every evaluation run records (AGENTS.md §16).
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from triagelab.data.collect import raw_paths
from triagelab.data.ground_truth import SilverTruth, derive
from triagelab.data.models import PRFiles, RawIssue
from triagelab.data.profile import RepoProfile
from triagelab.data.snapshot import SnapshotError, to_snapshot
from triagelab.data.splits import Assignment, assign_splits
from triagelab.data.stats import compute_stats, render_markdown
from triagelab.data.storage import read_jsonl, write_json, write_parquet
from triagelab.hashing import stable_hash


class DatasetPaths(BaseModel):
    snapshots: Path
    silver: Path
    splits: Path
    report_md: Path
    report_json: Path


def dataset_paths(data_dir: Path, reports_dir: Path, profile: RepoProfile) -> DatasetPaths:
    slug = profile.slug
    return DatasetPaths(
        snapshots=data_dir / "snapshots" / f"{slug}.parquet",
        silver=data_dir / "silver" / f"{slug}.parquet",
        splits=data_dir / "splits" / f"{slug}.parquet",
        report_md=reports_dir / "data" / f"{slug}.md",
        report_json=reports_dir / "data" / f"{slug}.json",
    )


def exclusion_reason(issue: RawIssue) -> str | None:
    """Why an issue can't be evaluated, or None if it can."""
    if issue.author.is_bot:
        return "bot_author"  # automated reports aren't triage requests
    try:
        to_snapshot(issue)
    except SnapshotError:
        return "creation_text_unrecoverable"
    return None


def latest_per_number(issues: list[RawIssue]) -> list[RawIssue]:
    """If an issue was collected twice, keep the most recent copy."""
    latest: dict[int, RawIssue] = {}
    for issue in issues:
        if issue.number not in latest or issue.collected_at > latest[issue.number].collected_at:
            latest[issue.number] = issue
    return [latest[n] for n in sorted(latest)]


def _silver_row(t: SilverTruth) -> dict[str, Any]:
    return {
        "number": t.number,
        "labels": [lt.name for lt in t.labels],
        "label_groups": [lt.group for lt in t.labels],
        "label_sources": [lt.source for lt in t.labels],
        "human_triaged": t.human_triaged,
        "duplicate_of": t.duplicate_of,
        "duplicate_source": t.duplicate_source,
        "component": t.component,
        "component_votes": json.dumps(t.component_votes, sort_keys=True),
        "fix_prs": list(t.fix_prs),
        "needs_info": t.needs_info,
        "needs_info_at": t.needs_info_at,
    }


def build_dataset(
    profile: RepoProfile,
    data_dir: Path,
    reports_dir: Path,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DatasetPaths:
    issues_path, prs_path = raw_paths(data_dir, profile)
    issues = latest_per_number(read_jsonl(issues_path, RawIssue))
    if not issues:
        raise FileNotFoundError(f"No raw issues at {issues_path}; run `triagelab data collect`.")
    pr_files = {pr.number: pr for pr in read_jsonl(prs_path, PRFiles)}

    truths = {issue.number: derive(issue, pr_files, profile) for issue in issues}
    exclusions = {i.number: r for i in issues if (r := exclusion_reason(i)) is not None}
    assignments: list[Assignment] = assign_splits(issues, truths, exclusions, profile)

    snapshot_rows = [to_snapshot(i).model_dump() for i in issues if i.number not in exclusions]
    silver_rows = [_silver_row(truths[i.number]) for i in issues]
    split_rows = [a.model_dump() for a in assignments]
    dataset_hash = stable_hash(
        {
            "profile": profile.model_dump(mode="json"),
            "snapshots": [{**r, "created_at": r["created_at"].isoformat()} for r in snapshot_rows],
            "silver": [
                {**r, "needs_info_at": r["needs_info_at"] and r["needs_info_at"].isoformat()}
                for r in silver_rows
            ],
            "splits": split_rows,
        }
    )

    paths = dataset_paths(data_dir, reports_dir, profile)
    write_parquet(paths.snapshots, snapshot_rows)
    write_parquet(paths.silver, silver_rows)
    write_parquet(paths.splits, split_rows)

    stats = compute_stats(
        issues, truths, assignments, profile, built_at=now(), dataset_hash=dataset_hash
    )
    paths.report_md.parent.mkdir(parents=True, exist_ok=True)
    paths.report_md.write_bytes(render_markdown(stats, profile).encode("utf-8"))
    write_json(paths.report_json, stats.model_dump(mode="json"))
    return paths
