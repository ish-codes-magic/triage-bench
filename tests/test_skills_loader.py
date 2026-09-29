"""Skill parsing, spec validation and the three disclosure levels."""

from pathlib import Path

import pytest

from triagelab.skills.loader import MAX_FILE_CHARS, SkillError, SkillSet, name_problems, parse_skill


def make_skill(root: Path, name: str, front: str, body: str = "Do the thing.") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(f"---\n{front}\n---\n\n{body}\n", encoding="utf-8")
    return directory


@pytest.fixture
def triage_skill(tmp_path: Path) -> Path:
    d = make_skill(
        tmp_path,
        "triage-demo",
        "name: triage-demo\ndescription: Triage demo issues. Use for labels & <components>.",
        body="# Steps\n1. Read references/taxonomy.md.",
    )
    (d / "references").mkdir()
    (d / "references" / "taxonomy.md").write_text("type-bug: broken behaviour\n", encoding="utf-8")
    return d


def test_parses_front_matter_body_and_resources(triage_skill: Path) -> None:
    skill = parse_skill(triage_skill)
    assert skill.name == "triage-demo"
    assert skill.body.startswith("# Steps")
    assert skill.resources() == ["references/taxonomy.md"]
    assert skill.problems == ()


def test_catalog_shows_only_escaped_names_and_descriptions(triage_skill: Path) -> None:
    catalog = SkillSet([parse_skill(triage_skill)]).catalog()
    assert "<name>triage-demo</name>" in catalog
    assert "labels &amp; &lt;components&gt;" in catalog
    assert "# Steps" not in catalog  # level 1 never includes the body


def test_no_skills_means_no_catalog_at_all() -> None:
    assert SkillSet([]).catalog() == ""


def test_activation_gives_the_body_and_lists_files_without_reading_them(
    triage_skill: Path,
) -> None:
    text = SkillSet([parse_skill(triage_skill)]).activate("triage-demo")
    assert '<skill_content name="triage-demo">' in text
    assert "# Steps" in text
    assert "<file>references/taxonomy.md</file>" in text
    assert "broken behaviour" not in text  # level 3 content stays on disk


def test_read_file_is_confined_to_the_skill_folder(triage_skill: Path) -> None:
    skills = SkillSet([parse_skill(triage_skill)])
    assert "broken behaviour" in skills.read_file("triage-demo", "references/taxonomy.md")
    (triage_skill.parent / "secret.txt").write_text("nope", encoding="utf-8")
    for bad in ("../secret.txt", str(triage_skill.parent / "secret.txt"), ""):
        with pytest.raises(SkillError):
            skills.read_file("triage-demo", bad)
    with pytest.raises(SkillError, match=r"references/taxonomy\.md"):  # lists what exists
        skills.read_file("triage-demo", "references/missing.md")


def test_long_files_are_truncated_with_a_marker(triage_skill: Path) -> None:
    (triage_skill / "references" / "big.md").write_text("x" * (MAX_FILE_CHARS + 10), "utf-8")
    text = parse_skill(triage_skill).read("references/big.md")
    assert text.endswith(f"[... truncated at {MAX_FILE_CHARS} characters]")


def test_unknown_skill_is_an_error(triage_skill: Path) -> None:
    with pytest.raises(SkillError, match="triage-demo"):
        SkillSet([parse_skill(triage_skill)]).activate("nope")


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("triage-cpython", True),
        ("a", True),
        ("Triage", False),
        ("-triage", False),
        ("triage-", False),
        ("triage--cpython", False),
        ("triage_cpython", False),
        ("x" * 65, False),
    ],
)
def test_name_rules_follow_the_spec(name: str, ok: bool) -> None:
    assert (name_problems(name, name) == []) is ok


def test_lenient_loading_warns_but_skips_only_unusable_skills(tmp_path: Path) -> None:
    mismatched = make_skill(tmp_path, "folder", "name: other\ndescription: d\nversion: 2")
    skill = parse_skill(mismatched)
    assert any("does not match" in p for p in skill.problems)
    assert any("unexpected front matter fields: version" in p for p in skill.problems)
    with pytest.raises(SkillError, match="description"):
        parse_skill(make_skill(tmp_path, "nodesc", "name: nodesc"))
    with pytest.raises(SkillError, match="unreadable"):
        parse_skill(make_skill(tmp_path, "badyaml", "name: [unclosed"))
    (tmp_path / "nofront").mkdir()
    (tmp_path / "nofront" / "SKILL.md").write_text("just text", encoding="utf-8")
    with pytest.raises(SkillError, match="front matter"):
        parse_skill(tmp_path / "nofront")
