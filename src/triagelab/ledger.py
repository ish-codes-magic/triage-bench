"""Append-only record of real money spent.

The all-time budget has to survive across runs and processes, so it cannot live in
memory. Each non-cached model call appends one JSON line; total spend is the sum of the
file. Append-only JSONL means a crash can lose at most the line being written.
"""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class SpendEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    at: datetime
    run_id: str
    model: str
    resolved_model: str | None
    tokens_in: int
    tokens_out: int
    cached_tokens_in: int
    cost_usd: float
    # LiteLLM's own estimate, kept only to spot drift between its price map and ours.
    litellm_cost_usd: float | None = None


class SpendLedger:
    def __init__(self, path: Path) -> None:
        self._path = path

    def record(self, entry: SpendEntry) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

    def entries(self) -> list[SpendEntry]:
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()
        return [SpendEntry.model_validate_json(line) for line in lines if line.strip()]

    def total_usd(self) -> float:
        return sum(e.cost_usd for e in self.entries())
