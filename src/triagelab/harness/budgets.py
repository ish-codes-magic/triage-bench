"""Per-issue budgets: steps, tool calls, tokens and dollars (AGENTS.md §10).

Two thresholds, on purpose:
  - `submit_reason()`: a limit is (nearly) reached, so the next model call is *forced*
    to call `submit_triage`. The agent still answers, and the result records why.
  - `exhausted()`: the hard stop. No further model calls at all.

Cached responses count at their original cost and tokens. A replayed run (cache or CI
cassette) must therefore make exactly the decisions the recorded run made; counting a
cache hit as free would trip the cost limit at a different step and change every
request after it.
"""

from pydantic import BaseModel

from triagelab.config import AgentBudgetConfig
from triagelab.llm_client import LLMResponse


class BudgetUse(BaseModel):
    steps: int = 0
    tool_calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0


class BudgetTracker:
    def __init__(self, limits: AgentBudgetConfig) -> None:
        self.limits = limits
        self.use = BudgetUse()

    def record_call(self, response: LLMResponse) -> None:
        self.use.steps += 1
        self.use.tokens += response.usage.tokens_in + response.usage.tokens_out
        self.use.cost_usd += response.original_cost_usd

    def record_tool_call(self) -> None:
        self.use.tool_calls += 1

    @property
    def tool_calls_left(self) -> int:
        return max(0, self.limits.max_tool_calls - self.use.tool_calls)

    def submit_reason(self) -> str | None:
        """Why the next call must be the final answer, or None if it needn't be."""
        use, lim = self.use, self.limits
        if use.steps >= lim.max_steps - 1:
            return "max_steps"
        if use.tool_calls >= lim.max_tool_calls:
            return "max_tool_calls"
        if use.tokens >= lim.max_tokens:
            return "max_tokens"
        if use.cost_usd >= lim.max_cost_usd:
            return "max_cost_usd"
        return None

    def exhausted(self) -> bool:
        return self.use.steps >= self.limits.max_steps
