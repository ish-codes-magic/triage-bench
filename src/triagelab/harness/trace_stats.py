"""Agent system metrics from a run's traces (AGENTS.md §12.2).

Reads `predictions.jsonl` for the final prediction per issue and keeps only the trace
events those predictions point to (by `trace_id`), so an issue that was interrupted and
re-run counts once, with its final attempt.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import BaseModel

from triagelab.data.storage import read_jsonl
from triagelab.eval.metrics import percentile
from triagelab.triage import TriageResult


class ToolUsage(BaseModel):
    calls: int
    errors: int
    issues: int  # how many issues called it at least once


class AgentStats(BaseModel):
    issues: int
    stop_reasons: dict[str, int]
    forced: dict[str, int]  # budget limit that forced the final answer
    steps_mean: float
    steps_p95: float
    tool_calls_mean: float
    tool_calls_max: int
    tools: dict[str, ToolUsage]
    skill_load_rate: float  # share of issues that called load_skill
    issues_with_validation_errors: int
    compactions: int
    tokens_in_mean: float
    tokens_out_mean: float
    reasoning_tokens_mean: float
    cost_per_issue: float
    latency_p50_s: float
    latency_p95_s: float


def load_events(run_dir: Path) -> tuple[list[TriageResult], dict[str, list[dict[str, Any]]]]:
    latest = {p.issue_ref: p for p in read_jsonl(run_dir / "predictions.jsonl", TriageResult)}
    predictions = list(latest.values())
    wanted = {p.trace_id for p in predictions}
    events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    path = run_dir / "traces.jsonl"
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                event = json.loads(line)
                if event["trace_id"] in wanted:
                    events[event["trace_id"]].append(event)
    return predictions, events


def agent_stats(run_dir: Path) -> AgentStats:
    predictions, events = load_events(run_dir)
    n = max(len(predictions), 1)
    calls: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    per_issue: defaultdict[str, set[str]] = defaultdict(set)
    forced: Counter[str] = Counter()
    reasoning = 0
    validation = compactions = 0
    for trace_id, evs in events.items():
        for e in evs:
            if e["event"] == "tool":
                calls[e["name"]] += 1
                errors[e["name"]] += bool(e["is_error"])
                per_issue[e["name"]].add(trace_id)
            elif e["event"] == "llm":
                reasoning += int(e.get("reasoning_tokens") or 0)
            elif e["event"] == "compaction":
                compactions += 1
            elif e["event"] == "end" and e.get("forced"):
                forced[str(e["forced"])] += 1
        validation += any(e["event"] == "validation_error" for e in evs)
    latencies = [p.latency_ms / 1000 for p in predictions]
    steps = [float(p.steps) for p in predictions]
    return AgentStats(
        issues=len(predictions),
        stop_reasons=dict(Counter(p.stop_reason or p.error or "?" for p in predictions)),
        forced=dict(forced),
        steps_mean=mean(steps) if steps else 0.0,
        steps_p95=percentile(steps, 95) if steps else 0.0,
        tool_calls_mean=mean(p.tool_calls for p in predictions) if predictions else 0.0,
        tool_calls_max=max((p.tool_calls for p in predictions), default=0),
        tools={
            name: ToolUsage(calls=calls[name], errors=errors[name], issues=len(per_issue[name]))
            for name in sorted(calls)
        },
        skill_load_rate=len(per_issue["load_skill"]) / n,
        issues_with_validation_errors=validation,
        compactions=compactions,
        tokens_in_mean=sum(p.tokens_in for p in predictions) / n,
        tokens_out_mean=sum(p.tokens_out for p in predictions) / n,
        reasoning_tokens_mean=reasoning / n,
        cost_per_issue=sum(p.cost_usd for p in predictions) / n,
        latency_p50_s=percentile(latencies, 50) if latencies else 0.0,
        latency_p95_s=percentile(latencies, 95) if latencies else 0.0,
    )


def render(stats: AgentStats, run_id: str) -> str:
    tool_rows = "\n".join(
        f"| {name} | {u.calls} | {u.calls / max(stats.issues, 1):.2f} | {u.issues} | {u.errors} |"
        for name, u in stats.tools.items()
    )
    reasons = ", ".join(f"{k} {v}" for k, v in sorted(stats.stop_reasons.items()))
    forced = ", ".join(f"{k} {v}" for k, v in sorted(stats.forced.items())) or "none"
    return (
        f"# Agent run {run_id}\n\n"
        f"- **Issues:** {stats.issues}; stop reasons: {reasons}\n"
        f"- **Forced final answers:** {forced}\n"
        f"- **Steps per issue:** mean {stats.steps_mean:.1f}, p95 {stats.steps_p95:.0f}\n"
        f"- **Tool calls per issue:** mean {stats.tool_calls_mean:.1f}, "
        f"max {stats.tool_calls_max}\n"
        f"- **Skill load rate:** {stats.skill_load_rate:.0%} of issues called `load_skill`\n"
        f"- **Validation errors:** {stats.issues_with_validation_errors} issues; "
        f"compactions: {stats.compactions}\n"
        f"- **Tokens per issue:** {stats.tokens_in_mean:,.0f} in, {stats.tokens_out_mean:,.0f} out "
        f"({stats.reasoning_tokens_mean:,.0f} reasoning)\n"
        f"- **Cost per issue:** ${stats.cost_per_issue:.5f}; "
        f"latency p50 {stats.latency_p50_s:.0f} s, p95 {stats.latency_p95_s:.0f} s\n\n"
        "| tool | calls | per issue | issues using it | errors |\n|---|---|---|---|---|\n"
        f"{tool_rows}\n"
    )
