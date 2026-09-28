from datetime import UTC, datetime
from pathlib import Path

import yaml

from triagelab.config import load_config
from triagelab.eval.registry import (
    GitInfo,
    create_run,
    git_info,
    list_runs,
    make_run_id,
    write_cost,
)
from triagelab.llm_client import CallStats

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 29, 14, 25, 1, tzinfo=UTC)
GIT = GitInfo(sha="abc123", dirty=True)


def test_run_id_is_sortable_and_slugged() -> None:
    assert (
        make_run_id(NOW, "E2: Skills / Repo!", "3fa9c1d2")
        == "20260929-142501-e2-skills-repo-3fa9c1"
    )


def test_create_run_records_config_git_and_manifest(tmp_path: Path) -> None:
    cfg = load_config(REPO_ROOT / "configs" / "base.yaml")
    run_dir, manifest = create_run(cfg, runs_dir=tmp_path, command="pytest", now=NOW, git=GIT)
    assert run_dir.name == manifest.run_id
    assert (run_dir / "git_sha").read_text(encoding="utf-8").strip() == "abc123-dirty"
    assert yaml.safe_load((run_dir / "config.yaml").read_text(encoding="utf-8"))["name"] == "base"
    assert manifest.config_fingerprint == cfg.fingerprint()


def test_same_second_runs_get_distinct_ids_and_never_overwrite(tmp_path: Path) -> None:
    cfg = load_config(REPO_ROOT / "configs" / "base.yaml")
    first, m1 = create_run(cfg, runs_dir=tmp_path, command="a", now=NOW, git=GIT)
    second, m2 = create_run(cfg, runs_dir=tmp_path, command="b", now=NOW, git=GIT)
    assert m2.run_id == f"{m1.run_id}-2"
    assert first != second
    assert '"command": "a"' in (first / "manifest.json").read_text(encoding="utf-8")


def test_list_runs_newest_first_with_cost(tmp_path: Path) -> None:
    cfg = load_config(REPO_ROOT / "configs" / "base.yaml")
    older, _ = create_run(cfg, runs_dir=tmp_path, command="a", now=NOW, git=GIT)
    newer, _ = create_run(cfg, runs_dir=tmp_path, command="b", now=NOW.replace(minute=30), git=GIT)
    write_cost(newer, CallStats(calls=1, cost_usd=0.01))
    (tmp_path / "half-created").mkdir()  # no manifest: must be skipped

    runs = list_runs(tmp_path)
    assert [r.manifest.run_id for r in runs] == [newer.name, older.name]
    assert runs[0].cost is not None
    assert runs[0].cost.cost_usd == 0.01
    assert runs[1].cost is None


def test_git_info_reads_this_repo() -> None:
    info = git_info(REPO_ROOT)
    assert info.sha == "unknown" or len(info.sha) == 40
