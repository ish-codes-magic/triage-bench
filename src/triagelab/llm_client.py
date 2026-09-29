"""Provider-agnostic model client: cache, budget, retries and cost around every call.

The provider itself hides behind the small `CompletionBackend` protocol. The LiteLLM
adapter is one implementation; tests use a fake one, and CI will replay recorded
responses through the cache. This module never imports a provider SDK.
"""

import random
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from triagelab.cache import DiskCache
from triagelab.config import ProviderRoute, ReasoningEffort, RetryConfig
from triagelab.cost import BudgetGuard, PriceTable, Usage, cost_usd, worst_case_cost_usd
from triagelab.hashing import canonical_json, stable_hash
from triagelab.ledger import SpendEntry, SpendLedger
from triagelab.retry import UniformSource, backoff_delay, call_with_retries

# Bump to invalidate every cached response when the cached format or semantics change.
CACHE_FORMAT_VERSION = 1

# Headroom for tokens we never see as text: chat-template markers, provider-injected
# system prompts for structured output or tool use, and per-message framing.
_PROMPT_OVERHEAD_TOKENS = 1_000
_PER_MESSAGE_OVERHEAD_TOKENS = 16


def _omit_empty(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Drop optional tool fields while they are unused.

    Tool calling was added after E1's responses were cached. Omitting the new fields
    when empty keeps every tool-free request serializing, and so hashing, exactly as
    before: old cache entries (and CI cassettes) stay valid.
    """
    return {k: v for k, v in data.items() if k not in keys or v not in (None, [], ())}


class ToolSpec(BaseModel):
    """A function the model may call: name, description and a JSON-schema for arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str
    parameters: dict[str, Any]


class ToolCall(BaseModel):
    """One call the model asked for. `arguments` stays the raw JSON text the model wrote,
    so the harness can report a parse error back to it instead of losing the call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    arguments: str


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ToolCall, ...] = ()  # assistant turns that call tools
    tool_call_id: str | None = None  # tool results: which call they answer

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return _omit_empty(handler(self), "tool_calls", "tool_call_id")


class LLMRequest(BaseModel):
    """Everything that can change a model's answer, and nothing that can't.

    That split is what makes `cache_key` correct: timeouts and retry settings are
    deliberately absent, while `sample` is present so that k repeated samples for the
    consistency study get k distinct cache entries instead of one replayed k times.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    route: ProviderRoute | None = None
    messages: tuple[Message, ...]
    max_tokens: int = Field(gt=0)
    temperature: float | None = None
    seed: int | None = None
    response_schema: dict[str, Any] | None = None
    schema_name: str | None = None
    reasoning: ReasoningEffort = "default"
    sample: int = Field(default=0, ge=0)
    tools: tuple[ToolSpec, ...] = ()
    # None = provider default ("auto"); "none" = no tools; any other value forces that tool.
    tool_choice: str | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return _omit_empty(handler(self), "tools", "tool_choice")

    def price_key(self) -> str:
        """The price-table key: the model, plus the pinned provider when there is one.

        The same OpenRouter model costs different amounts on different providers.
        """
        return f"{self.model}@{self.route.tag}" if self.route else self.model

    def cache_key(self) -> str:
        return stable_hash({"v": CACHE_FORMAT_VERSION, **self.model_dump(mode="json")})


class Completion(BaseModel):
    """What a backend returns: provider output normalized to our types."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    resolved_model: str | None
    usage: Usage
    litellm_cost_usd: float | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    reasoning_text: str = ""  # the model's visible thinking, kept for traces


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    model: str
    resolved_model: str | None
    usage: Usage
    tool_calls: tuple[ToolCall, ...] = ()
    reasoning_text: str = ""
    cost_usd: float = Field(description="Money spent by *this* call: 0.0 on a cache hit.")
    original_cost_usd: float = Field(description="What the response cost when first produced.")
    cache_hit: bool
    latency_ms: int
    attempts: int


class CompletionBackend(Protocol):
    def complete(self, request: LLMRequest, *, timeout_s: float) -> Completion: ...
    def is_retryable(self, err: Exception) -> bool: ...
    def retry_after_s(self, err: Exception) -> float | None: ...


class CassetteMissError(RuntimeError):
    """Replay-only mode found no recorded response for a request.

    Deliberately not retryable and not an "infrastructure" failure: in CI it means a
    prompt, schema or tool output changed, and the cassettes must be re-recorded.
    """


class ReplayOnlyBackend:
    """The backend for replay-only runs: every call that reaches it is a cache miss."""

    def complete(self, request: LLMRequest, *, timeout_s: float) -> Completion:
        raise CassetteMissError(
            f"no recorded response for request {request.cache_key()[:16]} "
            f"({request.model}, {len(request.messages)} messages); re-record the cassettes"
        )

    def is_retryable(self, err: Exception) -> bool:
        return False

    def retry_after_s(self, err: Exception) -> float | None:
        return None


def prompt_tokens_upper_bound(request: LLMRequest) -> int:
    """A prompt-size bound that can only over-count, used by the budget check.

    Modern tokenizers (byte-level BPE, or SentencePiece with byte fallback) never emit
    more than one token per UTF-8 byte, so the byte count of everything we send is a
    true ceiling. It over-estimates English by roughly 3-4x, which is harmless for a
    safety check, and it needs no tokenizer download, network, or provider-specific code.
    """
    text_bytes = sum(len(m.content.encode("utf-8")) for m in request.messages)
    call_bytes = sum(
        len(c.name.encode("utf-8")) + len(c.arguments.encode("utf-8"))
        for m in request.messages
        for c in m.tool_calls
    )
    schema = request.response_schema
    schema_bytes = len(canonical_json(schema).encode("utf-8")) if schema else 0
    tool_bytes = sum(len(canonical_json(t.model_dump()).encode("utf-8")) for t in request.tools)
    return (
        text_bytes
        + call_bytes
        + schema_bytes
        + tool_bytes
        + _PER_MESSAGE_OVERHEAD_TOKENS * len(request.messages)
        + _PROMPT_OVERHEAD_TOKENS
    )


class CallStats(BaseModel):
    """Running totals for one client (one run); written to the run's cost.json."""

    calls: int = 0
    cache_hits: int = 0
    retries: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    saved_by_cache_usd: float = 0.0


class LLMClient:
    """Thread-safe: the eval runner calls one client from several worker threads."""

    def __init__(
        self,
        *,
        backend: CompletionBackend,
        prices: PriceTable,
        guard: BudgetGuard,
        ledger: SpendLedger,
        cache: DiskCache | None,
        run_id: str,
        retry: RetryConfig,
        timeout_s: float,
        rng: UniformSource | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.perf_counter,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._backend = backend
        self._prices = prices
        self._guard = guard
        self._ledger = ledger
        self._cache = cache
        self._run_id = run_id
        self._retry = retry
        self._timeout_s = timeout_s
        self._rng: UniformSource = rng if rng is not None else random.Random()
        self._sleep = sleep
        self._clock = clock
        self._now = now
        self._lock = threading.Lock()  # guards stats and ledger writes
        self.stats = CallStats()

    def complete(self, request: LLMRequest) -> LLMResponse:
        price = self._prices.price_for(request.price_key())  # unpriced: refuse before anything
        key = request.cache_key()
        started = self._clock()

        if self._cache is not None and (hit := self._cache.get(key)) is not None:
            cached = LLMResponse.model_validate(hit)
            with self._lock:
                self.stats.calls += 1
                self.stats.cache_hits += 1
                self.stats.saved_by_cache_usd += cached.original_cost_usd
            return cached.model_copy(
                update={"cache_hit": True, "cost_usd": 0.0, "latency_ms": self._ms_since(started)}
            )

        projected = worst_case_cost_usd(
            prompt_tokens_upper_bound(request), request.max_tokens, price
        )
        self._guard.reserve(projected)

        attempts = 0

        def attempt() -> Completion:
            nonlocal attempts
            attempts += 1
            return self._backend.complete(request, timeout_s=self._timeout_s)

        try:
            completion = call_with_retries(
                attempt,
                max_attempts=self._retry.max_attempts,
                is_retryable=self._backend.is_retryable,
                delay=lambda n: backoff_delay(
                    n,
                    base_s=self._retry.base_delay_s,
                    cap_s=self._retry.max_delay_s,
                    rng=self._rng,
                ),
                retry_after=self._backend.retry_after_s,
                sleep=self._sleep,
            )
        except BaseException:
            self._guard.release(projected)  # failed calls are not billed
            raise
        spent = cost_usd(completion.usage, price)
        self._guard.settle(projected, spent)
        with self._lock:
            self._ledger.record(
                SpendEntry(
                    at=self._now(),
                    run_id=self._run_id,
                    model=request.price_key(),
                    resolved_model=completion.resolved_model,
                    tokens_in=completion.usage.tokens_in,
                    tokens_out=completion.usage.tokens_out,
                    cached_tokens_in=completion.usage.cached_tokens_in,
                    cost_usd=spent,
                    litellm_cost_usd=completion.litellm_cost_usd,
                )
            )
        response = LLMResponse(
            text=completion.text,
            model=request.model,
            resolved_model=completion.resolved_model,
            usage=completion.usage,
            tool_calls=completion.tool_calls,
            reasoning_text=completion.reasoning_text,
            cost_usd=spent,
            original_cost_usd=spent,
            cache_hit=False,
            latency_ms=self._ms_since(started),
            attempts=attempts,
        )
        with self._lock:
            self.stats.calls += 1
            self.stats.retries += attempts - 1
            self.stats.tokens_in += completion.usage.tokens_in
            self.stats.tokens_out += completion.usage.tokens_out
            self.stats.reasoning_tokens += completion.usage.reasoning_tokens
            self.stats.cost_usd += spent
        if self._cache is not None:
            self._cache.put(key, response.model_dump(mode="json"))
        return response

    def complete_structured[M: BaseModel](
        self, request: LLMRequest, schema: type[M]
    ) -> tuple[M, LLMResponse]:
        """Ask for JSON matching `schema` and validate it.

        Raises pydantic.ValidationError on a malformed answer. Retrying with the error fed
        back to the model is the agent harness's job (M4), not the transport's.
        """
        typed_request = request.model_copy(
            update={"response_schema": schema.model_json_schema(), "schema_name": schema.__name__}
        )
        response = self.complete(typed_request)
        return schema.model_validate_json(response.text), response

    def _ms_since(self, started: float) -> int:
        return round((self._clock() - started) * 1000)
