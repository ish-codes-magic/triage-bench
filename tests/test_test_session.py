"""Test sessions: what gets frozen, and every way a test run is refused."""

from pathlib import Path

import pytest
import yaml

from triagelab.config import Config, load_config
from triagelab.data.profile import load_profile
from triagelab.eval import test_session
from triagelab.eval.test_session import (
    TestSetLockedError,
    audit,
    code_hash,
    deep_fingerprint,
    freeze,
    load_session,
)

from .test_runner import PROFILE_PATH, _config, _run, workspace  # noqa: F401

SLUG = load_profile(PROFILE_PATH).slug


def on_disk(ws: Path, cfg: Config) -> Path:
    """Sessions freeze config *files*; write the in-memory test config out as one."""
    path = ws / f"{cfg.name}.yaml"
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    return path


def frozen(ws: Path, *cfgs: Config) -> Path:
    report = ws / "reports" / "data" / f"{SLUG}.json"
    import json

    dataset_hash = json.loads(report.read_text(encoding="utf-8"))["dataset_hash"]
    return freeze(
        repo="python/cpython", slug=SLUG, config_paths=[on_disk(ws, c) for c in cfgs],
        dataset_hash=dataset_hash, root=ws,
    )  # fmt: skip


def test_a_frozen_config_runs_once(workspace: Path) -> None:  # noqa: F811
    cfg = _config(workspace, "majority", name="final")
    session = frozen(workspace, cfg)
    assert load_session(session).number == 1
    cfg = load_config(workspace / "final.yaml")
    outcome = _run(cfg, split="test", session=session, sessions_root=workspace)
    assert outcome.scorecard is not None
    events = [(e["config"], e["event"]) for e in audit(session)]
    assert events == [("final", "started"), ("final", "completed")]
    with pytest.raises(TestSetLockedError, match="already evaluated"):
        _run(cfg, split="test", session=session, sessions_root=workspace)


def test_a_test_run_is_never_partial(workspace: Path) -> None:  # noqa: F811
    cfg = _config(workspace, "majority", name="final")
    session = frozen(workspace, cfg)
    with pytest.raises(TestSetLockedError, match="whole test split"):
        _run(load_config(workspace / "final.yaml"), split="test", session=session,
             sessions_root=workspace, limit=2)  # fmt: skip


def test_only_frozen_unchanged_configs_run(workspace: Path) -> None:  # noqa: F811
    cfg = _config(workspace, "majority", name="final")
    session = frozen(workspace, cfg)
    other = _config(workspace, "majority", name="other")
    with pytest.raises(TestSetLockedError, match="not part of session"):
        _run(other, split="test", session=session, sessions_root=workspace)
    edited = cfg.model_copy(update={"eval": cfg.eval.model_copy(update={"seed": 7})})
    with pytest.raises(TestSetLockedError, match="changed after the session was frozen"):
        _run(edited, split="test", session=session, sessions_root=workspace)


def test_changed_code_or_data_is_refused(
    workspace: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _config(workspace, "majority", name="final")
    session = frozen(workspace, cfg)
    cfg = load_config(workspace / "final.yaml")
    monkeypatch.setattr(test_session, "code_hash", lambda _root: "something-else")
    with pytest.raises(TestSetLockedError, match="code, skills or configs changed"):
        _run(cfg, split="test", session=session, sessions_root=workspace)
    monkeypatch.undo()
    report = workspace / "reports" / "data" / f"{SLUG}.json"
    report.write_text(
        report.read_text("utf-8").replace('"dataset_hash": "', '"dataset_hash": "x'), "utf-8"
    )
    with pytest.raises(TestSetLockedError, match="dataset differs"):
        _run(cfg, split="test", session=session, sessions_root=workspace)


def test_a_third_session_is_refused(workspace: Path) -> None:  # noqa: F811
    cfg = _config(workspace, "majority", name="final")
    assert frozen(workspace, cfg).name == "session-1.yaml"
    assert frozen(workspace, cfg).name == "session-2.yaml"
    with pytest.raises(TestSetLockedError, match="already has 2 test sessions"):
        frozen(workspace, cfg)


def test_a_session_file_from_elsewhere_is_refused(workspace: Path, tmp_path: Path) -> None:  # noqa: F811
    cfg = _config(workspace, "majority", name="final")
    session = frozen(workspace, cfg)
    stray = tmp_path / "session-1.yaml"
    stray.write_bytes(session.read_bytes())
    with pytest.raises(TestSetLockedError, match="not a session of this repository"):
        _run(load_config(workspace / "final.yaml"), split="test", session=stray,
             sessions_root=workspace)  # fmt: skip


def test_code_hash_ignores_line_endings_and_sees_edits(tmp_path: Path) -> None:
    for tree in ("src/triagelab", "skills", "configs"):
        (tmp_path / tree).mkdir(parents=True)
    f = tmp_path / "src" / "triagelab" / "a.py"
    f.write_bytes(b"x = 1\ny = 2\n")
    unix = code_hash(tmp_path)
    f.write_bytes(b"x = 1\r\ny = 2\r\n")
    assert code_hash(tmp_path) == unix  # a Windows checkout hashes like a Linux one
    f.write_bytes(b"x = 1\ny = 3\n")
    assert code_hash(tmp_path) != unix


def test_a_routed_fingerprint_covers_its_parts(workspace: Path) -> None:  # noqa: F811
    base = on_disk(workspace, _config(workspace, "majority", name="part"))
    top = _config(workspace, "majority", name="top")
    assert top.system is not None
    routed = top.model_copy(
        update={
            "system": top.system.model_validate({"kind": "routed", "routed": {"base": str(base)}})
        }
    )
    before = deep_fingerprint(routed)
    part = load_config(base)
    edited = part.model_copy(update={"eval": part.eval.model_copy(update={"seed": 9})})
    base.write_text(yaml.safe_dump(edited.model_dump(mode="json")), encoding="utf-8")
    assert deep_fingerprint(routed) != before  # the top config's own bytes did not change


def test_a_ci_evaluation_is_imported_next_to_its_session(workspace: Path, tmp_path: Path) -> None:  # noqa: F811
    from triagelab.eval.test_session import import_runs

    cfg = _config(workspace, "majority", name="final")
    session = frozen(workspace, cfg)
    outcome = _run(
        load_config(workspace / "final.yaml"), split="test", session=session,
        sessions_root=workspace,
    )  # fmt: skip
    artifact = workspace / "runs"  # what CI uploads
    registry = tmp_path / "registry"
    registry.mkdir()
    imported = import_runs(session, artifact, registry)
    assert imported == {"final": outcome.run_id}
    assert (registry / outcome.run_id / "predictions.jsonl").is_file()
    records = session.with_suffix("") / "final"
    assert {p.name for p in records.iterdir()} >= {
        "predictions.jsonl",
        "config.yaml",
        "metrics.json",
    }
    assert b"\r\n" not in (records / "manifest.json").read_bytes()

    other = frozen(workspace, _config(workspace, "majority", name="never-ran"))
    with pytest.raises(TestSetLockedError, match="no test run for"):
        import_runs(other, artifact, registry)
