"""CODEOWNERS lookup, following GitHub's documented rules.

Source: docs.github.com, "About code owners" (checked 2026-09-29):
  - gitignore-style patterns, except that `!` negation, `[ ]` ranges and `\\#` escaping
    are not supported;
  - the *last* matching line wins;
  - a line with a pattern but no owners means "no owner";
  - the file is looked up in `.github/`, then the root, then `docs/`, and the first found wins.
"""

import re
from dataclasses import dataclass
from pathlib import Path

LOCATIONS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


def _glob_to_regex(glob: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return "".join(out)


@dataclass(frozen=True)
class Rule:
    pattern: str
    owners: tuple[str, ...]
    regex: re.Pattern[str]


def compile_rule(pattern: str, owners: tuple[str, ...]) -> Rule:
    body = pattern.strip()
    directory_only = body.endswith("/")
    body = body.rstrip("/")
    # gitignore: a slash at the start or in the middle anchors the pattern to the root.
    anchored = body.startswith("/") or "/" in body
    body = body.lstrip("/")
    rx = _glob_to_regex(body)
    prefix = "^" if anchored else "^(?:.*/)?"
    # A match on a directory covers everything under it. "docs/*" is the documented
    # exception: its "*" stops at a slash, so it covers direct children only.
    suffix = "/.*$" if directory_only else "(?:/.*)?$"
    if body.endswith("/*"):
        suffix = "$"
    return Rule(pattern=pattern, owners=owners, regex=re.compile(prefix + rx + suffix))


class CodeOwners:
    def __init__(self, rules: list[Rule]) -> None:
        self._rules = rules

    @classmethod
    def parse(cls, text: str) -> "CodeOwners":
        rules: list[Rule] = []
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip() if not raw.lstrip().startswith("#") else ""
            if not line:
                continue
            pattern, *owners = line.split()
            rules.append(compile_rule(pattern, tuple(owners)))
        return cls(rules)

    @classmethod
    def from_checkout(cls, root: Path) -> "CodeOwners":
        for location in LOCATIONS:
            path = root / location
            if path.is_file():
                return cls.parse(path.read_text(encoding="utf-8"))
        return cls([])

    def owners_for(self, path: str) -> tuple[tuple[str, ...], str | None]:
        """(owners, matching pattern) for a repo-relative path; the last match wins."""
        clean = path.strip().lstrip("/")
        for rule in reversed(self._rules):
            if rule.regex.match(clean):
                return rule.owners, rule.pattern
        return (), None
