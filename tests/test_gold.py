"""Gold records: the store (latest line wins) and evidence assembly on the smoke dataset."""

from datetime import UTC, datetime
from pathlib import Path

from triagelab.data.profile import load_profile
from triagelab.labeling.gold import Decision, GoldRecord, GoldStore, label_vocabulary, load_items

from .smoke_dataset import PROFILE_PATH, write_smoke_dataset


def record(ref: str, labels: list[str], final: bool) -> GoldRecord:
    decision = Decision(labels=labels, component="stdlib")
    return GoldRecord(
        issue_ref=ref,
        number=int(ref.split("#")[1]),
        split="dev",
        blind=decision,
        final=decision if final else None,
        annotator="t",
        blind_seconds=12.5,
        updated_at=datetime(2026, 9, 30, tzinfo=UTC),
    )


def test_store_keeps_the_latest_record_per_issue(tmp_path: Path) -> None:
    store = GoldStore(tmp_path / "gold" / "repo.jsonl")
    assert store.load() == {}
    store.save(record("o/r#1", ["type-bug"], final=False))
    store.save(record("o/r#2", ["type-feature"], final=True))
    store.save(record("o/r#1", ["type-crash"], final=True))
    loaded = store.load()
    assert set(loaded) == {"o/r#1", "o/r#2"}
    first = loaded["o/r#1"].final
    assert first is not None
    assert first.labels == ["type-crash"]


def test_items_carry_creation_time_text_and_post_creation_evidence(tmp_path: Path) -> None:
    write_smoke_dataset(tmp_path)
    profile = load_profile(PROFILE_PATH)
    items = load_items(tmp_path / "data", profile)
    assert {i.split for i in items} == {"dev", "test"}
    assert [i.snapshot.number for i in items] == sorted(i.snapshot.number for i in items)
    fixed = next(i for i in items if i.evidence.fix_prs)
    assert fixed.evidence.fix_prs[0].files  # the fixing PR's changed files
    assert fixed.evidence.component is not None
    duplicate = next(i for i in items if i.evidence.duplicate_of)
    assert duplicate.evidence.duplicate_title  # the original's title, for adjudication
    assert all(
        source in {"author", "triager", "bot"} for i in items for _, source in i.evidence.labels
    )
    vocab = label_vocabulary(tmp_path / "data", profile, min_count=1)
    assert vocab["type"][0].startswith("type-")
