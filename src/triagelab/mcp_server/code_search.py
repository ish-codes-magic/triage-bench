"""Literal code search over the frozen checkout.

Uses ripgrep when installed (fast, respects binary detection) and falls back to a small
pure-Python scan otherwise, so the server and its tests also work where `rg` is missing.
Queries are literal and case-insensitive: model-written regexes fail in surprising ways,
and a triage lookup ("where is PyList_Append defined?") rarely needs one.
"""

import json
import shutil
import subprocess
from fnmatch import fnmatch
from pathlib import Path

from pydantic import BaseModel

_SNIPPET_CHARS = 200
_MAX_FILE_BYTES = 1_000_000
_SKIP_DIRS = frozenset({".git", "__pycache__", ".venv", "node_modules"})


class CodeHit(BaseModel):
    path: str
    line: int
    snippet: str
    component: str | None = None  # filled in by the server from the component map


def _snippet(text: str) -> str:
    text = text.strip()
    return text if len(text) <= _SNIPPET_CHARS else text[:_SNIPPET_CHARS] + " …[truncated]"


class CodeSearcher:
    def __init__(
        self, root: Path, *, ripgrep: str | None = None, use_ripgrep: bool = False
    ) -> None:
        self.root = root
        # Opt-in (ADR-0044): ripgrep also skips hidden and .gitignore'd files, so letting an
        # installed `rg` switch itself on would make search results depend on the machine.
        self._rg = (ripgrep or shutil.which("rg")) if use_ripgrep else None

    def search(
        self, query: str, *, path_glob: str | None = None, max_results: int = 20
    ) -> tuple[list[CodeHit], bool]:
        """Up to `max_results` hits, and whether more were available (truncated)."""
        if not query.strip():
            return [], False
        hits = (
            self._ripgrep(query, path_glob, max_results + 1)
            if self._rg
            else self._scan(query, path_glob, max_results + 1)
        )
        return hits[:max_results], len(hits) > max_results

    def _ripgrep(self, query: str, path_glob: str | None, limit: int) -> list[CodeHit]:
        assert self._rg is not None
        args = [
            self._rg,
            "--json",
            "--fixed-strings",
            "--ignore-case",
            "--max-count",
            "3",
            "--max-filesize",
            "1M",
            "--sort",
            "path",
        ]
        if path_glob:
            args += ["--glob", path_glob]
        args += ["--", query, "."]
        proc = subprocess.run(
            args,
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        hits: list[CodeHit] = []
        for line in proc.stdout.splitlines():
            event = json.loads(line)
            if event.get("type") != "match":
                continue
            data = event["data"]
            path = str(data["path"].get("text", "")).removeprefix("./").replace("\\", "/")
            hits.append(
                CodeHit(
                    path=path,
                    line=int(data["line_number"]),
                    snippet=_snippet(data["lines"].get("text", "")),
                )
            )
            if len(hits) >= limit:
                break
        return hits

    def _scan(self, query: str, path_glob: str | None, limit: int) -> list[CodeHit]:
        needle = query.casefold()
        hits: list[CodeHit] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or _SKIP_DIRS & set(path.relative_to(self.root).parts):
                continue
            rel = path.relative_to(self.root).as_posix()
            if path_glob and not fnmatch(rel, path_glob):
                continue
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            raw = path.read_bytes()
            if b"\0" in raw[:4096]:
                continue  # binary
            per_file = 0
            for number, text in enumerate(raw.decode("utf-8", "replace").splitlines(), start=1):
                if needle in text.casefold():
                    hits.append(CodeHit(path=rel, line=number, snippet=_snippet(text)))
                    per_file += 1
                    if len(hits) >= limit:
                        return hits
                    if per_file >= 3:
                        break
        return hits
