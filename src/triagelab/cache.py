"""Content-addressed disk cache for model responses.

One JSON file per entry at `<dir>/<key[:2]>/<key>.json`. Plain files (rather than SQLite)
are easy to inspect, diff, and later commit as CI cassettes. The two-character fan-out
directory keeps any single folder from holding tens of thousands of files.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast


class DiskCache:
    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def _path(self, key: str) -> Path:
        return self._dir / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            # A corrupt entry is treated as a miss; the next successful call overwrites it.
            return None
        return cast(dict[str, Any], raw) if isinstance(raw, dict) else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a crash mid-write can never leave a half-written entry
        # that a later run would read as a valid cached response.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            # newline="\n": the same bytes on every OS, so cassettes recorded on Windows
            # match the files CI checks out.
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(value, f, ensure_ascii=False, indent=1)
            Path(tmp).replace(path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
