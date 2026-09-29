"""A frozen source checkout for code search (AGENTS.md §7.2).

Code search must not see fixes made after the issues it helps triage. We freeze the tree
at the last commit on the main branch before the evaluation window opens. That is an
approximation, documented in the dataset card: an issue filed in August sees May's code.
Train-window issues see code from *after* they were filed, but they're never evaluated.
"""

import json
import shutil
import tarfile
import tempfile
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, cast

import httpx
from pydantic import BaseModel

from triagelab.data.profile import RepoProfile

API = "https://api.github.com"


class CheckoutInfo(BaseModel):
    repo: str
    commit: str
    committed_at: datetime
    fetched_at: datetime


def checkout_dir(data_dir: Path, profile: RepoProfile) -> Path:
    return data_dir / "checkouts" / profile.slug


def resolve_freeze_commit(
    http: httpx.Client, repo: str, branch: str, before: date
) -> tuple[str, datetime]:
    """The last commit on `branch` strictly before `before` (00:00 UTC)."""
    until = datetime.combine(before, time.min, tzinfo=UTC).isoformat()
    response = http.get(
        f"{API}/repos/{repo}/commits", params={"sha": branch, "until": until, "per_page": 1}
    )
    response.raise_for_status()
    commit = cast(list[dict[str, Any]], response.json())[0]
    return commit["sha"], datetime.fromisoformat(commit["commit"]["committer"]["date"])


def download_checkout(profile: RepoProfile, data_dir: Path, token: str) -> CheckoutInfo:
    dest = checkout_dir(data_dir, profile)
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "triagelab"}
    with httpx.Client(headers=headers, timeout=120, follow_redirects=True) as http:
        sha, committed_at = resolve_freeze_commit(
            http, profile.repo, profile.main_branch, profile.windows.eval_start
        )
        info_path = dest / "checkout.json"
        if info_path.exists():
            existing = CheckoutInfo.model_validate_json(info_path.read_text(encoding="utf-8"))
            if existing.commit == sha:
                return existing  # already frozen at the right commit
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "src.tar.gz"
            with http.stream("GET", f"{API}/repos/{profile.repo}/tarball/{sha}") as response:
                response.raise_for_status()
                with archive.open("wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
            extract_to = Path(tmp) / "x"
            with tarfile.open(archive) as tar:
                # filter="data" rejects absolute paths, "..", links outside the tree, etc.
                tar.extractall(extract_to, filter="data")
            (top,) = list(extract_to.iterdir())  # GitHub wraps the tree in one folder
            if dest.exists():
                shutil.rmtree(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(top), str(dest))
    info = CheckoutInfo(
        repo=profile.repo, commit=sha, committed_at=committed_at, fetched_at=datetime.now(UTC)
    )
    info_path.write_text(
        json.dumps(info.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )
    return info
