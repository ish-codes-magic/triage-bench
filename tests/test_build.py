"""End-to-end build on synthetic raw data: raw JSONL -> Parquet tables + report."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from triagelab.data.build import build_dataset, exclusion_reason
from triagelab.data.collect import raw_paths
from triagelab.data.models import Actor, PRFiles, RawIssue
from triagelab.data.profile import load_profile
from triagelab.data.storage import append_jsonl, read_parquet

from .data_fixtures import raw

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE = load_profile(REPO_ROOT / "configs" / "repos" / "python__cpython.yaml")
FIXED_NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


def _issues() -> list[RawIssue]:
    base = raw()
    w = PROFILE.windows
    start = datetime.combine(w.history_start, datetime.min.time(), tzinfo=UTC)
    dev = datetime.combine(w.eval_start, datetime.min.time(), tzinfo=UTC)
    test = datetime.combine(w.test_start, datetime.min.time(), tzinfo=UTC)
    out: list[RawIssue] = []
    for i, created in enumerate([start] * 5 + [dev] * 5 + [test] * 5, start=1):
        at = created + timedelta(hours=i)
        issue = base.model_copy(update={"number": i, "created_at": at, "last_edited_at": None})
        out.append(issue)
    out[3] = out[3].model_copy(update={"author": Actor(login="some-bot", is_bot=True)})
    return out


@pytest.fixture
def built(tmp_path: Path) -> tuple[Path, Path]:
    issues_path, prs_path = raw_paths(tmp_path / "data", PROFILE)
    append_jsonl(issues_path, _issues())
    append_jsonl(
        prs_path, [PRFiles(repo=PROFILE.repo, number=1002, files=("Lib/foo.py",), files_total=1)]
    )
    build_dataset(PROFILE, tmp_path / "data", tmp_path / "reports", now=lambda: FIXED_NOW)
    return tmp_path / "data", tmp_path / "reports"


def test_build_writes_all_tables_and_the_report(built: tuple[Path, Path]) -> None:
    data, reports = built
    slug = PROFILE.slug
    splits = {r["number"]: r["split"] for r in read_parquet(data / "splits" / f"{slug}.parquet")}
    assert splits[4] == "excluded"  # bot author
    assert {splits[n] for n in (1, 2, 3, 5)} == {"train"}
    assert {splits[n] for n in range(6, 11)} == {"dev"}  # pool of 5 < dev_size: all sampled
    assert {splits[n] for n in range(11, 16)} == {"test"}
    snapshots = read_parquet(data / "snapshots" / f"{slug}.parquet")
    assert 4 not in {r["number"] for r in snapshots}
    assert set(snapshots[0]) == {
        "issue_ref",
        "repo",
        "number",
        "title",
        "body",
        "author_association",
        "created_at",
    }
    assert "Dataset report: python/cpython" in (reports / "data" / f"{slug}.md").read_text(
        encoding="utf-8"
    )


def test_build_is_deterministic(tmp_path: Path) -> None:
    hashes: list[str] = []
    for run in ("a", "b"):
        root = tmp_path / run
        issues_path, _ = raw_paths(root / "data", PROFILE)
        append_jsonl(issues_path, _issues())
        build_dataset(PROFILE, root / "data", root / "reports", now=lambda: FIXED_NOW)
        report = (root / "reports" / "data" / f"{PROFILE.slug}.json").read_text(encoding="utf-8")
        hashes.append(report.split('"dataset_hash": "')[1].split('"')[0])
    assert hashes[0] == hashes[1]


def test_exclusion_reasons() -> None:
    assert exclusion_reason(raw()) is None
    assert exclusion_reason(raw().model_copy(update={"original_body": None})) == (
        "creation_text_unrecoverable"
    )
