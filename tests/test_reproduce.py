"""`triagelab reproduce`: the headline table rebuilt from a pack, committed records and gold."""

import hashlib
import shutil
from pathlib import Path

import pytest

from triagelab.config import Config, load_config
from triagelab.data.build import dataset_paths
from triagelab.data.evalpack import build_pack
from triagelab.data.profile import load_profile
from triagelab.eval.dataset import load_split
from triagelab.eval.report import results_document
from triagelab.eval.reproduce import (
    Download,
    ReproduceError,
    ReproduceSpec,
    Target,
    ensure_dataset,
    reproduce,
    restore_runs,
)
from triagelab.eval.test_session import import_runs
from triagelab.labeling.gold import Decision, GoldRecord, GoldStore, gold_path

from .test_evalpack import _with_index
from .test_runner import FIXED_NOW, PROFILE_PATH, _config, _run, workspace  # noqa: F401
from .test_test_session import frozen

PROFILE = load_profile(PROFILE_PATH)


def evaluated(ws: Path) -> tuple[Config, Target]:
    """A workspace after a test evaluation: gold labels, a pack, records, a committed table."""
    data = ws / "data"
    store = GoldStore(gold_path(data, PROFILE))
    decision = Decision(labels=["type-bug"], component="stdlib")
    for e in load_split(data, PROFILE, "test"):
        store.save(
            GoldRecord(
                issue_ref=e.snapshot.issue_ref, number=e.snapshot.number, split="test",
                blind=decision, final=decision, annotator="t", blind_seconds=1.0,
                updated_at=FIXED_NOW,
            )
        )  # fmt: skip
    cfg = _config(ws, "majority", name="final")
    session = frozen(ws, cfg)
    _run(load_config(ws / "final.yaml"), split="test", session=session, sessions_root=ws)
    import_runs(session, ws / "runs", ws / "registry")
    expected = ws / "expected.md"
    expected.write_bytes(results_document(cfg, ws / "runs", "test", "gold").encode("utf-8"))
    _with_index(data, PROFILE)
    pack = ws / "pack.tar.gz"
    build_pack(data, PROFILE, pack, include_test=True)
    target = Target(
        repo=PROFILE.repo, profile=PROFILE_PATH, pack_url=pack.as_uri(),
        pack_sha256=hashlib.sha256(pack.read_bytes()).hexdigest(),
        records=session.with_suffix(""), expected=expected,
    )  # fmt: skip
    return cfg, target


def copy_pack(source: Path, calls: list[str]) -> Download:
    """A stand-in for the network: 'downloads' the local pack and records each call."""

    def download(url: str, dest: Path) -> None:
        calls.append(url)
        shutil.copyfile(source, dest)

    return download


def drop_tables(cfg: Config) -> None:
    paths = dataset_paths(cfg.dataset.data_dir, cfg.dataset.reports_dir, PROFILE)
    for table in (paths.snapshots, paths.silver, paths.splits):
        table.unlink()


def test_the_table_is_rebuilt_from_a_downloaded_pack(workspace: Path) -> None:  # noqa: F811
    cfg, target = evaluated(workspace)
    drop_tables(cfg)  # a fresh clone: gold and records are in git, the dataset is not
    calls: list[str] = []
    download = copy_pack(workspace / "pack.tar.gz", calls)
    (outcome,) = reproduce(ReproduceSpec(targets=[target]), cfg, download)
    assert outcome.dataset == "downloaded"
    assert outcome.matches
    assert "| final | majority |" in outcome.document

    (again,) = reproduce(ReproduceSpec(targets=[target]), cfg, download)
    assert again.dataset == "already present"
    assert len(calls) == 1  # the second time needs no network


def test_a_changed_table_is_reported(workspace: Path) -> None:  # noqa: F811
    cfg, target = evaluated(workspace)
    edited = target.expected.read_text(encoding="utf-8").replace("| final |", "| better |")
    target.expected.write_text(edited, encoding="utf-8")
    (outcome,) = reproduce(ReproduceSpec(targets=[target]), cfg, copy_pack(workspace, []))
    assert not outcome.matches


def test_a_pack_with_the_wrong_checksum_is_never_unpacked(workspace: Path) -> None:  # noqa: F811
    cfg, target = evaluated(workspace)
    drop_tables(cfg)
    wrong = target.model_copy(update={"pack_sha256": "0" * 64})
    with pytest.raises(ReproduceError, match="SHA-256"):
        ensure_dataset(wrong, cfg, copy_pack(workspace / "pack.tar.gz", []))
    paths = dataset_paths(cfg.dataset.data_dir, cfg.dataset.reports_dir, PROFILE)
    assert not paths.splits.exists()


def test_records_are_restored_under_their_run_ids(workspace: Path, tmp_path: Path) -> None:  # noqa: F811
    _, target = evaluated(workspace)
    registry = tmp_path / "restored"
    registry.mkdir()
    (run_id,) = restore_runs(target.records, registry)
    assert (registry / run_id / "predictions.jsonl").is_file()
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ReproduceError, match="no run records"):
        restore_runs(empty, registry)
