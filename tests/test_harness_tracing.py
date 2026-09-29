"""JSONL traces and OpenTelemetry spans (OpenInference attributes) for one issue."""

import json
from pathlib import Path
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanContext, StatusCode

from triagelab.cost import Usage
from triagelab.harness.tools import ToolResult
from triagelab.harness.tracing import RunTracer
from triagelab.llm_client import LLMRequest, LLMResponse, Message, ToolCall, ToolSpec

CALL = ToolCall(id="c1", name="search_code", arguments='{"query": "zipfile"}')
REQUEST = LLMRequest(
    model="openrouter/qwen/qwen3.5-9b",
    messages=(Message(role="system", content="sys"), Message(role="user", content="issue")),
    max_tokens=100,
    tools=(ToolSpec(name="search_code", description="d", parameters={"type": "object"}),),
)
RESPONSE = LLMResponse(
    text="",
    model=REQUEST.model,
    resolved_model=None,
    usage=Usage(tokens_in=120, tokens_out=30, reasoning_tokens=20),
    tool_calls=(CALL,),
    reasoning_text="look at the code",
    cost_usd=0.001,
    original_cost_usd=0.001,
    cache_hit=False,
    latency_ms=250,
    attempts=1,
)


def tool_result(is_error: bool = False) -> ToolResult:
    return ToolResult(
        call_id="c1",
        name="search_code",
        kind="mcp",
        arguments={"query": "zipfile"},
        output="Lib/zipfile.py:1",
        is_error=is_error,
        truncated=False,
        latency_ms=40,
    )


def run_one(tracer: RunTracer, *, tool_error: bool = False) -> str:
    t = tracer.issue("o/r#1", metadata={"config": "test"})
    t.llm_call(1, REQUEST, list(REQUEST.messages), RESPONSE)
    t.tool_call(1, tool_result(tool_error))
    t.finish(stop_reason="submitted", answer={"labels": []}, totals={"steps": 1})
    return t.trace_id


def context(span: ReadableSpan) -> SpanContext:
    assert span.context is not None
    return span.context


def events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_jsonl_records_the_whole_issue(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    tracer = RunTracer(run_id="r1", jsonl_path=path)
    trace_id = run_one(tracer)
    tracer.close()
    evs = events(path)
    assert [e["event"] for e in evs] == ["start", "llm", "tool", "end"]
    assert {e["trace_id"] for e in evs} == {trace_id}
    assert len(trace_id) == 32
    llm = evs[1]
    assert llm["tool_calls"][0]["name"] == "search_code"
    assert llm["reasoning"] == "look at the code"
    assert [m["role"] for m in llm["new_messages"]] == ["system", "user"]
    assert evs[2]["output"] == "Lib/zipfile.py:1"
    assert evs[3]["stop_reason"] == "submitted"


def test_spans_form_one_tree_with_openinference_attributes(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    tracer = RunTracer(run_id="r1", jsonl_path=tmp_path / "t.jsonl", exporter=exporter)
    trace_id = run_one(tracer, tool_error=True)
    tracer.close()
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) == {"triage o/r#1", "llm step 1", "tool search_code"}
    root, llm, tool = spans["triage o/r#1"], spans["llm step 1"], spans["tool search_code"]
    assert {format(context(s).trace_id, "032x") for s in spans.values()} == {trace_id}
    assert llm.parent is not None
    assert tool.parent is not None
    assert llm.parent.span_id == tool.parent.span_id == context(root).span_id

    assert root.attributes is not None
    assert llm.attributes is not None
    assert tool.attributes is not None
    assert root.attributes["openinference.span.kind"] == "AGENT"
    assert root.attributes["session.id"] == "r1"
    assert llm.attributes["openinference.span.kind"] == "LLM"
    assert llm.attributes["llm.token_count.prompt"] == 120
    assert llm.attributes["llm.token_count.completion_details.reasoning"] == 20
    assert llm.attributes["llm.input_messages.1.message.content"] == "issue"
    name_key = "llm.output_messages.0.message.tool_calls.0.tool_call.function.name"
    assert llm.attributes[name_key] == "search_code"
    assert tool.attributes["tool.name"] == "search_code"
    assert tool.status.status_code == StatusCode.ERROR  # tool errors show red in the viewer
    # Child spans carry their measured duration, not the time it took to record them.
    assert llm.end_time is not None
    assert llm.start_time is not None
    assert llm.end_time - llm.start_time >= 250 * 1_000_000


def test_no_exporter_means_no_spans_but_still_a_trace_id(tmp_path: Path) -> None:
    tracer = RunTracer(run_id="r1", jsonl_path=None)
    assert len(run_one(tracer)) == 32  # works without a file or a viewer
    tracer.close()
