"""Build throwaway skill folders for tests."""

from pathlib import Path


def make_skill(root: Path, name: str, front: str, body: str = "Do the thing.") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(f"---\n{front}\n---\n\n{body}\n", encoding="utf-8")
    return directory
