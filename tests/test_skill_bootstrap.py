"""The auto-skill bootstrap: train-only sources, and output that passes the spec checks."""

import json
from pathlib import Path

from triagelab.config import LLMConfig
from triagelab.data.profile import load_profile
from triagelab.eval.dataset import family_vocabulary, load_split
from triagelab.skills.bootstrap import collect_sources, generate, write_skill
from triagelab.skills.loader import parse_skill

from .fakes import FAKE_MODEL, FakeBackend, make_client
from .smoke_dataset import PROFILE_PATH, write_smoke_dataset

PROFILE = load_profile(PROFILE_PATH)


def test_sources_use_the_train_split_only(tmp_path: Path) -> None:
    write_smoke_dataset(tmp_path)
    train = load_split(tmp_path / "data", PROFILE, "train")
    dev = load_split(tmp_path / "data", PROFILE, "dev")
    sources = collect_sources(
        PROFILE, train, family_vocabulary(train, 1), {"type-bug": "A bug"}, "Read the guide."
    )
    assert "Read the guide." in sources
    assert "`type-bug` (" in sources
    assert ": A bug." in sources
    train_titles = {e.snapshot.title for e in train}
    dev_only = [e.snapshot.title for e in dev if e.snapshot.title not in train_titles]
    assert dev_only  # the smoke data has dev titles unseen in train
    assert not any(title in sources for title in dev_only)


def test_generated_skill_passes_the_spec(tmp_path: Path) -> None:
    reply = {
        "description": 'Triage "demo" issues: labels, components, duplicates. Use for any issue.',
        "body": "1. Read references/label_taxonomy.md.\n2. Read references/component_map.md.",
        "label_taxonomy": "# Labels\n- type-bug: broken behaviour",
        "component_map": "# Components\n- stdlib: Lib/",
    }
    client = make_client(tmp_path, FakeBackend(text=json.dumps(reply)))
    skill = generate(client, LLMConfig(model=FAKE_MODEL), "o/r", "sources")
    directory = tmp_path / "triage-demo-auto"
    write_skill(skill, directory, sources_note="test")
    parsed = parse_skill(directory)
    assert parsed.problems == ()
    assert parsed.metadata["generated"].startswith("true")
    assert parsed.resources() == ["references/component_map.md", "references/label_taxonomy.md"]
    for f in directory.rglob("*.md"):
        assert b"\r\n" not in f.read_bytes(), f  # committed files: LF on every OS
