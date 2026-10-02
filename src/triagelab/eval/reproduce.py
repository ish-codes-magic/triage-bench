"""Reproduce the headline (test-set) tables from what is public: no API key, no collection.

Three inputs, all fixed, and declared in `reports/test-eval/reproduce.yaml`:

  - the dataset: a test pack, a public release asset, checked against a SHA-256 pinned in git;
  - the predictions: the session records committed under `reports/test-eval/`;
  - the adjudicated labels: `data/gold/`, in git.

No model is called. What is reproduced is the *scoring*: the same code path as
`triagelab results`, on the same predictions, compared byte for byte with the committed
table. Re-running the model calls would need the API, and would be a second evaluation
of the test split (ADR-0046).
"""

import hashlib
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel

from triagelab.config import Config
from triagelab.data.build import dataset_paths
from triagelab.data.evalpack import extract_pack
from triagelab.data.profile import load_profile
from triagelab.eval.registry import RunManifest
from triagelab.eval.report import results_document

SPEC = Path("reports/test-eval/reproduce.yaml")

Download = Callable[[str, Path], None]


class Target(BaseModel):
    """One repository's headline table and everything needed to rebuild it."""

    repo: str
    profile: Path
    pack_url: str
    pack_sha256: str
    records: Path  # the committed session records: one folder per config
    expected: Path  # the committed table this must reproduce


class ReproduceSpec(BaseModel):
    targets: list[Target]


class Outcome(BaseModel):
    repo: str
    dataset: str  # "already present" | "downloaded"
    document: str
    expected: Path
    matches: bool


class ReproduceError(Exception):
    pass


def load_spec(path: Path) -> ReproduceSpec:
    return ReproduceSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def http_download(url: str, dest: Path) -> None:
    with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
        response.raise_for_status()
        with dest.open("wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_dataset(target: Target, cfg: Config, download: Download) -> str:
    """Make the repository's dataset tables available under the config's data folder."""
    profile = load_profile(target.profile)
    paths = dataset_paths(cfg.dataset.data_dir, cfg.dataset.reports_dir, profile)
    if all(p.is_file() for p in (paths.snapshots, paths.silver, paths.splits)):
        return "already present"
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "pack.tar.gz"
        download(target.pack_url, archive)
        found = _sha256(archive)
        if found != target.pack_sha256:  # never unpack something we didn't pin
            raise ReproduceError(
                f"{target.repo}: the downloaded pack has SHA-256 {found[:12]}, "
                f"expected {target.pack_sha256[:12]}"
            )
        extract_pack(archive, cfg.dataset.data_dir, profile, allow_test=True)
    return "downloaded"


def restore_runs(records: Path, runs_dir: Path) -> list[str]:
    """Copy the committed records into a run registry, one folder per run id."""
    restored: list[str] = []
    for folder in sorted(p for p in records.iterdir() if (p / "manifest.json").is_file()):
        manifest = RunManifest.model_validate_json(
            (folder / "manifest.json").read_text(encoding="utf-8")
        )
        shutil.copytree(folder, runs_dir / manifest.run_id)
        restored.append(manifest.run_id)
    if not restored:
        raise ReproduceError(f"no run records under {records.as_posix()}")
    return restored


def reproduce(
    spec: ReproduceSpec, cfg: Config, download: Download = http_download
) -> list[Outcome]:
    """Rebuild every target's test-split table on adjudicated labels and compare it."""
    outcomes: list[Outcome] = []
    for target in spec.targets:
        dataset = ensure_dataset(target, cfg, download)
        target_cfg = cfg.model_copy(
            update={"dataset": cfg.dataset.model_copy(update={"profile": target.profile})}
        )
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            restore_runs(target.records, runs_dir)
            document = results_document(target_cfg, runs_dir, "test", "gold")
        expected = target.expected.read_bytes().decode("utf-8").replace("\r\n", "\n")
        outcomes.append(
            Outcome(
                repo=target.repo,
                dataset=dataset,
                document=document,
                expected=target.expected,
                matches=document == expected,
            )
        )
    return outcomes
