"""Run registry: one folder per run under `runs/<run_id>/`.

A result nobody can trace back to its exact code, config and model versions is an
anecdote, not a measurement. So every run records, at creation time:
  config.yaml    the fully resolved config (after `extends:` merging)
  git_sha        the commit it ran on, with a "-dirty" suffix for uncommitted changes
  manifest.json  run id, timestamps, versions and the config fingerprint
and, when it finishes, cost.json. Predictions, traces and metrics join them from M2 on.
"""

import platform
import re
import subprocess
import sys
from datetime import datetime
from itertools import count
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from triagelab import __version__
from triagelab.config import Config
from triagelab.llm_client import CallStats


class GitInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    sha: str
    dirty: bool

    def label(self) -> str:
        return f"{self.sha}-dirty" if self.dirty else self.sha


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    name: str
    created_at: datetime
    command: str
    git_sha: str
    config_fingerprint: str
    triagelab_version: str
    python_version: str
    platform: str


def git_info(repo_root: Path) -> GitInfo:
    """Current commit and whether the working tree has uncommitted changes."""
    try:
        sha = _git(repo_root, "rev-parse", "HEAD")
        dirty = bool(_git(repo_root, "status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.CalledProcessError):
        return GitInfo(sha="unknown", dirty=False)
    return GitInfo(sha=sha, dirty=dirty)


def _git(repo_root: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=True, timeout=10
    )
    return out.stdout.strip()


def make_run_id(now: datetime, name: str, fingerprint: str) -> str:
    """Sortable, readable and unique enough: `20260929-142501-base-3fa9c1`."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "run"
    return f"{now:%Y%m%d-%H%M%S}-{slug}-{fingerprint[:6]}"


def create_run(
    cfg: Config, *, runs_dir: Path, command: str, now: datetime, git: GitInfo
) -> tuple[Path, RunManifest]:
    fingerprint = cfg.fingerprint()
    run_dir = _claim_run_dir(runs_dir, make_run_id(now, cfg.name, fingerprint))
    manifest = RunManifest(
        run_id=run_dir.name,
        name=cfg.name,
        created_at=now,
        command=command,
        git_sha=git.label(),
        config_fingerprint=fingerprint,
        triagelab_version=__version__,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
    )
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    (run_dir / "git_sha").write_text(git.label() + "\n", encoding="utf-8")
    (run_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return run_dir, manifest


def _claim_run_dir(runs_dir: Path, base_id: str) -> Path:
    """Create a fresh run folder, suffixing `-2`, `-3`... if the id is taken.

    `mkdir(exist_ok=False)` is atomic, so two processes starting in the same second can
    never claim the same folder, and a past run is never overwritten.
    """
    runs_dir.mkdir(parents=True, exist_ok=True)
    for n in count(1):
        candidate = runs_dir / (base_id if n == 1 else f"{base_id}-{n}")
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise AssertionError("unreachable: count() is infinite")


def write_cost(run_dir: Path, stats: CallStats) -> None:
    (run_dir / "cost.json").write_text(stats.model_dump_json(indent=2), encoding="utf-8")


class RunSummary(BaseModel):
    manifest: RunManifest
    cost: CallStats | None


def list_runs(runs_dir: Path) -> list[RunSummary]:
    """All runs, newest first. Folders without a manifest (e.g. crashed mid-create) are skipped."""
    summaries: list[RunSummary] = []
    if not runs_dir.is_dir():
        return summaries
    for run_dir in sorted(runs_dir.iterdir(), reverse=True):
        manifest_file = run_dir / "manifest.json"
        if not manifest_file.is_file():
            continue
        cost_file = run_dir / "cost.json"
        summaries.append(
            RunSummary(
                manifest=RunManifest.model_validate_json(manifest_file.read_text(encoding="utf-8")),
                cost=CallStats.model_validate_json(cost_file.read_text(encoding="utf-8"))
                if cost_file.is_file()
                else None,
            )
        )
    return summaries
