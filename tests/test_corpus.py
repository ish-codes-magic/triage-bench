from datetime import timedelta
from pathlib import Path

import pytest

from triagelab.retrieval.corpus import Corpus, NotVisibleError, build_corpus

from .data_fixtures import ORIGINAL_BODY, raw

pytestmark = pytest.mark.leakage  # the corpus is a leakage boundary, like snapshots


def _corpus() -> Corpus:
    base = raw()
    assert base.original_body is not None
    issues = []
    for n in (1, 2, 3):
        created = base.created_at + timedelta(days=n - 1)  # issue 1 keeps the fixture timeline
        # Shift the creation revision with the issue, or the snapshot check (correctly)
        # refuses it as "creation text unprovable".
        original = base.original_body.model_copy(update={"at": created})
        issues.append(
            base.model_copy(update={"number": n, "created_at": created, "original_body": original})
        )
    return build_corpus(issues)


def test_visible_is_strictly_before_as_of() -> None:
    corpus = _corpus()
    t2 = corpus.issues[1].created_at
    assert [i.number for i in corpus.visible(t2)] == [1]  # issue 2 itself is not visible
    assert [i.number for i in corpus.visible(t2 + timedelta(seconds=1))] == [1, 2]


def test_get_refuses_future_issues() -> None:
    corpus = _corpus()
    t2 = corpus.issues[1].created_at
    with pytest.raises(NotVisibleError):
        corpus.get(3, t2)
    with pytest.raises(NotVisibleError):
        corpus.get(2, t2)
    with pytest.raises(NotVisibleError):
        corpus.get(999, t2 + timedelta(days=30))


def test_corpus_stores_creation_text_not_current_text() -> None:
    entry = _corpus().issues[0]
    assert entry.body == ORIGINAL_BODY
    assert "gh-linked-prs" not in entry.body
    assert entry.title == "foo() crashes"


def test_get_replays_labels_and_state_as_of() -> None:
    corpus = _corpus()
    issue_1 = corpus.issues[0]
    early = corpus.get(1, issue_1.created_at + timedelta(minutes=30))
    assert early.labels == ("type-bug",)  # triager's "stdlib" came 3h after creation
    assert early.state == "open"
    late = corpus.get(1, issue_1.created_at + timedelta(days=30))
    assert late.state == "closed"


def test_round_trip(tmp_path: Path) -> None:
    corpus = _corpus()
    corpus.save(tmp_path / "corpus.jsonl")
    loaded = Corpus.load(tmp_path / "corpus.jsonl")
    assert [i.number for i in loaded.issues] == [1, 2, 3]
    assert loaded.issues[0] == corpus.issues[0]


def test_refusals_do_not_reveal_whether_a_later_issue_exists() -> None:
    corpus = _corpus()
    t2 = corpus.issues[1].created_at

    def message(number: int) -> str:
        with pytest.raises(NotVisibleError) as info:
            corpus.get(number, t2)
        return str(info.value).replace(f"#{number}", "#N")

    # Issue 3 exists (later); 999 never does. The model must not be able to tell.
    assert message(3) == message(999)
