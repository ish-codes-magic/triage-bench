"""Agent system metrics from traces: only the final attempt of each issue counts."""

import json
from pathlib import Path
from typing import Any

import pytest

from triagelab.eval.failure_tagger import TaggedFailure, write_failures
from triagelab.harness.trace_stats import agent_stats, render
from triagelab.triage import TriageResult


def write_run(run_dir: Path) -> None:
    predictions = [
        TriageResult(
            issue_ref="o/r#1", trace_id="t1", steps=3, tool_calls=2, stop_reason="submitted",
            cost_usd=0.002, latency_ms=10_000, tokens_in=5000, tokens_out=100,
        ),
        TriageResult(
            issue_ref="o/r#2", trace_id="t2", steps=12, tool_calls=11, stop_reason="submitted",
            cost_usd=0.006, latency_ms=30_000, tokens_in=15000, tokens_out=300,
        ),
    ]  # fmt: skip
    (run_dir / "predictions.jsonl").write_text(
        "".join(p.model_dump_json() + "\n" for p in predictions), encoding="utf-8"
    )

    def tool(trace: str, name: str, error: bool = False) -> dict[str, Any]:
        return {"trace_id": trace, "event": "tool", "name": name, "is_error": error}

    events = [
        tool("t1", "load_skill"),
        tool("t1", "search_similar_issues"),
        {"trace_id": "t1", "event": "llm", "reasoning_tokens": 40},
        tool("t2", "search_similar_issues"),
        tool("t2", "get_issue", error=True),
        {"trace_id": "t2", "event": "validation_error"},
        {"trace_id": "t2", "event": "compaction"},
        {"trace_id": "t2", "event": "end", "forced": "max_steps"},
        # An interrupted first attempt at issue 2: not referenced by any prediction.
        tool("t2-old", "search_code"),
    ]
    (run_dir / "traces.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
    )


def test_stats_count_only_final_attempts(tmp_path: Path) -> None:
    write_run(tmp_path)
    stats = agent_stats(tmp_path)
    assert stats.issues == 2
    assert set(stats.tools) == {"load_skill", "search_similar_issues", "get_issue"}
    assert stats.tools["search_similar_issues"].issues == 2
    assert stats.tools["get_issue"].errors == 1
    assert stats.skill_load_rate == pytest.approx(0.5)
    assert stats.forced == {"max_steps": 1}
    assert stats.issues_with_validation_errors == 1
    assert stats.compactions == 1
    assert stats.steps_mean == pytest.approx(7.5)
    assert stats.cost_per_issue == pytest.approx(0.004)
    assert stats.reasoning_tokens_mean == pytest.approx(20)
    assert "Skill load rate:** 50%" in render(stats, "run")


def test_tagged_runs_report_failure_category_counts(tmp_path: Path) -> None:
    write_run(tmp_path)
    assert agent_stats(tmp_path).failure_categories is None
    tagged = [
        TaggedFailure(
            issue_ref=f"o/r#{n}",
            tasks=["T1"],
            details={"T1": "x"},
            categories=["retrieval miss"],
            reasoning="r",
            cost_usd=0.0,
        )
        for n in (1, 2)
    ]
    write_failures(tmp_path, tagged, taxonomy_version=0)
    stats = agent_stats(tmp_path)
    assert stats.failure_categories == {"retrieval miss": 2}
    assert "| retrieval miss | 2 |" in render(stats, "run")
