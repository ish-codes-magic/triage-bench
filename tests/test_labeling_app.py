"""The labeling app, driven through Streamlit's AppTest on the synthetic smoke dataset."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from triagelab.config import load_config
from triagelab.data.profile import load_profile
from triagelab.eval.runner import run_eval
from triagelab.labeling.failure_tags import FailureTagStore
from triagelab.labeling.gold import GoldStore, LabelingItem, gold_path, load_items
from triagelab.labeling.ratings import RatingStore, sample_items
from triagelab.triage import TriageResult

from .smoke_dataset import PROFILE_PATH, write_smoke_dataset

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "src" / "triagelab" / "labeling" / "app.py"


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    write_smoke_dataset(tmp_path)
    data = tmp_path / "data"
    monkeypatch.setenv("TRIAGELAB_DATA_DIR", str(data))
    monkeypatch.setenv("TRIAGELAB_PROFILE", str(PROFILE_PATH))
    monkeypatch.setenv("TRIAGELAB_ANNOTATOR", "tester")
    return data


def button(at: AppTest, label: str) -> AppTest:
    return next(b for b in at.button if b.label == label).click().run()


def test_blind_then_final_pass_writes_one_gold_record(data_dir: Path) -> None:
    profile = load_profile(PROFILE_PATH)
    first = next(i for i in load_items(data_dir, profile) if i.split == "dev")
    n = first.snapshot.number
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    assert at.subheader[0].value.startswith(f"#{n} ")
    assert not any("What happened next" in m.value for m in at.markdown)  # blind: no evidence

    at = button(at, "Save and reveal")  # no type chosen yet
    assert any("Choose a type label" in e.value for e in at.error)

    at.radio(key=f"blind_{n}_type").set_value("type-bug")
    at = button(at, "Save and reveal")
    store = GoldStore(gold_path(data_dir, profile))
    record = store.load()[first.snapshot.issue_ref]
    assert record.blind.labels == ["type-bug"]
    assert record.final is None
    assert record.annotator == "tester"
    assert any("What happened next" in m.value for m in at.markdown)  # evidence revealed

    at.radio(key=f"final_{n}_type").set_value("type-crash")
    at = button(at, "Save gold and next")
    record = store.load()[first.snapshot.issue_ref]
    assert record.final is not None
    assert record.final.labels == ["type-crash"]
    assert record.blind.labels == ["type-bug"]  # the blind answer is kept
    assert not at.subheader[0].value.startswith(f"#{n} ")  # moved on to the next issue


def write_run(runs: Path, name: str, items: list[LabelingItem], comment: str) -> Path:
    run = runs / f"20260930-000000-{name}"
    run.mkdir(parents=True)
    predictions = [
        TriageResult(
            issue_ref=i.snapshot.issue_ref, triage_comment=f"{comment} {i.snapshot.number}"
        )
        for i in items
    ]
    (run / "predictions.jsonl").write_text(
        "".join(p.model_dump_json() + "\n" for p in predictions), encoding="utf-8"
    )
    return run


def test_rating_page_scores_every_criterion_blind_to_the_system(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIAGELAB_RUBRIC", str(REPO_ROOT / "configs" / "judge" / "rubric.yaml"))
    dev = [i for i in load_items(data_dir, load_profile(PROFILE_PATH)) if i.split == "dev"][:3]
    runs = {
        "agent": write_run(tmp_path / "runs", "agent", dev, "Agent says"),
        "single": write_run(tmp_path / "runs", "single", dev, "Single says"),
    }
    store = RatingStore(data_dir)
    store.write_items(sample_items(runs))
    with pytest.raises(FileExistsError):  # the rated set is frozen once written
        store.write_items(sample_items(runs))
    page = tmp_path / "rate_page.py"
    page.write_text(
        "from triagelab.labeling import rating_page\nrating_page.render()\n", encoding="utf-8"
    )
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception
    assert not any("agent" in t.value.lower() or "single" in t.value.lower() for t in at.markdown)

    at = button(at, "Save and next")
    assert any("Score every criterion" in e.value for e in at.error)
    first = store.items()[0]
    for criterion in ("correctness", "actionability", "tone"):
        at.segmented_control(key=f"rate_{first.item_id}_{criterion}").set_value(3)
    at = button(at, "Save and next")
    rating = store.ratings()[first.item_id]
    assert rating.scores == {"correctness": 3, "actionability": 3, "tone": 3}
    assert rating.rubric_version == 1


def test_review_page_tags_a_failure_of_a_replayed_agent_run(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = load_config(tmp_path / "agent.yaml")  # the smoke agent, replayed from cassettes
    outcome = run_eval(
        cfg, split="dev", runs_dir=cfg.paths.runs_dir, command="t", log=lambda _: None, limit=10
    )
    monkeypatch.setenv("TRIAGELAB_RUNS_DIR", str(cfg.paths.runs_dir))
    page = tmp_path / "review_page.py"
    page.write_text(
        "from triagelab.labeling import review_page\nreview_page.render()\n", encoding="utf-8"
    )
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception
    assert any("What went wrong" in m.value for m in at.markdown)
    assert any("Agent trace" in m.value for m in at.markdown)

    at = button(at, "Save and next")
    assert any("at least one code" in e.value for e in at.error)
    at.multiselect[0].set_value(["retrieval miss"])
    at = button(at, "Save and next")
    tags = FailureTagStore(data_dir).load()
    assert len(tags) == 1
    ((run_id, _), tag), *_ = tags.items()
    assert run_id == outcome.run_dir.name
    assert tag.codes == ["retrieval miss"]
