"""Agent Skills with progressive disclosure, implemented by hand (AGENTS.md §9).

A skill is a folder holding `SKILL.md` (YAML front matter, then instructions) plus
optional `references/`, `scripts/` and `assets/` (agentskills.io specification,
checked 2026-09-30). Disclosure has three levels:

  1. catalog: only each skill's `name` and `description` sit in the system prompt;
  2. `load_skill(name)`: the SKILL.md body enters the context, with a list (not the
     contents) of the skill's files;
  3. `read_skill_file(name, path)`: one of those files, on demand.

Parsing is lenient, as the spec's client guide recommends: a skill whose front matter is
unreadable or has no description is skipped, and naming problems become warnings. Our
own skills are held to the strict rules by a test (`problems` must be empty).
"""

import html
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict

SKILL_FILE = "SKILL.md"
ALLOWED_FIELDS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)
# 1-64 chars of a-z, 0-9 and single hyphens, neither leading nor trailing.
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)
MAX_FILE_CHARS = 20_000


class SkillError(ValueError):
    """A skill (or one of its files) that can't be used."""


class Skill(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    root: Path
    body: str
    metadata: dict[str, str] = {}
    problems: tuple[str, ...] = ()  # spec violations, reported but not fatal

    def resources(self) -> list[str]:
        """Every file except SKILL.md, as POSIX paths relative to the skill root."""
        return sorted(
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file() and p.name != SKILL_FILE
        )

    def read(self, relative: str) -> str:
        """One file of this skill. Paths may not leave the skill folder."""
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise SkillError(f"{relative!r} is not a path inside skill {self.name!r}")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_file():
            files = ", ".join(self.resources())
            raise SkillError(f"skill {self.name!r} has no file {relative!r}; files: {files}")
        text = path.read_text(encoding="utf-8")
        if len(text) > MAX_FILE_CHARS:
            return text[:MAX_FILE_CHARS] + f"\n[... truncated at {MAX_FILE_CHARS} characters]"
        return text


def name_problems(name: str, directory: str) -> list[str]:
    problems: list[str] = []
    if not 1 <= len(name) <= 64:
        problems.append(f"name must be 1-64 characters, got {len(name)}")
    if not _NAME.match(name):
        problems.append(f"name {name!r} must be lowercase a-z, 0-9 and single inner hyphens")
    if name != directory:
        problems.append(f"name {name!r} does not match its directory {directory!r}")
    return problems


def parse_skill(directory: Path) -> Skill:
    """Read one skill folder; raises SkillError if it can't be used at all."""
    skill_md = directory / SKILL_FILE
    if not skill_md.is_file():
        raise SkillError(f"{directory} has no {SKILL_FILE}")
    match = _FRONT_MATTER.match(skill_md.read_text(encoding="utf-8"))
    if match is None:
        raise SkillError(f"{skill_md} does not start with a --- front matter block")
    try:
        loaded: Any = yaml.safe_load(match.group(1))
    except yaml.YAMLError as err:
        raise SkillError(f"{skill_md}: unreadable front matter ({err})") from err
    if not isinstance(loaded, dict):
        raise SkillError(f"{skill_md}: front matter must be a mapping")
    meta = cast(dict[str, Any], loaded)
    description = str(meta.get("description") or "").strip()
    if not description:
        raise SkillError(f"{skill_md}: a description is required")

    name = str(meta.get("name") or directory.name)
    problems = name_problems(name, directory.name)
    if len(description) > 1024:
        problems.append(f"description must be at most 1024 characters, got {len(description)}")
    if unknown := sorted(set(meta) - ALLOWED_FIELDS):
        problems.append(f"unexpected front matter fields: {', '.join(unknown)}")
    raw_metadata: Any = meta.get("metadata") or {}
    if not isinstance(raw_metadata, dict):
        problems.append("metadata must be a mapping of strings")
        raw_metadata = {}
    metadata = {str(k): str(v) for k, v in cast(dict[Any, Any], raw_metadata).items()}
    return Skill(
        name=name,
        description=description,
        root=directory,
        body=match.group(2).strip(),
        metadata=metadata,
        problems=tuple(problems),
    )


class SkillSet:
    """The skills one agent may use, selected by name from a skills directory."""

    def __init__(self, skills: Sequence[Skill]) -> None:
        self.skills = {s.name: s for s in skills}

    @classmethod
    def from_dir(cls, root: Path, names: Sequence[str]) -> "SkillSet":
        """Load exactly the named skills; an unknown or unusable one is a config error."""
        return cls([parse_skill(root / name) for name in names])

    def __len__(self) -> int:
        return len(self.skills)

    def get(self, name: str) -> Skill:
        if name not in self.skills:
            raise SkillError(f"no skill named {name!r}; available: {', '.join(self.skills)}")
        return self.skills[name]

    def catalog(self) -> str:
        """Level 1: names and descriptions only. Empty when there are no skills, so a
        no-skills ablation sees no trace of the mechanism."""
        if not self.skills:
            return ""
        entries = "\n".join(
            "  <skill>\n"
            f"    <name>{html.escape(s.name)}</name>\n"
            f"    <description>{html.escape(s.description)}</description>\n"
            "  </skill>"
            for s in self.skills.values()
        )
        return f"<available_skills>\n{entries}\n</available_skills>"

    def activate(self, name: str) -> str:
        """Level 2: the instructions, and the names (not contents) of the skill's files."""
        skill = self.get(name)
        files = "\n".join(f"  <file>{html.escape(f)}</file>" for f in skill.resources())
        resources = f"\n<skill_resources>\n{files}\n</skill_resources>" if files else ""
        return (
            f'<skill_content name="{html.escape(name)}">\n{skill.body}{resources}\n</skill_content>'
        )

    def read_file(self, name: str, path: str) -> str:
        """Level 3: one file, on demand."""
        return self.get(name).read(path)
