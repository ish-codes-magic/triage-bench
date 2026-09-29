"""The agent triager end to end: real skills, the real MCP server in-process, a scripted model."""

import json
from pathlib import Path
from typing import Any

import pytest

from triagelab.config import AgentConfig, LLMConfig
from triagelab.data.snapshot import to_snapshot
from triagelab.harness.agent import AgentTriager
from triagelab.harness.mcp_client import McpSession
from triagelab.harness.tracing import RunTracer
from triagelab.llm_client import ToolCall
from triagelab.mcp_server.server import build_server
from triagelab.skills.loader import SkillSet

from .fakes import FAKE_MODEL, FakeBackend, completion, make_client
from .mcp_fixtures import PROFILE, REPO_ROOT, fixture_issues, make_intel

ISSUE_3 = to_snapshot(fixture_issues()[2])  # "zipfile empty archive crash again"
ANSWER: dict[str, Any] = {
    "labels": [
        {"label": "type-bug", "confidence": 0.9},
        {"label": "stdlib", "confidence": 0.8},
        {"label": "area-stdlib", "confidence": 0.5},  # invented: recorded, not kept
    ],
    "component": "stdlib",
    "component_top3": ["stdlib", "extension-modules", "made-up"],
    "component_confidence": 0.7,
    "duplicate_of": 1,
    "duplicate_confidence": 0.85,
    "duplicate_candidates": [1, 99],  # 99 is newer than #3: impossible, dropped
    "needs_info": False,
    "needs_info_confidence": 0.1,
    "triage_comment": "Possibly a duplicate of #1.",
}


def call(name: str, args: dict[str, Any], id_: str) -> ToolCall:
    return ToolCall(id=id_, name=name, arguments=json.dumps(args))


def triager(
    tmp_path: Path, backend: FakeBackend, mcp: McpSession | None, skills: list[str]
) -> tuple[AgentTriager, RunTracer]:
    tracer = RunTracer(run_id="r", jsonl_path=tmp_path / "traces.jsonl")
    agent = AgentTriager(
        client=make_client(tmp_path, backend),
        llm=LLMConfig(model=FAKE_MODEL),
        agent=AgentConfig(skills=skills),
        profile=PROFILE,
        family_labels=["topic-asyncio"],
        skills=SkillSet.from_dir(REPO_ROOT / "skills", skills),
        mcp=mcp,
        tracer=tracer,
        max_body_chars=12_000,
    )
    return agent, tracer


def test_skill_search_and_submit(tmp_path: Path) -> None:
    backend = FakeBackend(
        script=[
            completion(
                calls=(
                    call("load_skill", {"name": "triage-cpython"}, "c1"),
                    call("search_similar_issues", {"query": "zipfile empty archive"}, "c2"),
                )
            ),
            completion(calls=(call("submit_triage", ANSWER, "c3"),)),
        ]
    )
    with McpSession.in_process(build_server(make_intel(tmp_path / "co"))) as mcp:
        agent, tracer = triager(tmp_path, backend, mcp, ["triage-cpython"])
        result = agent.triage(ISSUE_3)
    tracer.close()

    first = backend.requests[0]
    assert "<name>triage-cpython</name>" in first.messages[0].content  # catalog only...
    assert "# Triaging a CPython issue" not in first.messages[0].content  # ...not the body
    names = [t.name for t in first.tools]
    assert names[-1] == "submit_triage"
    assert {"load_skill", "search_similar_issues", "get_issue"} <= set(names)
    assert "as_of" not in json.dumps([t.parameters for t in first.tools])

    replies = {m.tool_call_id: m.content for m in backend.requests[1].messages if m.role == "tool"}
    assert "# Triaging a CPython issue" in replies["c1"]  # the body arrives on demand
    found = [r["number"] for r in json.loads(replies["c2"])["results"]]
    assert 1 in found
    assert 3 not in found  # as of #3's creation, #3 doesn't exist yet

    assert result.labels == ["type-bug", "stdlib"]
    assert result.rejected_labels == ["area-stdlib"]
    assert result.component == "stdlib"
    assert result.component_candidates == ["stdlib", "extension-modules"]
    assert result.duplicate_of == 1
    assert result.duplicate_candidates == [1]
    assert (result.steps, result.tool_calls, result.stop_reason) == (2, 2, "submitted")
    assert set(result.decided_by.values()) == {"agent"}
    assert result.cost_usd > 0
    assert result.error is None

    events = [json.loads(x) for x in (tmp_path / "traces.jsonl").read_text("utf-8").splitlines()]
    end = events[-1]
    assert end["event"] == "end"
    assert end["skills_loaded"] == ["triage-cpython"]
    assert {e["trace_id"] for e in events} == {result.trace_id}


def test_no_tools_no_skills_is_a_single_decision(tmp_path: Path) -> None:
    backend = FakeBackend(script=[completion(calls=(call("submit_triage", ANSWER, "c1"),))])
    agent, _ = triager(tmp_path, backend, None, [])
    result = agent.triage(ISSUE_3)
    system = backend.requests[0].messages[0].content
    assert "available_skills" not in system
    assert "tool calls" not in system
    assert [t.name for t in backend.requests[0].tools] == ["submit_triage"]
    assert result.stop_reason == "submitted"


def test_a_failed_run_is_a_scored_fallback_with_its_reason(tmp_path: Path) -> None:
    backend = FakeBackend(script=[completion(calls=(call("submit_triage", {"x": 1}, "c"),))])
    agent, _ = triager(tmp_path, backend, None, [])
    result = agent.triage(ISSUE_3)
    assert result.error == "invalid_output"
    assert result.labels == []
    assert result.steps == 3


def test_unknown_tool_names_in_the_config_fail_fast(tmp_path: Path) -> None:
    with (
        McpSession.in_process(build_server(make_intel(tmp_path / "co"))) as mcp,
        pytest.raises(ValueError, match="unknown MCP tools"),
    ):
        AgentTriager(
            client=make_client(tmp_path, FakeBackend()),
            llm=LLMConfig(model=FAKE_MODEL),
            agent=AgentConfig(tools=["search_similar_issues", "delete_everything"]),
            profile=PROFILE,
            family_labels=[],
            skills=SkillSet([]),
            mcp=mcp,
            tracer=RunTracer(run_id="r", jsonl_path=None),
            max_body_chars=100,
        )
