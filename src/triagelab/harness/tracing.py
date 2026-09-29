"""Traces for every agent run: local JSONL (source of truth) plus optional OpenTelemetry.

JSONL: one event per line in `runs/<run_id>/traces.jsonl`, each tagged with the issue's
`trace_id`: start (the prompts), every model call (text, reasoning, tool calls, tokens,
cost), every tool call (arguments and exactly what the model saw), compactions,
validation errors, and the end (stop reason and answer). The conversation can be
rebuilt from these events, which is what the M5 trace-review tool reads.

OpenTelemetry: when an OTLP endpoint is configured (e.g. Phoenix at
http://localhost:6006/v1/traces), the same run becomes one AGENT span per issue with an
LLM span per model call and a TOOL span per tool call, using OpenInference attribute
names (github.com/Arize-ai/openinference, spec/semantic_conventions.md). Spans are
recorded after each call with its measured start and end times.
"""

import json
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openinference.semconv.resource import ResourceAttributes
from openinference.semconv.trace import (
    MessageAttributes,
    OpenInferenceMimeTypeValues,
    OpenInferenceSpanKindValues,
    SpanAttributes,
    ToolCallAttributes,
)
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Span, Status, StatusCode

from triagelab.harness.tools import ToolResult
from triagelab.llm_client import LLMRequest, LLMResponse, Message

# Span attributes are for browsing; the JSONL keeps everything in full.
_MAX_ATTR_CHARS = 8_000
_JSON = OpenInferenceMimeTypeValues.JSON.value
_KIND = SpanAttributes.OPENINFERENCE_SPAN_KIND


def _clip(text: str) -> str:
    return text if len(text) <= _MAX_ATTR_CHARS else text[:_MAX_ATTR_CHARS] + " [...]"


def _message_attributes(prefix: str, messages: list[Message]) -> dict[str, Any]:
    """OpenInference's flattened form: <prefix>.<i>.message.role, ... (zero-based)."""
    attrs: dict[str, Any] = {}
    for i, m in enumerate(messages):
        base = f"{prefix}.{i}."
        attrs[base + MessageAttributes.MESSAGE_ROLE] = m.role
        attrs[base + MessageAttributes.MESSAGE_CONTENT] = _clip(m.content)
        if m.tool_call_id:
            attrs[base + MessageAttributes.MESSAGE_TOOL_CALL_ID] = m.tool_call_id
        for j, call in enumerate(m.tool_calls):
            tc = f"{base}{MessageAttributes.MESSAGE_TOOL_CALLS}.{j}."
            attrs[tc + ToolCallAttributes.TOOL_CALL_ID] = call.id
            attrs[tc + ToolCallAttributes.TOOL_CALL_FUNCTION_NAME] = call.name
            attrs[tc + ToolCallAttributes.TOOL_CALL_FUNCTION_ARGUMENTS_JSON] = call.arguments
    return attrs


class RunTracer:
    """Owns the run's JSONL file and (optionally) an OpenTelemetry pipeline. Thread-safe."""

    def __init__(
        self,
        *,
        run_id: str,
        jsonl_path: Path | None,
        otlp_endpoint: str | None = None,
        project: str = "triagelab",
        exporter: SpanExporter | None = None,  # tests pass an in-memory exporter
    ) -> None:
        self.run_id = run_id
        self._jsonl_path = jsonl_path
        self._lock = threading.Lock()
        self._provider: TracerProvider | None = None
        if exporter is not None or otlp_endpoint is not None:
            # A private provider, not the global one: tracing is scoped to this run.
            self._provider = TracerProvider(
                resource=Resource.create(
                    {ResourceAttributes.PROJECT_NAME: project, "service.name": "triagelab"}
                )
            )
            if exporter is not None:
                self._provider.add_span_processor(SimpleSpanProcessor(exporter))
            else:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                self._provider.add_span_processor(
                    BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
                )

    def write(self, record: dict[str, Any]) -> None:
        if self._jsonl_path is None:
            return
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with self._lock, self._jsonl_path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(line)

    def issue(self, issue_ref: str, *, metadata: dict[str, Any]) -> "IssueTrace":
        tracer = self._provider.get_tracer("triagelab.harness") if self._provider else None
        return IssueTrace(self, tracer, issue_ref, metadata)

    def close(self) -> None:
        """Flush pending spans; call once at the end of the run."""
        if self._provider is not None:
            self._provider.shutdown()


class IssueTrace:
    """The trace of one issue: JSONL events and, if enabled, one span tree."""

    def __init__(
        self,
        run: RunTracer,
        tracer: trace.Tracer | None,
        issue_ref: str,
        metadata: dict[str, Any],
    ) -> None:
        self._run = run
        self._tracer = tracer
        self.issue_ref = issue_ref
        self._root: Span | None = None
        self._ctx: Context | None = None
        if tracer is not None:
            self._root = tracer.start_span(
                f"triage {issue_ref}",
                attributes={
                    _KIND: OpenInferenceSpanKindValues.AGENT.value,
                    SpanAttributes.SESSION_ID: run.run_id,
                    SpanAttributes.INPUT_VALUE: issue_ref,
                    SpanAttributes.METADATA: json.dumps(metadata, default=str),
                },
            )
            self._ctx = trace.set_span_in_context(self._root)
            self.trace_id = format(self._root.get_span_context().trace_id, "032x")
        else:
            self.trace_id = uuid.uuid4().hex
        self.event("start", **metadata)

    def event(self, event: str, **fields: Any) -> None:
        self._run.write(
            {
                "run_id": self._run.run_id,
                "trace_id": self.trace_id,
                "issue_ref": self.issue_ref,
                "at": datetime.now(UTC).isoformat(),
                "event": event,
                **fields,
            }
        )

    def _child(self, name: str, latency_ms: int, attributes: dict[str, Any]) -> Span | None:
        if self._tracer is None:
            return None
        end = time.time_ns()
        return self._tracer.start_span(
            name,
            context=self._ctx,
            start_time=end - latency_ms * 1_000_000,
            attributes=attributes,
        )

    def llm_call(
        self, step: int, request: LLMRequest, new_messages: list[Message], response: LLMResponse
    ) -> None:
        """`new_messages`: what this call added to the conversation (the JSONL keeps each
        message once; spans get the full input for the viewer)."""
        usage = response.usage
        self.event(
            "llm",
            step=step,
            model=request.model,
            tool_choice=request.tool_choice,
            new_messages=[m.model_dump(mode="json") for m in new_messages],
            text=response.text,
            reasoning=response.reasoning_text,
            tool_calls=[c.model_dump() for c in response.tool_calls],
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            reasoning_tokens=usage.reasoning_tokens,
            cost_usd=response.original_cost_usd,
            cache_hit=response.cache_hit,
            latency_ms=response.latency_ms,
        )
        output = Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
        span = self._child(
            f"llm step {step}",
            response.latency_ms,
            {
                _KIND: OpenInferenceSpanKindValues.LLM.value,
                SpanAttributes.LLM_MODEL_NAME: request.model,
                SpanAttributes.LLM_PROVIDER: request.route.tag if request.route else "",
                SpanAttributes.LLM_TOKEN_COUNT_PROMPT: usage.tokens_in,
                SpanAttributes.LLM_TOKEN_COUNT_COMPLETION: usage.tokens_out,
                SpanAttributes.LLM_TOKEN_COUNT_TOTAL: usage.tokens_in + usage.tokens_out,
                SpanAttributes.LLM_TOKEN_COUNT_COMPLETION_DETAILS_REASONING: usage.reasoning_tokens,
                SpanAttributes.LLM_COST_TOTAL: response.original_cost_usd,
                SpanAttributes.LLM_INVOCATION_PARAMETERS: json.dumps(
                    {
                        "max_tokens": request.max_tokens,
                        "temperature": request.temperature,
                        "reasoning": request.reasoning,
                        "tool_choice": request.tool_choice,
                    }
                ),
                SpanAttributes.METADATA: json.dumps({"cache_hit": response.cache_hit}),
                **_message_attributes(SpanAttributes.LLM_INPUT_MESSAGES, list(request.messages)),
                **_message_attributes(SpanAttributes.LLM_OUTPUT_MESSAGES, [output]),
                **{
                    f"{SpanAttributes.LLM_TOOLS}.{i}.tool.json_schema": json.dumps(t.model_dump())
                    for i, t in enumerate(request.tools)
                },
            },
        )
        if span is not None:
            span.end()

    def tool_call(self, step: int, result: ToolResult) -> None:
        self.event("tool", step=step, **result.model_dump(mode="json"))
        span = self._child(
            f"tool {result.name}",
            result.latency_ms,
            {
                _KIND: OpenInferenceSpanKindValues.TOOL.value,
                SpanAttributes.TOOL_NAME: result.name,
                SpanAttributes.TOOL_PARAMETERS: json.dumps(result.arguments or {}),
                SpanAttributes.INPUT_VALUE: json.dumps(result.arguments or {}),
                SpanAttributes.INPUT_MIME_TYPE: _JSON,
                SpanAttributes.OUTPUT_VALUE: _clip(result.output),
            },
        )
        if span is not None:
            if result.is_error:
                span.set_status(Status(StatusCode.ERROR, _clip(result.output)))
            span.end()

    def finish(
        self, *, stop_reason: str, answer: dict[str, Any] | None, totals: dict[str, Any]
    ) -> None:
        self.event("end", stop_reason=stop_reason, answer=answer, **totals)
        if self._root is not None:
            self._root.set_attribute(SpanAttributes.OUTPUT_VALUE, json.dumps(answer))
            self._root.set_attribute(SpanAttributes.OUTPUT_MIME_TYPE, _JSON)
            self._root.set_attribute("triage.stop_reason", stop_reason)
            if stop_reason != "submitted":
                self._root.set_status(Status(StatusCode.ERROR, stop_reason))
            self._root.end()
