"""E4's planner + subagents: who sees which tools, what flows between roles, and the totals."""

import json
from pathlib import Path
from typing import Any

import pytest

from triagelab.config import AgentConfig, LLMConfig
from triagelab.harness.agent import AgentTriager
from triagelab.harness.mcp_client import McpSession
from triagelab.harness.tracing import RunTracer
from triagelab.llm_client import Completion
from triagelab.mcp_server.server import build_server
from triagelab.skills.loader import SkillSet

from .fakes import FAKE_MODEL, FakeBackend, completion, make_client
from .mcp_fixtures import PROFILE, REPO_ROOT, make_intel
from .test_harness_agent import ANSWER, ISSUE_3, call

PLAN: dict[str, Any] = {
    "look_for_duplicates": True,
    "locate_code": True,
    "duplicate_queries": ["zipfile empty archive"],
    "code_queries": ["_EndRecData"],
}
SCOUT = {"duplicate_of": 1, "duplicate_confidence": 0.8, "evidence": "#1 is the same crash."}
LOCATOR = {"component_top3": ["stdlib"], "confidence": 0.7, "evidence": "Lib/zipfile.py"}
PER_CALL_USD = 0.003  # 1000 in x $2/M + 100 out x $10/M


def team_run(tmp_path: Path, script: list[Completion]) -> tuple[FakeBackend, Any, list[Any]]:
    backend = FakeBackend(script=script)
    tracer = RunTracer(run_id="r", jsonl_path=tmp_path / "traces.jsonl")
    with McpSession.in_process(build_server(make_intel(tmp_path / "co"))) as mcp:
        agent = AgentTriager(
            client=make_client(tmp_path, backend),
            llm=LLMConfig(model=FAKE_MODEL),
            agent=AgentConfig(skills=["triage-cpython"], architecture="planner"),
            profile=PROFILE,
            family_labels=["topic-asyncio"],
            skills=SkillSet.from_dir(REPO_ROOT / "skills", ["triage-cpython"]),
            mcp=mcp,
            tracer=tracer,
            max_body_chars=12_000,
        )
        result = agent.triage(ISSUE_3)
    tracer.close()
    lines = (tmp_path / "traces.jsonl").read_text("utf-8").splitlines()
    return backend, result, [json.loads(x) for x in lines]


def test_each_role_gets_its_own_tools_and_the_findings_reach_the_synthesizer(
    tmp_path: Path,
) -> None:
    backend, result, events = team_run(
        tmp_path,
        [
            completion(text=json.dumps(PLAN)),
            completion(calls=(call("search_similar_issues", {"query": "zipfile empty"}, "s1"),)),
            completion(calls=(call("submit_findings", SCOUT, "s2"),)),
            completion(calls=(call("search_code", {"query": "_EndRecData"}, "l1"),)),
            completion(calls=(call("submit_findings", LOCATOR, "l2"),)),
            completion(calls=(call("submit_triage", ANSWER, "f1"),)),
        ],
    )
    planner, scout, _, locator, _, synthesizer = backend.requests

    assert planner.tools == ()
    assert planner.schema_name == "Plan"
    assert [t.name for t in scout.tools] == [
        "search_similar_issues",
        "get_issue",
        "submit_findings",
    ]
    assert "zipfile empty archive" in scout.messages[1].content  # the planner's hint
    assert [t.name for t in locator.tools] == ["search_code", "get_codeowners", "submit_findings"]
    assert "Components:\n- " in locator.messages[1].content
    assert "as_of" not in json.dumps([t.parameters for t in (*scout.tools, *locator.tools)])

    # The synthesizer decides with skills and the team's findings, never with retrieval.
    names = {t.name for t in synthesizer.tools}
    assert names == {"load_skill", "read_skill_file", "submit_triage"}
    note = synthesizer.messages[1].content
    assert "<team_findings>" in note
    assert '"duplicate_of":1' in note
    assert "Lib/zipfile.py" in note

    assert result.duplicate_of == 1
    assert (result.steps, result.tool_calls, result.stop_reason) == (6, 2, "submitted")
    assert result.cost_usd == pytest.approx(6 * PER_CALL_USD)
    roles = [e["role"] for e in events if e["event"] == "role"]
    assert roles == ["planner", "duplicate scout", "code locator", "synthesizer"]
    assert events[-1]["cost_usd"] == pytest.approx(6 * PER_CALL_USD)


def test_the_planner_can_skip_both_workers(tmp_path: Path) -> None:
    skip = {**PLAN, "look_for_duplicates": False, "locate_code": False}
    backend, result, _ = team_run(
        tmp_path,
        [
            completion(text=json.dumps(skip)),
            completion(calls=(call("submit_triage", ANSWER, "f1"),)),
        ],
    )
    assert len(backend.requests) == 2
    assert "Duplicate scout: not consulted" in backend.requests[1].messages[1].content
    assert result.steps == 2


def test_an_invalid_plan_sends_both_workers(tmp_path: Path) -> None:
    backend, result, events = team_run(
        tmp_path,
        [
            completion(text="I think we should search."),
            completion(calls=(call("submit_findings", SCOUT, "s1"),)),
            completion(calls=(call("submit_findings", LOCATOR, "l1"),)),
            completion(calls=(call("submit_triage", ANSWER, "f1"),)),
        ],
    )
    assert any(e["event"] == "plan_invalid" for e in events)
    assert "Suggested searches" not in backend.requests[1].messages[1].content
    assert result.stop_reason == "submitted"


def test_a_worker_without_findings_is_reported_as_such(tmp_path: Path) -> None:
    only_dupes = {**PLAN, "locate_code": False}
    backend, result, _ = team_run(
        tmp_path,
        [
            completion(text=json.dumps(only_dupes)),
            completion(calls=(call("submit_findings", {"bogus": 1}, "s1"),)),
            completion(calls=(call("submit_findings", {"bogus": 2}, "s2"),)),
            completion(calls=(call("submit_triage", ANSWER, "f1"),)),
        ],
    )
    note = backend.requests[3].messages[1].content
    assert "Duplicate scout: no findings (invalid_output)" in note
    assert result.stop_reason == "submitted"
