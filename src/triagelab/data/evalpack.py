"""The eval pack: the frozen dataset files a CI runner needs to run the agent on dev.

The dataset is built locally from the GitHub API (hours of collection) and is gitignored.
The regression gate (eval.yml) instead downloads this pack, verifies it, and unpacks it
into `data/`:

  snapshots, splits, silver   the three dataset tables, without test-period rows
                              (the test sample and its reserve)
  index/<slug>/               the retrieval corpus and its embeddings (as_of-guarded history)

Test rows are dropped at packing time, so no workflow that uses the pack can reach the
test split (AGENTS.md §12.8). The source checkout isn't packed: CI downloads the same frozen
commit with `triagelab data checkout`, and the gold labels are already in git.
"""

import hashlib
import io
import json
import tarfile
import tempfile
from pathlib import Path

from pydantic import BaseModel

from triagelab.data.build import dataset_paths
from triagelab.data.profile import RepoProfile
from triagelab.data.storage import read_parquet, write_parquet
from triagelab.retrieval.index import index_dir

PACK_VERSION = 1
MANIFEST = "evalpack.json"


class PackManifest(BaseModel):
    version: int
    repo: str
    splits: list[str]  # the splits whose rows are in the tables
    files: dict[str, str]  # path relative to data_dir -> sha256


def _is_test(split: str) -> bool:
    """The test sample and its reserve pool: every test-period issue."""
    return split.startswith("test")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_pack(data_dir: Path, profile: RepoProfile, out: Path) -> PackManifest:
    """Write `out` (.tar.gz): the tables without test rows, the index, and a manifest."""
    paths = dataset_paths(data_dir, data_dir, profile)
    assignments = read_parquet(paths.splits)
    kept = {r["number"] for r in assignments if not _is_test(r["split"])}
    files: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(out, "w:gz") as tar:
        for table in (paths.snapshots, paths.silver, paths.splits):
            rel = table.relative_to(data_dir).as_posix()
            staged = Path(tmp) / rel
            write_parquet(staged, [r for r in read_parquet(table) if r["number"] in kept])
            files[rel] = _sha256(staged)
            tar.add(staged, arcname=rel)
        for f in sorted(p for p in index_dir(data_dir, profile).rglob("*") if p.is_file()):
            rel = f.relative_to(data_dir).as_posix()
            files[rel] = _sha256(f)
            tar.add(f, arcname=rel)
        splits = sorted({r["split"] for r in assignments if r["number"] in kept})
        manifest = PackManifest(version=PACK_VERSION, repo=profile.repo, splits=splits, files=files)
        data = manifest.model_dump_json(indent=2).encode("utf-8")
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return manifest


class PackError(Exception):
    pass


def extract_pack(archive: Path, data_dir: Path) -> PackManifest:
    """Unpack into `data_dir` and verify every file against the manifest."""
    with tarfile.open(archive) as tar:
        # filter="data" rejects absolute paths, "..", and links out of the tree.
        tar.extractall(data_dir, filter="data")
    manifest = PackManifest.model_validate(
        json.loads((data_dir / MANIFEST).read_text(encoding="utf-8"))
    )
    if manifest.version != PACK_VERSION:
        raise PackError(f"pack version {manifest.version}, expected {PACK_VERSION}")
    if any(_is_test(s) for s in manifest.splits):
        raise PackError("this pack contains test-split rows; the gate refuses it")
    bad = [
        rel
        for rel, digest in manifest.files.items()
        if not (data_dir / rel).is_file() or _sha256(data_dir / rel) != digest
    ]
    if bad:
        raise PackError(f"{len(bad)} files are missing or fail their checksum, e.g. {bad[0]}")
    return manifest
