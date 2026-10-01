"""Decision runs: questions -> TriageResult fields, config pairing, and a full classifier run."""

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from triagelab.config import SystemConfig
from triagelab.data.profile import load_profile
from triagelab.data.snapshot import to_snapshot
from triagelab.decisions.base import Decision
from triagelab.decisions.questions import answer_for, questions
from triagelab.decisions.triager import DecisionTriager
from triagelab.eval.dataset import Gold
from triagelab.retrieval.dense import Matrix

from .mcp_fixtures import PROFILE, fixture_issues
from .test_runner import PROFILE_PATH, _config, _run, workspace  # noqa: F401

ISSUE = to_snapshot(fixture_issues()[2])


class Stub:
    """Answers every question with its second option, and records what it was asked."""

    name = "llm-stub"

    def __init__(self) -> None:
        self.asked: list[tuple[str, str, tuple[str, ...]]] = []

    def choose(self, state: str, question: str, options: Sequence[str]) -> Decision:
        self.asked.append((state, question, tuple(options)))
        dist = {options[1]: 0.7, options[0]: 0.2, options[2]: 0.1}
        return Decision(
            answer=options[1], confidence=0.7, backend=self.name, cost_usd=0.001, distribution=dist
        )

    def yes_no(self, state: str, question: str) -> Decision:
        raise NotImplementedError

    def score(self, state: str, question: str, lo: float, hi: float) -> Decision:
        raise NotImplementedError


def test_answers_fill_the_triage_result() -> None:
    stub = Stub()
    result = DecisionTriager(stub, PROFILE, ["type", "component"], max_body_chars=1000).triage(
        ISSUE
    )
    qs = questions(PROFILE)
    assert result.labels == [qs["type"].options[1]]
    assert result.label_confidence == {qs["type"].options[1]: 0.7}
    assert result.component == qs["component"].options[1]
    assert result.component_candidates[0] == qs["component"].options[1]
    assert len(result.component_candidates) == 3
    assert result.decided_by == {"type": "llm", "component": "llm"}
    assert result.cost_usd == pytest.approx(0.002)
    state, question, options = stub.asked[1]
    assert state.startswith("<issue>")  # the same issue block the agent sees
    assert "Components (each owns the files under its prefixes):" in question
    assert options == qs["component"].options


def test_only_unambiguous_type_labels_train_or_score() -> None:
    def gold(*labels: str) -> Gold:
        return Gold(
            labels=frozenset(labels), label_groups={}, human_triaged=True,
            duplicate_of=None, component="stdlib", needs_info=False,
        )  # fmt: skip

    assert answer_for("type", gold("type-bug", "stdlib"), PROFILE) == "type-bug"
    assert answer_for("type", gold("type-bug", "type-crash"), PROFILE) is None
    assert answer_for("type", gold("stdlib"), PROFILE) is None
    assert answer_for("component", gold(), PROFILE) == "stdlib"


def test_the_decisions_block_pairs_with_its_kind() -> None:
    with pytest.raises(ValidationError, match=r"system\.decisions is required"):
        SystemConfig.model_validate({"kind": "decisions"})
    with pytest.raises(ValidationError, match="only allowed there"):
        SystemConfig.model_validate({"kind": "majority", "decisions": {"backend": "llm"}})


class HashEncoder:
    """A stand-in for arctic-embed: a fixed random projection of character counts."""

    name = "hash"

    def __init__(self, *args: object, **kwargs: object) -> None:
        self._proj = np.random.default_rng(0).normal(size=(64, 16))

    def encode_documents(self, texts: Sequence[str]) -> Matrix:
        counts = np.array([[t.count(chr(97 + i % 26)) for i in range(64)] for t in texts])
        return (counts @ self._proj).astype(np.float32)

    def encode_queries(self, texts: Sequence[str]) -> Matrix:
        return self.encode_documents(texts)


def test_a_classifier_decision_run_end_to_end(
    workspace: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("triagelab.retrieval.encoders.FastEmbedEncoder", HashEncoder)
    cfg = _config(workspace, "majority")
    system = SystemConfig.model_validate(
        {"kind": "decisions", "decisions": {"backend": "classifier", "questions": ["type"]}}
    )
    outcome = _run(cfg.model_copy(update={"system": system}))
    assert outcome.completed == outcome.total > 0
    assert outcome.scorecard is not None
    profile = load_profile(PROFILE_PATH)
    cache = workspace / "data" / "models" / profile.slug / "decision-emb-hash.npz"
    assert cache.is_file()  # training embeddings are kept for the next run
