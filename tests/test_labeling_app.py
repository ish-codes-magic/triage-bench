"""The labeling app, driven through Streamlit's AppTest on the synthetic smoke dataset."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from triagelab.data.profile import load_profile
from triagelab.labeling.gold import GoldStore, gold_path, load_items

from .smoke_dataset import PROFILE_PATH, write_smoke_dataset

APP = Path(__file__).resolve().parents[1] / "src" / "triagelab" / "labeling" / "app.py"


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
