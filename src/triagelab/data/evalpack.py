"""The eval pack: the frozen dataset files a CI runner needs to run the agent on dev.

The dataset is built locally from the GitHub API (hours of collection) and is gitignored.
The regression gate (eval.yml) instead downloads this pack, verifies it, and unpacks it
into `data/`:

  snapshots, splits, silver   the three dataset tables, without test-period rows
                              (the test sample and its reserve)
  index/<slug>/               the retrieval corpus and its embeddings, cut at the start of
                              the test period

By default nothing from the test period is packed: no table rows, and no corpus
documents, whose label histories would amount to the test labels. The gate evaluates dev
issues only, and the as_of guard never shows an issue created after the one being
triaged, so the cut loses nothing. Unpacking re-checks both cuts against the repository's
own profile rather than trusting the pack's manifest (AGENTS.md §12.8).

A *test pack* (`include_test=True`) carries everything. It is built only when a frozen
test session is about to run, and only the test-eval workflow unpacks it
(`allow_test=True`).

The source checkout isn't packed: CI downloads the same frozen commit with
`triagelab data checkout`; gold labels are in git.
"""

import hashlib
import io
import json
import tarfile
import tempfile
from datetime import UTC, date, datetime, time
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from triagelab.data.build import dataset_paths
from triagelab.data.profile import RepoProfile
from triagelab.data.storage import read_parquet, write_parquet
from triagelab.retrieval.index import corpus_path, index_dir

PACK_VERSION = 2  # 2: the retrieval corpus is cut at the test period
MANIFEST = "evalpack.json"


class PackManifest(BaseModel):
    version: int
    repo: str
    splits: list[str]  # the splits whose rows are in the tables
    # No corpus document was created on or after this day; None in a test pack.
    history_cutoff: date | None
    files: dict[str, str]  # path relative to data_dir -> sha256


class PackError(Exception):
    pass


def _is_test(split: str) -> bool:
    """The test sample and its reserve pool: every test-period issue."""
    return split.startswith("test")


def _cutoff(profile: RepoProfile) -> datetime:
    return datetime.combine(profile.windows.test_start, time(0), tzinfo=UTC)


def _created(doc: dict[str, object]) -> datetime:
    return datetime.fromisoformat(str(doc["created_at"]))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _stage_index(
    data_dir: Path, profile: RepoProfile, stage: Path, cutoff: datetime | None
) -> None:
    """Copy the index into `stage`, without documents created at or after `cutoff`."""
    src = index_dir(data_dir, profile)
    dst = stage / src.relative_to(data_dir)
    dst.mkdir(parents=True)
    with corpus_path(data_dir, profile).open(encoding="utf-8") as fin:
        lines = [line for line in fin if cutoff is None or _created(json.loads(line)) < cutoff]
    kept = {int(json.loads(line)["number"]) for line in lines}
    (dst / "corpus.jsonl").write_bytes("".join(lines).encode("utf-8"))
    for f in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = f.relative_to(src)
        if rel.as_posix() == "corpus.jsonl":
            continue
        if rel.name == "index.json":
            meta = json.loads(f.read_text(encoding="utf-8"))
            text = json.dumps({**meta, "documents": len(kept)}, indent=2) + "\n"
            (dst / rel).write_bytes(text.encode("utf-8"))
        elif rel.suffix == ".npz":
            with np.load(f) as data:
                numbers = np.asarray(data["numbers"])
                vectors = np.asarray(data["vectors"])
            mask = np.isin(numbers, np.array(sorted(kept), dtype=np.int64))
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            with (dst / rel).open("wb") as fh:
                np.savez(fh, numbers=numbers[mask], vectors=vectors[mask])
        else:  # an unknown file could carry anything: refuse rather than ship it
            raise PackError(f"unexpected file in the index: {rel.as_posix()}")


def build_pack(
    data_dir: Path, profile: RepoProfile, out: Path, *, include_test: bool = False
) -> PackManifest:
    """Write `out` (.tar.gz): the tables, the index and a manifest; without the test
    period unless `include_test`."""
    paths = dataset_paths(data_dir, data_dir, profile)
    assignments = read_parquet(paths.splits)
    kept = {r["number"] for r in assignments if include_test or not _is_test(r["split"])}
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(out, "w:gz") as tar:
        stage = Path(tmp)
        for table in (paths.snapshots, paths.silver, paths.splits):
            rows = [r for r in read_parquet(table) if r["number"] in kept]
            write_parquet(stage / table.relative_to(data_dir), rows)
        _stage_index(data_dir, profile, stage, None if include_test else _cutoff(profile))
        files: dict[str, str] = {}
        for f in sorted(p for p in stage.rglob("*") if p.is_file()):
            rel = f.relative_to(stage).as_posix()
            files[rel] = _sha256(f)
            tar.add(f, arcname=rel)
        manifest = PackManifest(
            version=PACK_VERSION,
            repo=profile.repo,
            splits=sorted({r["split"] for r in assignments if r["number"] in kept}),
            history_cutoff=None if include_test else profile.windows.test_start,
            files=files,
        )
        data = manifest.model_dump_json(indent=2).encode("utf-8")
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return manifest


def extract_pack(
    archive: Path, data_dir: Path, profile: RepoProfile, *, allow_test: bool = False
) -> PackManifest:
    """Unpack into `data_dir` and verify checksums. Unless `allow_test`, re-check the
    test-period cut against `profile` (not against the manifest's own claims)."""
    with tarfile.open(archive) as tar:
        # filter="data" rejects absolute paths, "..", and links out of the tree.
        tar.extractall(data_dir, filter="data")
    manifest = PackManifest.model_validate(
        json.loads((data_dir / MANIFEST).read_text(encoding="utf-8"))
    )
    if manifest.version != PACK_VERSION:
        raise PackError(f"pack version {manifest.version}, expected {PACK_VERSION}")
    bad = [
        rel
        for rel, digest in manifest.files.items()
        if not (data_dir / rel).is_file() or _sha256(data_dir / rel) != digest
    ]
    if bad:
        raise PackError(f"{len(bad)} files are missing or fail their checksum, e.g. {bad[0]}")
    if allow_test:
        return manifest
    splits = {r["split"] for r in read_parquet(dataset_paths(data_dir, data_dir, profile).splits)}
    if any(_is_test(s) for s in splits | set(manifest.splits)):
        raise PackError("this pack contains test-split rows; the gate refuses it")
    cutoff = _cutoff(profile)
    with corpus_path(data_dir, profile).open(encoding="utf-8") as f:
        late = sum(_created(json.loads(line)) >= cutoff for line in f)
    if late:
        raise PackError(f"the corpus has {late} documents from the test period")
    return manifest
