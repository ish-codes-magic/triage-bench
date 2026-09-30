"""A person's failure tags: the open coding that the failure taxonomy is built from (§12.6).

Workflow: tag about 50 failures with free-form codes (the seed categories are offered as a
starting vocabulary), consolidate the codes into 6-10 categories in
docs/FAILURE_TAXONOMY.md, then validate an LLM tagger against these tags before letting
it label the remaining failures.
"""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from triagelab.data.storage import append_jsonl, read_jsonl

# AGENTS.md §12.6 seed categories: a starting vocabulary, not the final taxonomy.
SEED_CODES = (
    "retrieval miss",
    "correct evidence ignored",
    "skill not loaded",
    "skill misapplied",
    "wrong component map",
    "stopped too early",
    "hallucinated file or label",
    "budget exhaustion",
    "output validation failure",
    "ground-truth noise",
)


class FailureTag(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    issue_ref: str
    tasks: list[str]
    codes: list[str]
    note: str = ""
    annotator: str
    tagged_at: datetime


def tags_path(data_dir: Path) -> Path:
    return data_dir / "gold" / "failure_tags.jsonl"


class FailureTagStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = tags_path(data_dir)

    def load(self) -> dict[tuple[str, str], FailureTag]:
        return {(t.run_id, t.issue_ref): t for t in read_jsonl(self.path, FailureTag)}

    def save(self, tag: FailureTag) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        append_jsonl(self.path, [tag])

    def codes_in_use(self) -> list[str]:
        """Seed codes first, then every custom code already used, so vocabulary converges."""
        used = {c for t in self.load().values() for c in t.codes}
        return [*SEED_CODES, *sorted(used - set(SEED_CODES))]
