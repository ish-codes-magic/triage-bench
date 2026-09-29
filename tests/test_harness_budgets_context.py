"""Per-issue budgets and context compaction."""

from triagelab.config import AgentBudgetConfig
from triagelab.cost import Usage
from triagelab.harness.budgets import BudgetTracker
from triagelab.harness.context import approx_tokens, compact
from triagelab.llm_client import LLMResponse, Message, ToolCall


def response(tokens_in: int = 100, tokens_out: int = 10, cost: float = 0.001) -> LLMResponse:
    return LLMResponse(
        text="",
        model="m",
        resolved_model=None,
        usage=Usage(tokens_in=tokens_in, tokens_out=tokens_out),
        cost_usd=0.0,  # a cache hit: nothing spent now...
        original_cost_usd=cost,  # ...but the budget counts what the answer cost originally
        cache_hit=True,
        latency_ms=1,
        attempts=1,
    )


def test_steps_force_a_submit_one_call_before_the_hard_stop() -> None:
    budget = BudgetTracker(AgentBudgetConfig(max_steps=3))
    budget.record_call(response())
    assert budget.submit_reason() is None
    budget.record_call(response())
    assert budget.submit_reason() == "max_steps"  # the 3rd call must be the answer
    assert not budget.exhausted()
    budget.record_call(response())
    assert budget.exhausted()


def test_tool_calls_tokens_and_cost_each_force_a_submit() -> None:
    tools = BudgetTracker(AgentBudgetConfig(max_tool_calls=1))
    tools.record_tool_call()
    assert tools.submit_reason() == "max_tool_calls"
    assert tools.tool_calls_left == 0
    tokens = BudgetTracker(AgentBudgetConfig(max_tokens=100))
    tokens.record_call(response(tokens_in=95, tokens_out=5))
    assert tokens.submit_reason() == "max_tokens"
    cost = BudgetTracker(AgentBudgetConfig(max_cost_usd=0.002))
    cost.record_call(response(cost=0.002))
    assert cost.submit_reason() == "max_cost_usd"  # original cost, even on a cache hit


def conversation(results: list[tuple[str, str]]) -> list[Message]:
    """system, user, then one assistant call + tool result per (tool name, output)."""
    msgs = [Message(role="system", content="S" * 40), Message(role="user", content="U" * 40)]
    for i, (name, output) in enumerate(results):
        call = ToolCall(id=f"c{i}", name=name, arguments='{"q": 1}')
        msgs.append(Message(role="assistant", content="", tool_calls=(call,)))
        msgs.append(Message(role="tool", content=output, tool_call_id=f"c{i}"))
    return msgs


def test_small_conversations_are_left_alone() -> None:
    msgs = conversation([("search_code", "x" * 100)])
    out, event = compact(msgs, limit_tokens=1_000)
    assert event is None
    assert out == msgs


def test_old_results_are_elided_oldest_first_keeping_skills_and_recent_ones() -> None:
    msgs = conversation(
        [
            ("load_skill", "K" * 4000),  # skill content: never elided
            ("search_code", "a" * 4000),  # oldest ordinary result: goes first
            ("get_issue", "b" * 4000),
            ("search_code", "c" * 4000),  # the last two results stay
            ("get_issue", "d" * 4000),
        ]
    )
    out, event = compact(msgs, limit_tokens=approx_tokens(msgs) - 500, keep_last=2)
    assert event is not None
    assert event.elided == 1
    assert event.after_tokens < event.before_tokens
    tool_contents = [m.content for m in out if m.role == "tool"]
    assert tool_contents[0] == "K" * 4000
    assert tool_contents[1].startswith("[elided to save context: search_code(")
    assert tool_contents[2:] == ["b" * 4000, "c" * 4000, "d" * 4000]
    assert out[:2] == msgs[:2]  # system prompt and issue untouched


def test_compaction_gives_up_quietly_when_nothing_may_be_elided() -> None:
    msgs = conversation([("load_skill", "K" * 8000)])
    out, event = compact(msgs, limit_tokens=10)
    assert event is None
    assert out == msgs
