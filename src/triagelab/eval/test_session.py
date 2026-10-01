"""Test-set evaluation as policy in code (AGENTS.md §1.7, §7.4, §12.8).

The test split may be evaluated at most twice in the whole project. An "evaluation" is a
*session*: a file committed to git **before** any test issue is scored, declaring

  - which configs will run (each with a fingerprint that covers a routed system's parts);
  - a hash of the code, skills and configs they run on;
  - the dataset hash.

A test run is refused unless its config is in the session, nothing has changed since the
freeze, that config hasn't already run in the session, and the repository has at most two
sessions. Every run is appended to an audit log that is committed with the results.

Freezing the code (not only the configs) matters: prompts and post-processing live in
`src/`, so a config fingerprint alone would let a prompt change through.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from triagelab.config import Config, load_config
from triagelab.hashing import stable_hash

SESSION_LIMIT = 2
SESSIONS_DIR = Path("reports/test-eval")
# What a test run depends on besides the data. Line endings are normalised, so a Windows
# checkout and a Linux runner hash the same commit identically.
FROZEN_TREES = ("src/triagelab", "skills", "configs")


class TestSetLockedError(RuntimeError):
    __test__ = False  # not a pytest test class, despite the name


class FrozenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str  # repository-relative, POSIX
    name: str
    fingerprint: str


class TestSession(BaseModel):
    __test__ = False

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    repo: str
    number: int
    created_at: datetime
    code_hash: str
    dataset_hash: str
    configs: list[FrozenConfig]
    note: str = ""


def code_hash(root: Path) -> str:
    """One hash over every file the runs depend on (paths and contents, sorted)."""
    digest = hashlib.sha256()
    for tree in FROZEN_TREES:
        for f in sorted(p for p in (root / tree).rglob("*") if p.is_file()):
            if "__pycache__" in f.parts:
                continue
            content = f.read_bytes().replace(b"\r\n", b"\n")
            digest.update(f.relative_to(root).as_posix().encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def deep_fingerprint(cfg: Config) -> str:
    """The config's fingerprint, extended over the configs a routed system is built from."""
    routed = cfg.system.routed if cfg.system else None
    if routed is None:
        return cfg.fingerprint()
    parts = {
        role: deep_fingerprint(load_config(path))
        for role, path in (
            ("base", routed.base),
            ("type", routed.type),
            ("component", routed.component),
        )
        if path is not None
    }
    return stable_hash({"self": cfg.fingerprint(), "parts": parts})[:16]


def session_dir(slug: str, root: Path = Path()) -> Path:
    return root / SESSIONS_DIR / slug


def existing_sessions(slug: str, root: Path = Path()) -> list[Path]:
    return sorted(session_dir(slug, root).glob("session-*.yaml"))


def freeze(
    *,
    repo: str,
    slug: str,
    config_paths: list[Path],
    dataset_hash: str,
    note: str = "",
    root: Path = Path(),
    code_root: Path = Path(),
    now: datetime | None = None,
) -> Path:
    """Write the next session file for `repo` under `root`; refuses a third.

    `code_root` is where the frozen trees and the config files live (the repository).
    """
    number = len(existing_sessions(slug, root)) + 1
    if number > SESSION_LIMIT:
        raise TestSetLockedError(
            f"{repo} already has {SESSION_LIMIT} test sessions; the test split is spent."
        )
    configs: list[FrozenConfig] = []
    for path in config_paths:
        cfg = load_config(code_root / path)
        configs.append(
            FrozenConfig(path=path.as_posix(), name=cfg.name, fingerprint=deep_fingerprint(cfg))
        )
    session = TestSession(
        repo=repo,
        number=number,
        created_at=now or datetime.now(UTC),
        code_hash=code_hash(code_root),
        dataset_hash=dataset_hash,
        configs=configs,
        note=note,
    )
    out = session_dir(slug, root) / f"session-{number}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(session.model_dump(mode="json"), sort_keys=False)
    out.write_bytes(text.encode("utf-8"))
    return out


def load_session(path: Path) -> TestSession:
    return TestSession.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _audit_path(session_path: Path) -> Path:
    return session_path.parent / "audit.jsonl"


def audit(session_path: Path) -> list[dict[str, str]]:
    path = _audit_path(session_path)
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def record(session_path: Path, session: TestSession, cfg: Config, run_id: str, event: str) -> None:
    """Append one audit line: a run of a session's config started or completed."""
    entry = {
        "session": str(session.number),
        "config": cfg.name,
        "run_id": run_id,
        "event": event,
        "at": datetime.now(UTC).isoformat(),
    }
    with _audit_path(session_path).open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry) + "\n")


def authorize(
    session_path: Path,
    cfg: Config,
    slug: str,
    *,
    dataset_hash: str,
    root: Path = Path(),
    code_root: Path = Path(),
) -> TestSession:
    """Raise TestSetLockedError unless this config may run on test under this session."""
    resolved = session_path.resolve()
    if resolved not in {p.resolve() for p in existing_sessions(slug, root)}:
        raise TestSetLockedError(
            f"{session_path} is not a session of this repository "
            f"(expected {session_dir(slug).as_posix()}/session-N.yaml)."
        )
    if len(existing_sessions(slug, root)) > SESSION_LIMIT:
        raise TestSetLockedError(f"More than {SESSION_LIMIT} test sessions exist; refusing.")
    session = load_session(session_path)
    frozen = {c.name: c for c in session.configs}.get(cfg.name)
    if frozen is None:
        raise TestSetLockedError(f"Config {cfg.name!r} is not part of session {session.number}.")
    if deep_fingerprint(cfg) != frozen.fingerprint:
        raise TestSetLockedError(f"Config {cfg.name!r} changed after the session was frozen.")
    if code_hash(code_root) != session.code_hash:
        raise TestSetLockedError(
            "The code, skills or configs changed after the session was frozen "
            f"(session {session.number}, frozen {session.created_at:%Y-%m-%d})."
        )
    if dataset_hash != session.dataset_hash:
        raise TestSetLockedError("The dataset differs from the one the session was frozen on.")
    done = [
        e
        for e in audit(session_path)
        if e["config"] == cfg.name
        and e["session"] == str(session.number)
        and e["event"] == "completed"
    ]
    if done:
        raise TestSetLockedError(
            f"Config {cfg.name!r} was already evaluated in session {session.number} "
            f"(run {done[0]['run_id']})."
        )
    return session
