"""The live cascade: one issue at a time, routed exactly as the offline cascade routes it."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from triagelab.config import SystemConfig
from triagelab.data.models import IssueSnapshot
from triagelab.data.storage import read_jsonl
from triagelab.decisions.cascade import self_signal
from triagelab.decisions.live_cascade import ROUTES_FILE, CascadeTriager, Routing, routing_log
from triagelab.triage import TriageResult

TYPES = ["type-bug", "type-crash", "type-feature"]
ISSUE = IssueSnapshot(
    issue_ref="o/r#1", repo="o/r", number=1, title="t", body="b",
    author_association="NONE", created_at=datetime(2026, 6, 1, tzinfo=UTC),
)  # fmt: skip
FULL = TriageResult(
    issue_ref="o/r#1", labels=["type-crash"], component="interpreter-core", trace_id="full-1",
    decided_by={"labels": "agent"}, cost_usd=0.007, tokens_in=60_000, tokens_out=2_000,
)  # fmt: skip


def cheap(
    type_confidence: float, component_confidence: float, error: str | None = None
) -> TriageResult:
    return TriageResult(
        issue_ref="o/r#1", labels=["type-bug"], label_confidence={"type-bug": type_confidence},
        component="stdlib", component_confidence=component_confidence, trace_id="cheap-1",
        decided_by={"labels": "agent"}, cost_usd=0.001, tokens_in=7_000, tokens_out=900,
        error=error,
    )  # fmt: skip


class Fixed:
    name = "fixed"

    def __init__(self, result: TriageResult) -> None:
        self.result = result
        self.calls = 0

    def triage(self, issue: IssueSnapshot) -> TriageResult:
        self.calls += 1
        return self.result


def test_a_confident_cheap_answer_stands_and_the_agent_is_never_called() -> None:
    full = Fixed(FULL)
    seen: list[Routing] = []
    out = CascadeTriager(Fixed(cheap(0.9, 0.8)), full, TYPES, 0.70, seen.append).triage(ISSUE)
    assert (out.labels, out.component) == (["type-bug"], "stdlib")
    assert out.decided_by == {"labels": "agent", "cascade": "cheap tier"}
    assert out.cost_usd == pytest.approx(0.001)
    assert full.calls == 0
    assert (seen[0].signal, seen[0].escalated, seen[0].full_trace_id) == (0.8, False, None)


def test_an_unsure_cheap_answer_escalates_and_pays_for_both_tiers() -> None:
    seen: list[Routing] = []
    out = CascadeTriager(Fixed(cheap(0.9, 0.6)), Fixed(FULL), TYPES, 0.70, seen.append).triage(
        ISSUE
    )
    assert (out.labels, out.component) == (["type-crash"], "interpreter-core")
    assert out.decided_by == {"labels": "agent", "cascade": "escalated"}
    assert out.cost_usd == pytest.approx(0.008)  # 0.001 cheap + 0.007 full
    assert (out.tokens_in, out.tokens_out) == (67_000, 2_900)
    assert seen[0].model_dump() == {
        "issue_ref": "o/r#1", "signal": 0.6, "tau": 0.70, "escalated": True,
        "cheap_trace_id": "cheap-1", "full_trace_id": "full-1",
    }  # fmt: skip


def test_the_boundary_and_fallbacks_route_like_the_offline_cascade() -> None:
    # Offline: an issue escalates iff signal < tau (Thresholded.escalates).
    at_tau = Fixed(FULL)
    CascadeTriager(Fixed(cheap(0.70, 0.70)), at_tau, TYPES, 0.70).triage(ISSUE)
    assert at_tau.calls == 0  # signal == tau is kept
    failed = cheap(0.99, 0.99, error="no_answer")
    assert self_signal(failed, TYPES) == 0.0
    after_fallback = Fixed(FULL)
    CascadeTriager(Fixed(failed), after_fallback, TYPES, 0.70).triage(ISSUE)
    assert after_fallback.calls == 1  # a cheap tier that fell back always escalates


def test_routings_are_logged_next_to_the_run(tmp_path: Path) -> None:
    triager = CascadeTriager(
        Fixed(cheap(0.9, 0.6)), Fixed(FULL), TYPES, 0.70, routing_log(tmp_path)
    )
    triager.triage(ISSUE)
    (logged,) = read_jsonl(tmp_path / ROUTES_FILE, Routing)
    assert logged.escalated


def test_the_cascade_block_pairs_with_its_kind() -> None:
    with pytest.raises(ValidationError, match=r"system\.cascade is required"):
        SystemConfig.model_validate({"kind": "cascade"})
    block = {"cheap": "a.yaml", "full": "b.yaml", "tau": 0.7}
    assert SystemConfig.model_validate({"kind": "cascade", "cascade": block}).cascade is not None
    with pytest.raises(ValidationError, match="only allowed there"):
        SystemConfig.model_validate({"kind": "majority", "cascade": block})
