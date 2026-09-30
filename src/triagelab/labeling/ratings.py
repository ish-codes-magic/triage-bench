"""Human ratings of triage comments: the reference the LLM judge is calibrated against.

The item set is sampled once and committed (`data/gold/judge_items.jsonl`), so later
runs can't change what was rated. Each dev issue appears once, with the comment of one
system picked at random, and the rater never sees which system wrote it.

Items are split into judge-dev (used to iterate on the judge prompt) and judge-test
(reported once) by a stable hash of the item id, so the split needs no stored state
and never changes when items are added.
"""

import random
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from triagelab.data.storage import append_jsonl, read_jsonl
from triagelab.hashing import stable_hash
from triagelab.triage import TriageResult

JudgeSplit = Literal["judge-dev", "judge-test"]


class Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    question: str
    levels: dict[int, str]


class Rubric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    scale: list[int]
    criteria: list[Criterion]

    @model_validator(mode="after")
    def _levels_cover_the_scale(self) -> "Rubric":
        for c in self.criteria:
            if sorted(c.levels) != sorted(self.scale):
                raise ValueError(f"criterion {c.name!r} must describe every level {self.scale}")
        return self


def load_rubric(path: Path) -> Rubric:
    return Rubric.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class RatingItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str
    issue_ref: str
    number: int
    system: str  # config name of the run that wrote the comment (hidden from the rater)
    run_id: str
    comment: str


class Rating(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str
    scores: dict[str, int]  # criterion -> level
    rubric_version: int
    annotator: str
    seconds: float
    rated_at: datetime


def items_path(data_dir: Path) -> Path:
    return data_dir / "gold" / "judge_items.jsonl"


def ratings_path(data_dir: Path) -> Path:
    return data_dir / "gold" / "judge_ratings.jsonl"


def sample_items(runs: dict[str, Path], *, seed: int = 0) -> list[RatingItem]:
    """One item per issue that every run commented on, the system chosen at random."""
    predictions = {
        name: {p.issue_ref: p for p in read_jsonl(run / "predictions.jsonl", TriageResult)}
        for name, run in runs.items()
    }
    names = list(runs)
    common: set[str] = set(predictions[names[0]]) if names else set()
    for name in names[1:]:
        common &= set(predictions[name])
    shared = sorted(common, key=lambda ref: int(ref.rsplit("#", 1)[1]))
    rng = random.Random(seed)
    items: list[RatingItem] = []
    for ref in shared:
        options = [name for name in runs if predictions[name][ref].triage_comment.strip()]
        if not options:
            continue
        name = rng.choice(sorted(options))
        items.append(
            RatingItem(
                item_id=f"{ref}:{name}",
                issue_ref=ref,
                number=int(ref.rsplit("#", 1)[1]),
                system=name,
                run_id=runs[name].name,
                comment=predictions[name][ref].triage_comment.strip(),
            )
        )
    return items


def judge_split(item_id: str) -> JudgeSplit:
    """Stable 50/50 assignment by hash, independent of which other items exist."""
    return "judge-dev" if int(stable_hash(item_id)[:8], 16) % 2 == 0 else "judge-test"


class RatingStore:
    def __init__(self, data_dir: Path) -> None:
        self.items_file = items_path(data_dir)
        self.ratings_file = ratings_path(data_dir)

    def items(self) -> list[RatingItem]:
        return read_jsonl(self.items_file, RatingItem)

    def write_items(self, items: list[RatingItem]) -> None:
        if self.items_file.exists():
            raise FileExistsError(f"{self.items_file} exists: the rated set is frozen")
        self.items_file.parent.mkdir(parents=True, exist_ok=True)
        append_jsonl(self.items_file, items)

    def ratings(self) -> dict[str, Rating]:
        return {r.item_id: r for r in read_jsonl(self.ratings_file, Rating)}

    def save(self, rating: Rating) -> None:
        self.ratings_file.parent.mkdir(parents=True, exist_ok=True)
        append_jsonl(self.ratings_file, [rating])
