"""Load a dataset split as evaluation examples: (creation-time snapshot, gold, weight)."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from triagelab.data.build import dataset_paths
from triagelab.data.models import IssueSnapshot
from triagelab.data.profile import RepoProfile
from triagelab.data.splits import Split
from triagelab.data.storage import read_parquet


class Gold(BaseModel):
    """Silver (and, from M5, gold) answers for one issue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    labels: frozenset[str]
    label_groups: dict[str, str]  # label -> type | area | family
    human_triaged: bool
    duplicate_of: int | None
    component: str | None
    needs_info: bool


class EvalExample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot: IssueSnapshot
    gold: Gold
    split: Split
    weight: float  # post-stratification weight; 1.0 outside the dev/test samples


def load_split(
    data_dir: Path, profile: RepoProfile, splits: set[Split] | Split
) -> list[EvalExample]:
    wanted = {splits} if isinstance(splits, str) else splits
    paths = dataset_paths(data_dir, Path(), profile)
    assignments = {r["number"]: r for r in read_parquet(paths.splits) if r["split"] in wanted}
    silver = {r["number"]: r for r in read_parquet(paths.silver) if r["number"] in assignments}
    examples: list[EvalExample] = []
    for row in read_parquet(paths.snapshots):
        number = row["number"]
        if number not in assignments:
            continue
        s = silver[number]
        examples.append(
            EvalExample(
                snapshot=IssueSnapshot.model_validate(row),
                gold=Gold(
                    labels=frozenset(s["labels"]),
                    label_groups=dict(zip(s["labels"], s["label_groups"], strict=True)),
                    human_triaged=s["human_triaged"],
                    duplicate_of=s["duplicate_of"],
                    component=s["component"],
                    needs_info=s["needs_info"],
                ),
                split=assignments[number]["split"],
                weight=assignments[number]["weight"] or 1.0,
            )
        )
    return sorted(examples, key=lambda e: e.snapshot.number)


def load_history(data_dir: Path, profile: RepoProfile) -> list[IssueSnapshot]:
    """Every eligible issue's creation-time snapshot: the pool retrieval may search.

    Callers must still filter by time (only issues created before the query issue).
    """
    paths = dataset_paths(data_dir, Path(), profile)
    return sorted(
        (IssueSnapshot.model_validate(r) for r in read_parquet(paths.snapshots)),
        key=lambda s: s.created_at,
    )


def created_before(history: list[IssueSnapshot], when: datetime) -> list[IssueSnapshot]:
    return [h for h in history if h.created_at < when]
