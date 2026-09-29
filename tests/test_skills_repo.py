"""Our own skills follow the Agent Skills spec strictly and agree with the repo profile."""

import re
from pathlib import Path

import pytest

from triagelab.data.profile import load_profile
from triagelab.skills.loader import SKILL_FILE, parse_skill

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "skills"
SKILL_DIRS = sorted(p for p in SKILLS.iterdir() if (p / SKILL_FILE).is_file())


def test_there_are_skills_to_check() -> None:
    assert {p.name for p in SKILL_DIRS} >= {"generic-triage", "triage-cpython"}


@pytest.mark.parametrize("directory", SKILL_DIRS, ids=lambda p: p.name)
def test_skill_meets_the_spec(directory: Path) -> None:
    skill = parse_skill(directory)
    assert skill.problems == ()
    lines = (directory / SKILL_FILE).read_text(encoding="utf-8").count("\n")
    assert lines < 500  # the spec's size guidance for SKILL.md
    for resource in skill.resources():
        assert resource.count("/") <= 1  # references stay one level deep


@pytest.mark.parametrize("directory", SKILL_DIRS, ids=lambda p: p.name)
def test_body_and_files_point_at_each_other(directory: Path) -> None:
    skill = parse_skill(directory)
    for resource in skill.resources():
        assert resource in skill.body or resource.startswith("assets/"), (
            f"{resource} is never pointed to, so the model can't know to read it"
        )
    for mentioned in re.findall(r"`((?:references|scripts|assets)/[^`]+)`", skill.body):
        assert mentioned in skill.resources(), f"the body points to missing {mentioned}"


def test_cpython_component_map_matches_the_profile() -> None:
    profile = load_profile(REPO_ROOT / "configs" / "repos" / "python__cpython.yaml")
    text = (SKILLS / "triage-cpython" / "references" / "component_map.md").read_text("utf-8")
    for component in profile.components:
        row = next(line for line in text.splitlines() if line.startswith(f"| `{component.name}`"))
        for prefix in component.prefixes:
            assert f"`{prefix}`" in row, f"{prefix} missing from the {component.name} row"
