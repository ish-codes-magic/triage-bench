"""File formats at the edges of the data layer.

- Raw collections are JSONL: append-only, so a crashed or interrupted collection resumes
  where it stopped, and one bad line never corrupts the rest.
- Derived tables (snapshots, silver labels, splits) are Parquet: typed, compact, and
  readable by DuckDB/pandas in later milestones.
"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel


def append_jsonl(path: Path, records: Iterable[BaseModel]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    # newline="\n": never CRLF, even on Windows, so files are byte-identical across OSes.
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for record in records:
            f.write(record.model_dump_json() + "\n")
            count += 1
    return count


def read_jsonl[M: BaseModel](path: Path, model: type[M]) -> list[M]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [model.model_validate_json(line) for line in f if line.strip()]


def write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # pyarrow-stubs leave some parquet signatures partially unknown; the boundary is tiny.
    pq.write_table(pa.Table.from_pylist(rows), path)  # pyright: ignore[reportUnknownMemberType]


def read_parquet(path: Path) -> list[dict[str, Any]]:
    return pq.read_table(path).to_pylist()  # pyright: ignore[reportUnknownMemberType]


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, indent=2, default=str) + "\n").encode("utf-8"))
