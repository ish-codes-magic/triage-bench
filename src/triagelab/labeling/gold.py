"""Gold labels: one person's labels for dev/test issues, blind first, then adjudicated.

Each issue gets two passes (AGENTS.md §7.5):
  1. blind: only the issue as it was opened, which is exactly what every system sees;
  2. final: after the evidence is revealed (the maintainers' labels and who applied them,
     the fixing PRs and their files, the duplicate closure). The final pass is the gold.

The blind pass is a human baseline on the systems' own inputs, and blind-vs-final shows
how much the evidence (including the silver label) moves a careful reader.

Records are appended to `data/gold/<repo>.jsonl` (the latest line per issue wins), which
is committed: gold labels are a research artifact that others need to reproduce results.
"""

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from triagelab.data.build import dataset_paths
from triagelab.data.collect import raw_paths
from triagelab.data.models import IssueSnapshot, PRFiles, RawIssue
from triagelab.data.profile import RepoProfile
from triagelab.data.splits import Split
from triagelab.data.storage import append_jsonl, read_jsonl, read_parquet
from triagelab.eval.dataset import family_vocabulary, load_split


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    labels: list[str] = Field(default_factory=list[str])
    component: str | None = None  # None: can't tell from what was shown
    needs_info: bool = False
    duplicate_of: int | None = None  # asked only in the final pass


class GoldRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issue_ref: str
    number: int
    split: str
    blind: Decision
    final: Decision | None = None  # None until adjudicated
    unusable: bool = False  # spam, not an issue, or impossible to judge
    notes: str = ""
    annotator: str
    blind_seconds: float
    updated_at: datetime


class FixPR(BaseModel):
    number: int
    title: str
    merged: bool
    files: list[str]
    files_total: int


class Evidence(BaseModel):
    """What happened after the issue was opened: shown only after the blind pass."""

    url: str
    labels: list[tuple[str, str]]  # (label, who applied it: author | triager | bot)
    component: str | None
    component_votes: dict[str, float]
    fix_prs: list[FixPR]
    duplicate_of: int | None
    duplicate_source: str | None
    duplicate_title: str | None
    needs_info: bool
    needs_info_at: datetime | None


class LabelingItem(BaseModel):
    snapshot: IssueSnapshot
    split: str
    evidence: Evidence


def gold_path(data_dir: Path, profile: RepoProfile) -> Path:
    return data_dir / "gold" / f"{profile.slug}.jsonl"


class GoldStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, GoldRecord]:
        return {r.issue_ref: r for r in read_jsonl(self.path, GoldRecord)}

    def save(self, record: GoldRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        append_jsonl(self.path, [record])


def label_vocabulary(
    data_dir: Path, profile: RepoProfile, min_count: int = 10
) -> dict[str, list[str]]:
    """The labels a person may choose: the same vocabulary the systems are offered."""
    train = load_split(data_dir, profile, "train")
    tax = profile.taxonomy
    return {
        "type": list(tax.type),
        "area": list(tax.area),
        "family": family_vocabulary(train, min_count),
    }


def _stream[M: BaseModel](path: Path, model: type[M]) -> Iterable[M]:
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield model.model_validate_json(line)


def load_items(
    data_dir: Path, profile: RepoProfile, splits: Iterable[Split] = ("dev", "test")
) -> list[LabelingItem]:
    """Every issue to label, oldest first, with the evidence for its final pass."""
    examples = load_split(data_dir, profile, set(splits))
    wanted = {e.snapshot.number for e in examples}
    silver = {
        r["number"]: r
        for r in read_parquet(dataset_paths(data_dir, Path(), profile).silver)
        if r["number"] in wanted
    }
    issues_path, prs_path = raw_paths(data_dir, profile)
    raw: dict[int, RawIssue] = {}
    titles: dict[int, str] = {}
    for issue in _stream(issues_path, RawIssue):
        titles[issue.number] = issue.title
        if issue.number in wanted:
            raw[issue.number] = issue
    pr_numbers = {pr.number for i in raw.values() for pr in i.linked_prs}
    pr_files = {p.number: p for p in _stream(prs_path, PRFiles) if p.number in pr_numbers}

    items: list[LabelingItem] = []
    for e in sorted(examples, key=lambda e: e.snapshot.number):
        n = e.snapshot.number
        s, r = silver[n], raw[n]
        votes = cast(dict[str, float], json.loads(str(s.get("component_votes") or "{}")))
        fix_numbers = {int(x) for x in cast(list[Any], s.get("fix_prs") or [])}
        fix_prs = [
            FixPR(
                number=pr.number,
                title=pr.title,
                merged=pr.merged,
                files=list(pr_files[pr.number].files[:40]) if pr.number in pr_files else [],
                files_total=pr_files[pr.number].files_total if pr.number in pr_files else 0,
            )
            for pr in r.linked_prs
            if pr.number in fix_numbers
        ]
        duplicate_of = cast(int | None, s.get("duplicate_of"))
        items.append(
            LabelingItem(
                snapshot=e.snapshot,
                split=e.split,
                evidence=Evidence(
                    url=r.url,
                    labels=list(
                        zip(
                            cast(list[str], s["labels"]),
                            cast(list[str], s["label_sources"]),
                            strict=True,
                        )
                    ),
                    component=cast(str | None, s.get("component")),
                    component_votes=votes,
                    fix_prs=fix_prs,
                    duplicate_of=duplicate_of,
                    duplicate_source=cast(str | None, s.get("duplicate_source")),
                    duplicate_title=titles.get(duplicate_of) if duplicate_of else None,
                    needs_info=bool(s["needs_info"]),
                    needs_info_at=cast(datetime | None, s.get("needs_info_at")),
                ),
            )
        )
    return items
