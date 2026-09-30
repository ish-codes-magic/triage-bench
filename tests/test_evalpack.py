"""The eval pack: no test-period rows, verified on unpacking, refused if tampered."""

import json
import tarfile
from pathlib import Path

import pytest

from triagelab.data.evalpack import MANIFEST, PackError, build_pack, extract_pack
from triagelab.data.profile import load_profile
from triagelab.data.storage import read_parquet
from triagelab.eval.dataset import load_split

from .test_runner import PROFILE_PATH, workspace  # noqa: F401


def test_the_eval_pack_has_no_test_rows_and_verifies(workspace: Path) -> None:  # noqa: F811
    profile = load_profile(PROFILE_PATH)
    pack = workspace / "pack.tar.gz"
    manifest = build_pack(workspace / "data", profile, pack)
    assert "test" not in manifest.splits

    out = workspace / "unpacked"
    extract_pack(pack, out)
    splits = {r["split"] for r in read_parquet(out / "splits" / f"{profile.slug}.parquet")}
    assert "test" not in splits
    assert len(load_split(out, profile, "dev")) == len(
        load_split(workspace / "data", profile, "dev")
    )

    # A tampered file fails its checksum.
    (out / "silver" / f"{profile.slug}.parquet").write_bytes(b"tampered")
    with tarfile.open(workspace / "evil.tar.gz", "w:gz") as tar:
        tar.add(out / "silver", arcname="silver")
        tar.add(out / MANIFEST, arcname=MANIFEST)
    with pytest.raises(PackError, match="checksum"):
        extract_pack(workspace / "evil.tar.gz", workspace / "evil")


def test_a_pack_claiming_test_rows_is_refused(tmp_path: Path) -> None:
    (tmp_path / MANIFEST).write_text(
        json.dumps({"version": 1, "repo": "o/r", "splits": ["dev", "test_reserve"], "files": {}}),
        encoding="utf-8",
    )
    with tarfile.open(tmp_path / "p.tar.gz", "w:gz") as tar:
        tar.add(tmp_path / MANIFEST, arcname=MANIFEST)
    with pytest.raises(PackError, match="test-split"):
        extract_pack(tmp_path / "p.tar.gz", tmp_path / "out")
