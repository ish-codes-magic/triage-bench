"""The eval pack: nothing from the test period, verified on unpacking, refused if tampered."""

import json
import tarfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from triagelab.data.evalpack import MANIFEST, PackError, build_pack, extract_pack
from triagelab.data.profile import RepoProfile, load_profile
from triagelab.data.storage import read_parquet
from triagelab.eval.dataset import load_split
from triagelab.retrieval.index import build_corpus_from_raw, corpus_path, index_dir

from .test_runner import PROFILE_PATH, workspace  # noqa: F401

PROFILE = load_profile(PROFILE_PATH)


def _with_index(data_dir: Path, profile: RepoProfile) -> list[int]:
    """A real corpus over the workspace issues, plus one embedding chunk for all of them."""
    corpus = build_corpus_from_raw(data_dir, profile)
    corpus.save(corpus_path(data_dir, profile))
    numbers = [i.number for i in corpus.issues]
    emb = index_dir(data_dir, profile) / "emb-test"
    emb.mkdir(parents=True)
    with (emb / "chunk-00000.npz").open("wb") as fh:
        np.savez(fh, numbers=np.array(numbers, dtype=np.int64), vectors=np.ones((len(numbers), 4)))
    (index_dir(data_dir, profile) / "index.json").write_text(
        json.dumps({"documents": len(numbers), "encoder": "test"}), encoding="utf-8"
    )
    return numbers


def _late(path: Path, profile: RepoProfile) -> int:
    cutoff = datetime.fromisoformat(f"{profile.windows.test_start}T00:00:00+00:00")
    lines = path.read_text(encoding="utf-8").splitlines()
    return sum(datetime.fromisoformat(json.loads(x)["created_at"]) >= cutoff for x in lines)


def test_the_pack_holds_nothing_from_the_test_period(workspace: Path) -> None:  # noqa: F811
    data = workspace / "data"
    numbers = _with_index(data, PROFILE)
    assert _late(corpus_path(data, PROFILE), PROFILE) > 0  # the source has test-period docs
    manifest = build_pack(data, PROFILE, workspace / "pack.tar.gz")
    assert not any(s.startswith("test") for s in manifest.splits)
    assert manifest.history_cutoff == PROFILE.windows.test_start

    out = workspace / "unpacked"
    extract_pack(workspace / "pack.tar.gz", out, PROFILE)
    splits = {r["split"] for r in read_parquet(out / "splits" / f"{PROFILE.slug}.parquet")}
    assert not any(s.startswith("test") for s in splits)
    assert _late(corpus_path(out, PROFILE), PROFILE) == 0
    kept = len(corpus_path(out, PROFILE).read_text(encoding="utf-8").splitlines())
    with np.load(index_dir(out, PROFILE) / "emb-test" / "chunk-00000.npz") as chunk:
        assert len(chunk["numbers"]) == kept < len(numbers)  # vectors cut the same way
    meta = json.loads((index_dir(out, PROFILE) / "index.json").read_text(encoding="utf-8"))
    assert meta["documents"] == kept
    assert len(load_split(out, PROFILE, "dev")) == len(load_split(data, PROFILE, "dev"))


def test_a_tampered_pack_fails_its_checksum(workspace: Path) -> None:  # noqa: F811
    data = workspace / "data"
    _with_index(data, PROFILE)
    build_pack(data, PROFILE, workspace / "pack.tar.gz")
    out = workspace / "unpacked"
    extract_pack(workspace / "pack.tar.gz", out, PROFILE)
    (out / "silver" / f"{PROFILE.slug}.parquet").write_bytes(b"tampered")
    with tarfile.open(workspace / "evil.tar.gz", "w:gz") as tar:
        tar.add(out / "silver", arcname="silver")
        tar.add(out / MANIFEST, arcname=MANIFEST)
    with pytest.raises(PackError, match="checksum"):
        extract_pack(workspace / "evil.tar.gz", workspace / "evil", PROFILE)


def test_unpacking_rechecks_the_corpus_instead_of_trusting_the_manifest(
    workspace: Path,  # noqa: F811
) -> None:
    data = workspace / "data"
    _with_index(data, PROFILE)
    build_pack(data, PROFILE, workspace / "pack.tar.gz")
    out = workspace / "unpacked"
    extract_pack(workspace / "pack.tar.gz", out, PROFILE)
    # Smuggle the full corpus (with test-period docs) in, with a manifest that vouches for it.
    full = corpus_path(data, PROFILE).read_bytes()
    corpus_path(out, PROFILE).write_bytes(full)
    manifest = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    rel = corpus_path(out, PROFILE).relative_to(out).as_posix()
    from triagelab.data.evalpack import _sha256  # pyright: ignore[reportPrivateUsage]

    manifest["files"][rel] = _sha256(corpus_path(out, PROFILE))
    (out / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    with tarfile.open(workspace / "evil.tar.gz", "w:gz") as tar:
        for f in out.rglob("*"):
            if f.is_file():
                tar.add(f, arcname=f.relative_to(out).as_posix())
    with pytest.raises(PackError, match="test period"):
        extract_pack(workspace / "evil.tar.gz", workspace / "evil", PROFILE)


def test_an_unexpected_index_file_is_refused(workspace: Path) -> None:  # noqa: F811
    data = workspace / "data"
    _with_index(data, PROFILE)
    (index_dir(data, PROFILE) / "notes.txt").write_text("anything", encoding="utf-8")
    with pytest.raises(PackError, match="unexpected file"):
        build_pack(data, PROFILE, workspace / "pack.tar.gz")
