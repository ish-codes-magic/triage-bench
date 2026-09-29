"""The agent loop, written by hand (AGENTS.md §10).

    model call -> tool calls -> execute -> append results -> repeat

until the model calls `submit_triage` with arguments that validate against the answer
schema. The final answer is itself a tool: its parameters are the answer's JSON schema,
and a validation error goes back to the model as that tool's result ("fix these
fields"), at most `max_validation_retries` times.

Stopping rules, in order of preference:
  - submitted: a valid answer, possibly after a forced final call (see `forced`);
  - forced final call: when a budget is (nearly) spent, the next call gets
    `tool_choice=submit_triage`, so a slow issue still produces an answer;
  - no_answer / invalid_output / budget: fallbacks with no answer, and the reason
    recorded.

Reasoning text is traced but not sent back on later turns. OpenRouter recommends
passing it back in tool loops but doesn't require it for Qwen, and dropping it keeps
prompts smaller and replays identical.
"""

from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from triagelab.harness.budgets import BudgetTracker
from triagelab.harness.context import compact
from triagelab.harness.tools import Toolbox
from triagelab.harness.tracing import IssueTrace
from triagelab.llm_client import LLMClient, LLMRequest, Message, ToolCall, ToolSpec

SUBMIT = "submit_triage"
NUDGE = (
    "Reply with a tool call. Call submit_triage with your decision now, or another tool "
    "if you still need information."
)
_MAX_FEEDBACK_CHARS = 2_000


def inline_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema with `$ref`s expanded and `title`s dropped.

    Small models follow flat schemas more reliably than `$defs` indirection, and titles
    only repeat the field names.
    """
    schema = model.model_json_schema()
    defs = cast(dict[str, Any], schema.pop("$defs", {}))

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            d = cast(dict[str, Any], node)
            if "$ref" in d:
                return resolve(defs[str(d["$ref"]).rsplit("/", 1)[-1]])
            return {k: resolve(v) for k, v in d.items() if k != "title"}
        if isinstance(node, list):
            return [resolve(v) for v in cast(list[Any], node)]
        return node

    return cast(dict[str, Any], resolve(schema))


def submit_tool(answer_type: type[BaseModel], description: str) -> ToolSpec:
    return ToolSpec(name=SUBMIT, description=description, parameters=inline_schema(answer_type))


@dataclass
class LoopOutcome[A: BaseModel]:
    answer: A | None
    stop_reason: str  # submitted | no_answer | invalid_output | budget:<limit>
    forced: str | None  # the budget limit that forced the final call, if any
    steps: int
    tool_calls: int
    tool_errors: int
    validation_errors: int
    compactions: int
    tokens_in: int
    tokens_out: int
    reasoning_tokens: int
    cost_usd: float  # at original prices, so cached replays report the true cost
    spent_usd: float  # actually spent in this run (0 for cache hits)


def _validate[A: BaseModel](call: ToolCall, answer_type: type[A]) -> tuple[A | None, str]:
    try:
        return answer_type.model_validate_json(call.arguments or "{}"), "Accepted."
    except ValidationError as err:
        text = str(err)[:_MAX_FEEDBACK_CHARS]
        return None, f"Error: invalid {SUBMIT} arguments. Fix them and call {SUBMIT} again.\n{text}"


def run_loop[A: BaseModel](
    *,
    client: LLMClient,
    base: LLMRequest,
    messages: list[Message],
    toolbox: Toolbox,
    submit: ToolSpec,
    answer_type: type[A],
    budget: BudgetTracker,
    context_limit_tokens: int,
    max_validation_retries: int,
    trace: IssueTrace,
) -> LoopOutcome[A]:
    convo = list(messages)
    logged = 0  # prompt messages (system/user) already written to the trace
    tools = (*toolbox.specs, submit)
    out = LoopOutcome[A](
        answer=None,
        stop_reason="",
        forced=None,
        steps=0,
        tool_calls=0,
        tool_errors=0,
        validation_errors=0,
        compactions=0,
        tokens_in=0,
        tokens_out=0,
        reasoning_tokens=0,
        cost_usd=0.0,
        spent_usd=0.0,
    )
    nudged = False

    while not budget.exhausted():
        convo, compaction = compact(convo, limit_tokens=context_limit_tokens)
        if compaction is not None:
            out.compactions += 1
            trace.event("compaction", step=out.steps + 1, **compaction._asdict())
        forced = budget.submit_reason()
        request = base.model_copy(
            update={
                "messages": tuple(convo),
                "tools": tools,
                "tool_choice": SUBMIT if forced else None,
            }
        )
        response = client.complete(request)
        budget.record_call(response)
        out.steps += 1
        out.tokens_in += response.usage.tokens_in
        out.tokens_out += response.usage.tokens_out
        out.reasoning_tokens += response.usage.reasoning_tokens
        out.cost_usd += response.original_cost_usd
        out.spent_usd += response.cost_usd
        prompt = [m for m in convo[logged:] if m.role in ("system", "user")]
        logged = len(convo)
        trace.llm_call(out.steps, request, prompt, response)

        if not response.tool_calls:
            if forced or nudged:
                out.stop_reason = "no_answer"
                return out
            nudged = True
            convo += [
                Message(role="assistant", content=response.text),
                Message(role="user", content=NUDGE),
            ]
            continue

        convo.append(
            Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
        )
        for call in response.tool_calls:
            if call.name == SUBMIT:
                if out.answer is not None:
                    reply = "Ignored: an answer was already accepted."
                else:
                    out.answer, reply = _validate(call, answer_type)
                    if out.answer is None:
                        out.validation_errors += 1
                        trace.event("validation_error", step=out.steps, error=reply)
            elif out.answer is not None:
                reply = "Ignored: an answer was already accepted."
            elif budget.tool_calls_left == 0:
                reply = f"Error: the tool-call budget is used up. Call {SUBMIT} now."
            else:
                result = toolbox.execute(call)
                budget.record_tool_call()
                out.tool_calls += 1
                out.tool_errors += result.is_error
                trace.tool_call(out.steps, result)
                reply = result.output
            convo.append(Message(role="tool", content=reply, tool_call_id=call.id))

        if out.answer is not None:
            out.stop_reason, out.forced = "submitted", forced
            return out
        if out.validation_errors > max_validation_retries:
            out.stop_reason = "invalid_output"
            return out

    out.stop_reason = f"budget:{budget.submit_reason() or 'max_steps'}"
    return out
