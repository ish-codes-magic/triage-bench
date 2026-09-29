"""The agent triager: our loop + repo-intel over MCP + skills, behind the `Triager` contract.

Per issue it builds a fresh toolbox whose MCP tools have `as_of` fixed to the issue's
creation time, runs the loop, and maps the validated answer onto `TriageResult`.
The label vocabulary and issue framing are the same bytes the single-shot baseline sees
(`triagelab.prompting`), so agent-vs-baseline differences come from tools and skills.
"""

import time
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from triagelab.config import AgentConfig, LLMConfig
from triagelab.data.models import IssueSnapshot
from triagelab.data.profile import RepoProfile
from triagelab.harness.budgets import BudgetTracker
from triagelab.harness.loop import LoopOutcome, run_loop, submit_tool
from triagelab.harness.mcp_client import McpSession, ToolInfo
from triagelab.harness.tools import Tool, Toolbox, mcp_tools, skill_tools
from triagelab.harness.tracing import RunTracer
from triagelab.llm_client import LLMClient, LLMRequest, Message
from triagelab.prompting import UNTRUSTED_ISSUE, issue_prompt
from triagelab.skills.loader import SkillSet
from triagelab.triage import TriageResult

PROMPT_VERSION = "2"  # bump with any change to SYSTEM_PROMPT or the answer schema


class LabelGuess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="A label copied exactly from the allowed list.")
    confidence: float = Field(ge=0.0, le=1.0)


class AgentAnswer(BaseModel):
    """The `submit_triage` arguments. Descriptions are read by the model."""

    model_config = ConfigDict(extra="forbid")

    labels: list[LabelGuess] = Field(
        description="Every allowed label that applies: one type label, plus area, topic "
        "and OS labels that clearly apply."
    )
    component: str = Field(description="The component a fix would change, from the list.")
    # Required (iteration 3): with a default, the model omitted it on 77% of issues and
    # top-3 accuracy silently became top-1.
    component_top3: list[str] = Field(description="Your 3 most likely components, best first.")
    component_confidence: float = Field(ge=0.0, le=1.0)
    duplicate_of: int | None = Field(
        default=None, description="An earlier issue this one duplicates, or null."
    )
    duplicate_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Probability it duplicates duplicate_of."
    )
    duplicate_candidates: list[int] = Field(
        default_factory=list[int], description="Earlier issues that might be duplicates."
    )
    needs_info: bool = Field(description="True if the reporter must provide more information.")
    needs_info_confidence: float = Field(ge=0.0, le=1.0)
    missing_info: list[str] = Field(default_factory=list[str])
    suggested_owners: list[str] = Field(
        default_factory=list[str], description="GitHub handles from get_codeowners, if any."
    )
    triage_comment: str = Field(description="1-3 sentences a maintainer could post.")

    @field_validator("duplicate_of", mode="before")
    @classmethod
    def _null_spelled_as_text(cls, value: object) -> object:
        # Seen in the first real runs: Qwen writes "duplicate_of": "None" (a string) when
        # it means null, and each one cost a validation round-trip.
        if isinstance(value, str) and value.strip().lower() in {"", "none", "null"}:
            return None
        return value


SYSTEM_PROMPT = """You triage GitHub issues for the {repo} repository, like an experienced \
maintainer.

You receive one issue exactly as it was first opened. {untrusted}
{tools}{skills}
Decide the labels, the component a fix would change (and your top 3), whether the issue \
duplicates an earlier one, whether the reporter must provide more information, and a short \
comment for maintainers. Give every confidence as a probability between 0 and 1.

When you have decided, call submit_triage exactly once."""

_TOOLS_NOTE = (
    "\nUse the tools to look things up before deciding; they only show information from "
    "before the issue was opened. You may make at most {n} tool calls.\n"
)
_SKILLS_NOTE = (
    "\nSkills hold instructions for this repository. When the task matches a skill's "
    "description, call load_skill with its name first and follow it.\n{catalog}\n"
)
SUBMIT_DESCRIPTION = "Submit your final triage decision. Call exactly once, when you have decided."
_DECISIONS = ("labels", "component", "duplicate", "needs_info", "comment")


def system_prompt(repo: str, *, has_tools: bool, max_tool_calls: int, skills: SkillSet) -> str:
    catalog = skills.catalog()
    return SYSTEM_PROMPT.format(
        repo=repo,
        untrusted=UNTRUSTED_ISSUE,
        tools=_TOOLS_NOTE.format(n=max_tool_calls) if has_tools else "",
        skills=_SKILLS_NOTE.format(catalog=catalog) if catalog else "",
    )


def _dedupe[T](items: Sequence[T]) -> list[T]:
    return list(dict.fromkeys(items))


class AgentTriager:
    name = "agent"

    def __init__(
        self,
        *,
        client: LLMClient,
        llm: LLMConfig,
        agent: AgentConfig,
        profile: RepoProfile,
        family_labels: Sequence[str],
        skills: SkillSet,
        mcp: McpSession | None,
        tracer: RunTracer,
        max_body_chars: int,
    ) -> None:
        self._client = client
        self._llm = llm
        self._agent = agent
        self._profile = profile
        self._family_labels = list(family_labels)
        self._skills = skills
        self._mcp = mcp
        self._tracer = tracer
        self._max_body_chars = max_body_chars
        self._components = [c.name for c in profile.components]
        tax = profile.taxonomy
        self._allowed_labels = {*tax.type, *tax.area, *self._family_labels}
        self._mcp_infos: list[ToolInfo] = self._select_tools(mcp) if mcp else []
        self._system = system_prompt(
            profile.repo,
            has_tools=bool(self._mcp_infos) or bool(len(skills)),
            max_tool_calls=agent.budget.max_tool_calls,
            skills=skills,
        )

    def _select_tools(self, mcp: McpSession) -> list[ToolInfo]:
        infos = mcp.list_tools()
        wanted = self._agent.tools
        if wanted is None:
            return infos
        unknown = set(wanted) - {i.name for i in infos}
        if unknown:
            raise ValueError(f"agent.tools names unknown MCP tools: {sorted(unknown)}")
        return [i for i in infos if i.name in wanted]

    def warm_up(self) -> None:
        """Build the server's index before timing starts (it loads lazily on first search)."""
        if self._mcp and any(i.name == "search_similar_issues" for i in self._mcp_infos):
            as_of = f"{self._profile.windows.eval_start.isoformat()}T00:00:00+00:00"
            self._mcp.call_tool("search_similar_issues", {"query": "warm up", "as_of": as_of})

    def _toolbox(self, issue: IssueSnapshot, loaded: set[str]) -> Toolbox:
        tools: list[Tool] = []
        if self._mcp is not None:
            tools += mcp_tools(self._mcp, self._mcp_infos, {"as_of": issue.created_at.isoformat()})
        tools += skill_tools(self._skills, loaded)
        return Toolbox(tools, max_result_chars=self._agent.max_tool_result_chars)

    def triage(self, issue: IssueSnapshot) -> TriageResult:
        started = time.perf_counter()
        trace = self._tracer.issue(
            issue.issue_ref,
            metadata={
                "prompt_version": PROMPT_VERSION,
                "model": self._llm.model,
                "skills": sorted(self._skills.skills),
                "tools": [i.name for i in self._mcp_infos],
            },
        )
        loaded: set[str] = set()
        messages = [
            Message(role="system", content=self._system),
            Message(
                role="user",
                content=issue_prompt(
                    issue, self._profile, self._family_labels, self._max_body_chars
                ),
            ),
        ]
        base = LLMRequest(
            model=self._llm.model,
            route=self._llm.route,
            messages=(),
            max_tokens=self._llm.max_tokens,
            temperature=self._llm.temperature,
            seed=self._llm.seed,
            reasoning=self._llm.reasoning,
        )
        stop_reason = "exception"
        answer: dict[str, Any] | None = None
        totals: dict[str, Any] = {}
        try:
            outcome = run_loop(
                client=self._client,
                base=base,
                messages=messages,
                toolbox=self._toolbox(issue, loaded),
                submit=submit_tool(AgentAnswer, SUBMIT_DESCRIPTION),
                answer_type=AgentAnswer,
                budget=BudgetTracker(self._agent.budget),
                context_limit_tokens=self._agent.context_limit_tokens,
                max_validation_retries=self._agent.max_validation_retries,
                trace=trace,
            )
            stop_reason = outcome.stop_reason
            answer = outcome.answer.model_dump() if outcome.answer else None
            totals = {
                "forced": outcome.forced,
                "steps": outcome.steps,
                "tool_calls": outcome.tool_calls,
                "tool_errors": outcome.tool_errors,
                "validation_errors": outcome.validation_errors,
                "compactions": outcome.compactions,
                "skills_loaded": sorted(loaded),
                "cost_usd": outcome.cost_usd,
            }
            latency_ms = round((time.perf_counter() - started) * 1000)
            return self._result(issue, outcome, trace.trace_id, latency_ms)
        finally:
            trace.finish(stop_reason=stop_reason, answer=answer, totals=totals)

    def _result(
        self,
        issue: IssueSnapshot,
        outcome: LoopOutcome[AgentAnswer],
        trace_id: str,
        latency_ms: int,
    ) -> TriageResult:
        base = TriageResult(
            issue_ref=issue.issue_ref,
            trace_id=trace_id,
            cost_usd=outcome.cost_usd,
            latency_ms=latency_ms,
            tokens_in=outcome.tokens_in,
            tokens_out=outcome.tokens_out,
            steps=outcome.steps,
            tool_calls=outcome.tool_calls,
            stop_reason=outcome.stop_reason,
            error=None if outcome.answer else outcome.stop_reason,
        )
        a = outcome.answer
        if a is None:
            return base
        kept = [g for g in a.labels if g.label in self._allowed_labels]
        component = a.component if a.component in self._components else None
        # A duplicate's original must be older, and older issues have smaller numbers.
        earlier = [n for n in (a.duplicate_of, *a.duplicate_candidates) if n and n < issue.number]
        duplicate_of = a.duplicate_of if a.duplicate_of in earlier else None
        return base.model_copy(
            update={
                "labels": _dedupe([g.label for g in kept]),
                "label_confidence": {g.label: g.confidence for g in kept},
                "rejected_labels": _dedupe(
                    [g.label for g in a.labels if g.label not in self._allowed_labels]
                ),
                "component": component,
                "component_confidence": a.component_confidence if component else None,
                "component_candidates": _dedupe(
                    [c for c in (component, *a.component_top3) if c in self._components]
                ),
                "suggested_owners": _dedupe(a.suggested_owners),
                "duplicate_of": duplicate_of,
                "duplicate_confidence": a.duplicate_confidence if duplicate_of else None,
                "duplicate_candidates": _dedupe(earlier),
                "needs_info": a.needs_info,
                "needs_info_confidence": a.needs_info_confidence,
                "missing_info": a.missing_info,
                "triage_comment": a.triage_comment,
                "decided_by": dict.fromkeys(_DECISIONS, "agent"),
            }
        )
