"""The agent loop, driven by scripted model replies: tools, validation, budgets, nudges."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field

from triagelab.config import AgentBudgetConfig
from triagelab.harness.budgets import BudgetTracker
from triagelab.harness.loop import SUBMIT, LoopOutcome, inline_schema, run_loop, submit_tool
from triagelab.harness.tools import Tool, Toolbox, ToolKind
from triagelab.harness.tracing import RunTracer
from triagelab.llm_client import LLMRequest, Message, ToolCall, ToolSpec

from .fakes import FAKE_MODEL, FakeBackend, completion, make_client


class Guess(BaseModel):
    label: str
    confidence: float = Field(ge=0.0, le=1.0)


class Answer(BaseModel):
    guesses: list[Guess]
    note: str


class Echo:
    """A tool that returns its arguments."""

    kind: ToolKind = "mcp"
    spec = ToolSpec(name="echo", description="Echo.", parameters={"type": "object"})

    def run(self, arguments: Mapping[str, Any]) -> tuple[str, bool]:
        return json.dumps(dict(arguments)), False


def call(name: str, args: dict[str, Any] | str, id_: str) -> ToolCall:
    return ToolCall(
        id=id_, name=name, arguments=args if isinstance(args, str) else json.dumps(args)
    )


VALID = {"guesses": [{"label": "type-bug", "confidence": 0.8}], "note": "ok"}
INVALID = {"guesses": [{"label": "type-bug", "confidence": 2.0}], "note": "ok"}


def run(
    tmp_path: Path, script: list[Any], **budget: int
) -> tuple[LoopOutcome[Answer], FakeBackend, list[dict[str, Any]]]:
    backend = FakeBackend(script=script)
    tracer = RunTracer(run_id="r", jsonl_path=tmp_path / "traces.jsonl")
    tools: list[Tool] = [Echo()]
    outcome = run_loop(
        client=make_client(tmp_path, backend),
        base=LLMRequest(model=FAKE_MODEL, messages=(), max_tokens=100),
        messages=[Message(role="system", content="s"), Message(role="user", content="u")],
        toolbox=Toolbox(tools, max_result_chars=1000),
        submit=submit_tool(Answer, "Submit."),
        answer_type=Answer,
        budget=BudgetTracker(AgentBudgetConfig(**budget)),
        context_limit_tokens=10_000,
        max_validation_retries=2,
        trace=tracer.issue("o/r#1", metadata={}),
    )
    lines = (tmp_path / "traces.jsonl").read_text(encoding="utf-8").splitlines()
    return outcome, backend, [json.loads(line) for line in lines]


def test_tool_then_submit(tmp_path: Path) -> None:
    out, backend, events = run(
        tmp_path,
        [
            completion(calls=(call("echo", {"q": 1}, "c1"),)),
            completion(calls=(call(SUBMIT, VALID, "c2"),)),
        ],
    )
    assert out.stop_reason == "submitted"
    assert out.answer == Answer.model_validate(VALID)
    assert (out.steps, out.tool_calls, out.forced) == (2, 1, None)
    second = backend.requests[1].messages
    assert second[-2].tool_calls[0].name == "echo"  # the call...
    assert second[-1] == Message(
        role="tool", content='{"q": 1}', tool_call_id="c1"
    )  # ...its result
    assert [e["event"] for e in events] == ["start", "llm", "tool", "llm"]
    assert backend.requests[0].tools[-1].name == SUBMIT


def test_invalid_answer_is_fed_back_then_fixed(tmp_path: Path) -> None:
    out, backend, events = run(
        tmp_path,
        [
            completion(calls=(call(SUBMIT, INVALID, "c1"),)),
            completion(calls=(call(SUBMIT, VALID, "c2"),)),
        ],
    )
    assert out.stop_reason == "submitted"
    assert out.validation_errors == 1
    feedback = backend.requests[1].messages[-1]
    assert feedback.role == "tool"
    assert feedback.tool_call_id == "c1"
    assert "invalid submit_triage arguments" in feedback.content
    assert "confidence" in feedback.content  # pydantic names the bad field
    assert "validation_error" in [e["event"] for e in events]


def test_too_many_invalid_answers_stop_the_loop(tmp_path: Path) -> None:
    out, backend, _ = run(tmp_path, [completion(calls=(call(SUBMIT, "{not json", "c"),))])
    assert out.stop_reason == "invalid_output"
    assert out.answer is None
    assert backend.calls == 3  # first try + max_validation_retries (2)


def test_near_the_step_limit_the_final_call_is_forced(tmp_path: Path) -> None:
    out, backend, _ = run(
        tmp_path,
        [
            completion(calls=(call("echo", {}, "c1"),)),
            completion(calls=(call("echo", {}, "c2"),)),
            completion(calls=(call(SUBMIT, VALID, "c3"),)),
        ],
        max_steps=3,
    )
    assert [r.tool_choice for r in backend.requests] == [None, None, SUBMIT]
    assert out.stop_reason == "submitted"
    assert out.forced == "max_steps"


def test_tool_budget_answers_extra_calls_with_an_error_and_forces_submit(tmp_path: Path) -> None:
    out, backend, _ = run(
        tmp_path,
        [
            completion(calls=(call("echo", {"n": 1}, "c1"), call("echo", {"n": 2}, "c2"))),
            completion(calls=(call(SUBMIT, VALID, "c3"),)),
        ],
        max_tool_calls=1,
    )
    replies = [m for m in backend.requests[1].messages if m.role == "tool"]
    assert replies[0].content == '{"n": 1}'
    assert "tool-call budget is used up" in replies[1].content
    assert backend.requests[1].tool_choice == SUBMIT
    assert out.tool_calls == 1
    assert out.forced == "max_tool_calls"


def test_a_text_reply_gets_one_nudge(tmp_path: Path) -> None:
    out, backend, _ = run(
        tmp_path,
        [completion(text="I think it's a bug."), completion(calls=(call(SUBMIT, VALID, "c"),))],
    )
    assert out.stop_reason == "submitted"
    assert backend.requests[1].messages[-1].role == "user"  # the nudge
    (tmp_path / "b").mkdir()
    out2, _, _ = run(tmp_path / "b", [completion(text="still thinking")])
    assert out2.stop_reason == "no_answer"


def test_a_model_that_never_submits_hits_the_hard_stop(tmp_path: Path) -> None:
    out, backend, _ = run(tmp_path, [completion(calls=(call("echo", {}, "c"),))], max_steps=2)
    assert out.stop_reason == "budget:max_steps"
    assert out.answer is None
    assert backend.calls == 2


def test_costs_and_tokens_add_up_across_steps(tmp_path: Path) -> None:
    out, _, _ = run(
        tmp_path,
        [
            completion(calls=(call("echo", {}, "c1"),), tokens=(1000, 100)),
            completion(calls=(call(SUBMIT, VALID, "c2"),), tokens=(2000, 50)),
        ],
    )
    assert (out.tokens_in, out.tokens_out) == (3000, 150)
    # (1000 + 2000) * $2/M + (100 + 50) * $10/M
    assert out.cost_usd == pytest.approx(0.0075)
    assert out.spent_usd == pytest.approx(0.0075)


def test_inline_schema_expands_refs_and_drops_titles() -> None:
    schema = inline_schema(Answer)
    text = json.dumps(schema)
    assert "$ref" not in text
    assert "$defs" not in text
    assert "title" not in text
    assert schema["properties"]["guesses"]["items"]["properties"]["confidence"]["maximum"] == 1.0


def test_the_first_call_can_be_forced_to_a_tool(tmp_path: Path) -> None:
    backend = FakeBackend(
        script=[
            completion(calls=(call("echo", {}, "c1"),)),
            completion(calls=(call(SUBMIT, VALID, "c2"),)),
        ]
    )
    tracer = RunTracer(run_id="r", jsonl_path=None)
    tools: list[Tool] = [Echo()]
    run_loop(
        client=make_client(tmp_path, backend),
        base=LLMRequest(model=FAKE_MODEL, messages=(), max_tokens=100),
        messages=[Message(role="system", content="s"), Message(role="user", content="u")],
        toolbox=Toolbox(tools, max_result_chars=1000),
        submit=submit_tool(Answer, "Submit."),
        answer_type=Answer,
        budget=BudgetTracker(AgentBudgetConfig()),
        context_limit_tokens=10_000,
        max_validation_retries=2,
        trace=tracer.issue("o/r#1", metadata={}),
        first_tool_choice="echo",
    )
    assert [r.tool_choice for r in backend.requests] == ["echo", None]  # only the first
