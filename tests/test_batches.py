"""File-based annotation: exports hide what they must, imports validate everything."""

import json
from pathlib import Path

import pytest

from triagelab.data.profile import load_profile
from triagelab.eval.failures import Failure
from triagelab.labeling.batches import (
    AnnotationError,
    export_failures,
    export_gold_blind,
    export_gold_final,
    export_ratings,
    import_failure_tags,
    import_gold_blind,
    import_gold_final,
    import_ratings,
)
from triagelab.labeling.failure_tags import FailureTagStore
from triagelab.labeling.gold import GoldStore, LabelingItem, gold_path, label_vocabulary, load_items
from triagelab.labeling.ratings import RatingItem, RatingStore, load_rubric

from .smoke_dataset import PROFILE_PATH, write_smoke_dataset

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE = load_profile(PROFILE_PATH)
COMPONENTS = [c.name for c in PROFILE.components]


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Path, list[LabelingItem], dict[str, list[str]]]:
    write_smoke_dataset(tmp_path)
    data = tmp_path / "data"
    items = [i for i in load_items(data, PROFILE) if i.split == "dev"][:3]
    return data, items, label_vocabulary(data, PROFILE, min_count=1)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_gold_round_trip_is_blind_first(
    tmp_path: Path, setup: tuple[Path, list[LabelingItem], dict[str, list[str]]]
) -> None:
    data, items, vocab = setup
    store = GoldStore(gold_path(data, PROFILE))
    by_ref = {i.snapshot.issue_ref: i for i in items}
    (blind_file,) = export_gold_blind(items, {}, vocab, COMPONENTS, tmp_path / "out")
    text = blind_file.read_text(encoding="utf-8")
    assert items[0].snapshot.title in text
    assert "What happened next" not in text  # no evidence in the blind pass
    assert export_gold_final(items, {}, tmp_path / "out") == []  # nothing blind-labeled yet

    refs = [i.snapshot.issue_ref for i in items]
    bad = write_jsonl(tmp_path / "bad.jsonl", [
        {"issue_ref": refs[0], "labels": ["type-bug"], "component": "stdlib", "needs_info": False},
        {"issue_ref": refs[1], "labels": ["stdlib"], "component": "stdlib", "needs_info": False},
    ])  # fmt: skip
    with pytest.raises(AnnotationError, match="exactly one type label"):
        import_gold_blind(bad, store, by_ref, vocab, COMPONENTS, "model-x")
    assert store.load() == {}  # a bad file stores nothing

    good = write_jsonl(tmp_path / "good.jsonl", [
        {"issue_ref": r, "labels": ["type-bug", "stdlib"], "component": None, "needs_info": False}
        for r in refs
    ])  # fmt: skip
    assert import_gold_blind(good, store, by_ref, vocab, COMPONENTS, "model-x") == 3
    (final_file,) = export_gold_final(items, store.load(), tmp_path / "out")
    final_text = final_file.read_text(encoding="utf-8")
    assert "What happened next" in final_text
    assert "Your blind answer" in final_text

    final = write_jsonl(tmp_path / "final.jsonl", [
        {"issue_ref": refs[0], "labels": ["type-crash"], "component": "docs", "needs_info": True,
         "duplicate_of": 7, "unusable": False, "notes": "n"},
    ])  # fmt: skip
    assert import_gold_final(final, store, vocab, COMPONENTS) == 1
    record = store.load()[refs[0]]
    assert record.final is not None
    assert (record.final.labels, record.final.duplicate_of) == (["type-crash"], 7)
    assert record.blind.labels == ["type-bug", "stdlib"]
    assert record.annotator == "model-x"


def test_rating_batches_never_name_the_system(
    tmp_path: Path, setup: tuple[Path, list[LabelingItem], dict[str, list[str]]]
) -> None:
    data, items, _ = setup
    rubric = load_rubric(REPO_ROOT / "configs" / "judge" / "rubric.yaml")
    rating_items = [
        RatingItem(item_id=f"{i.snapshot.issue_ref}:secret-system", issue_ref=i.snapshot.issue_ref,
                   number=i.snapshot.number, system="secret-system", run_id="r", comment="c")
        for i in items
    ]  # fmt: skip
    issues = {i.snapshot.issue_ref: i for i in items}
    out = tmp_path / "ratings"
    (batch,) = export_ratings(rating_items, issues, rubric, set(), out)
    assert "secret-system" not in batch.read_text(encoding="utf-8")
    assert list(out.iterdir()) == [batch]  # the key lives elsewhere
    key_path = tmp_path / "ratings-keys" / "ratings-01.key.json"
    answers = write_jsonl(tmp_path / "answers.jsonl", [
        {"item_id": opaque, "scores": {"correctness": 3, "actionability": 2, "tone": 4}}
        for opaque in json.loads(key_path.read_text(encoding="utf-8"))
    ])  # fmt: skip
    store = RatingStore(data)
    assert import_ratings(answers, key_path, store, rubric, "model-x") == 3
    assert set(store.ratings()) == {r.item_id for r in rating_items}
    wrong = write_jsonl(tmp_path / "wrong.jsonl", [{"item_id": "r01-01", "scores": {"tone": 9}}])
    with pytest.raises(AnnotationError, match="need"):
        import_ratings(wrong, key_path, store, rubric, "model-x")


def test_failure_tags_round_trip(
    tmp_path: Path, setup: tuple[Path, list[LabelingItem], dict[str, list[str]]]
) -> None:
    data, items, _ = setup
    ref = items[0].snapshot.issue_ref
    failure = Failure(issue_ref=ref, trace_id="t1", tasks=["T3"], details={"T3": "said docs"})
    events = {"t1": [{"event": "llm", "step": 1, "tool_calls": [], "text": "hmm"}]}
    (batch,) = export_failures(
        "run-1", [failure], events, {ref: items[0]}, set(), tmp_path / "f", limit=10
    )
    assert "said docs" in batch.read_text(encoding="utf-8")
    answers = write_jsonl(
        tmp_path / "tags.jsonl", [{"issue_ref": ref, "codes": ["retrieval miss"]}]
    )
    store = FailureTagStore(data)
    assert import_failure_tags(answers, "run-1", {ref: failure}, store, "model-x") == 1
    assert store.load()[("run-1", ref)].codes == ["retrieval miss"]
    empty = write_jsonl(tmp_path / "empty.jsonl", [{"issue_ref": ref, "codes": [" "]}])
    with pytest.raises(AnnotationError, match="no codes"):
        import_failure_tags(empty, "run-1", {ref: failure}, store, "model-x")
