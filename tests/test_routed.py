"""The routed system: backends overwrite the type label and the component; the rest stays."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from triagelab.config import SystemConfig
from triagelab.data.models import IssueSnapshot
from triagelab.decisions.routed import RoutedTriager, route
from triagelab.triage import TriageResult

TYPES = ["type-bug", "type-crash", "type-feature"]
BASE = TriageResult(
    issue_ref="o/r#1",
    labels=["type-bug", "stdlib", "topic-asyncio"],
    label_confidence={"type-bug": 0.9, "stdlib": 1.0, "topic-asyncio": 0.95},
    component="stdlib",
    component_confidence=0.8,
    component_candidates=["stdlib", "tests", "docs"],
    duplicate_of=7,
    triage_comment="A comment.",
    decided_by={"labels": "agent", "component": "agent"},
    cost_usd=0.001,
    tokens_in=1000,
)
TYPE = TriageResult(
    issue_ref="o/r#1",
    labels=["type-crash"],
    label_confidence={"type-crash": 0.7},
    decided_by={"type": "llm"},
    cost_usd=0.0001,
    tokens_in=100,
)
COMPONENT = TriageResult(
    issue_ref="o/r#1",
    component="tests",
    component_confidence=0.6,
    decided_by={"component": "classifier"},
    cost_usd=0.0002,
)


def test_backends_overwrite_their_decisions_only() -> None:
    out = route(BASE, {"type": TYPE, "component": COMPONENT}, TYPES)
    assert out.labels == ["type-crash", "stdlib", "topic-asyncio"]  # one type; the rest kept
    assert out.label_confidence == {"type-crash": 0.7, "stdlib": 1.0, "topic-asyncio": 0.95}
    assert (out.component, out.component_confidence) == ("tests", 0.6)
    assert out.component_candidates == ["tests", "stdlib", "docs"]
    assert out.decided_by == {"labels": "agent", "type": "llm", "component": "classifier"}
    assert (out.duplicate_of, out.triage_comment) == (7, "A comment.")  # untouched
    assert out.cost_usd == pytest.approx(0.0013)
    assert out.tokens_in == 1100


def test_an_abstaining_backend_leaves_the_base_answer() -> None:
    silent = TriageResult(issue_ref="o/r#1", cost_usd=0.0001)
    out = route(BASE, {"type": silent, "component": silent}, TYPES)
    assert out.labels == BASE.labels
    assert out.component == "stdlib"
    assert out.decided_by == BASE.decided_by
    assert out.cost_usd == pytest.approx(0.0012)  # the calls were still paid for


class Fixed:
    name = "fixed"

    def __init__(self, result: TriageResult) -> None:
        self._result = result

    def triage(self, issue: IssueSnapshot) -> TriageResult:
        return self._result


def test_the_triager_composes_its_parts() -> None:
    issue = IssueSnapshot(
        issue_ref="o/r#1", repo="o/r", number=1, title="t", body="b",
        author_association="NONE", created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )  # fmt: skip
    out = RoutedTriager(Fixed(BASE), {"type": Fixed(TYPE)}, TYPES).triage(issue)
    assert out.labels[0] == "type-crash"
    assert out.component == "stdlib"  # no component backend configured


def test_the_routed_block_pairs_with_its_kind() -> None:
    with pytest.raises(ValidationError, match=r"system\.routed is required"):
        SystemConfig.model_validate({"kind": "routed"})
    ok = SystemConfig.model_validate({"kind": "routed", "routed": {"base": "a.yaml"}})
    assert ok.routed is not None
    assert ok.routed.type is None
