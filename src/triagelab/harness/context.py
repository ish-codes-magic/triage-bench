"""Context management: keep the conversation under a working size (AGENTS.md §10).

Two mechanisms:
  - every tool result is truncated when it is produced (`Toolbox`);
  - when the whole conversation passes a threshold, the oldest tool results are replaced
    by a one-line stub, oldest first, until it fits (`compact`).

The system prompt, the issue, skill content (the Agent Skills client guide says to exempt
it from pruning) and the most recent results are never elided. The stub names the call,
so the model can simply repeat it if it needs the data again. This is cheaper and more
predictable than asking a model to summarise its own history.
"""

from collections.abc import Sequence
from typing import NamedTuple

from triagelab.llm_client import Message, ToolCall

SKILL_TOOLS = frozenset({"load_skill", "read_skill_file"})
_ELIDED = "[elided to save context: "


def approx_tokens(messages: Sequence[Message]) -> int:
    """About 4 characters per token. Only used for the compaction threshold; budgets
    use the provider's exact token counts."""
    chars = sum(
        len(m.content) + sum(len(c.name) + len(c.arguments) for c in m.tool_calls) for m in messages
    )
    return chars // 4


class Compaction(NamedTuple):
    before_tokens: int
    after_tokens: int
    elided: int


def _stub(call: ToolCall | None, size: int) -> str:
    what = f"{call.name}({call.arguments[:120]})" if call else "an earlier tool call"
    return f"{_ELIDED}{what} returned {size} characters; call it again if you need it]"


def compact(
    messages: Sequence[Message], *, limit_tokens: int, keep_last: int = 2
) -> tuple[list[Message], Compaction | None]:
    """Elide old tool results until the conversation fits; None if nothing was needed."""
    before = approx_tokens(messages)
    if before <= limit_tokens:
        return list(messages), None
    calls = {c.id: c for m in messages for c in m.tool_calls}
    tool_positions = [i for i, m in enumerate(messages) if m.role == "tool"]
    recent = set(tool_positions[-keep_last:]) if keep_last else set[int]()
    out = list(messages)
    size = before
    elided = 0
    for i in tool_positions:
        if size <= limit_tokens:
            break
        m = out[i]
        call = calls.get(m.tool_call_id or "")
        if i in recent or m.content.startswith(_ELIDED) or (call and call.name in SKILL_TOOLS):
            continue
        stub = _stub(call, len(m.content))
        size -= (len(m.content) - len(stub)) // 4
        out[i] = m.model_copy(update={"content": stub})
        elided += 1
    if not elided:
        return out, None
    return out, Compaction(before_tokens=before, after_tokens=approx_tokens(out), elided=elided)
