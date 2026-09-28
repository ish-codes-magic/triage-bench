"""Provider-agnostic model client: cache, budget, retries and cost around every call.

The provider itself hides behind the small `CompletionBackend` protocol. The LiteLLM
adapter is one implementation; tests use a fake one, and CI will replay recorded
responses through the cache. This module never imports a provider SDK.
"""

import random
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from triagelab.cache import DiskCache
from triagelab.config import RetryConfig
from triagelab.cost import BudgetGuard, PriceTable, Usage, cost_usd, worst_case_cost_usd
from triagelab.hashing import stable_hash
from triagelab.ledger import SpendEntry, SpendLedger
from triagelab.retry import UniformSource, backoff_delay, call_with_retries

# Bump to invalidate every cached response when the cached format or semantics change.
CACHE_FORMAT_VERSION = 1


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    """Everything that can change a model's answer, and nothing that can't.

    That split is what makes `cache_key` correct: timeouts and retry settings are
    deliberately absent, while `sample` is present so that k repeated samples for the
    consistency study get k distinct cache entries instead of one replayed k times.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    messages: tuple[Message, ...]
    max_tokens: int = Field(gt=0)
    temperature: float | None = None
    seed: int | None = None
    response_schema: dict[str, Any] | None = None
    schema_name: str | None = None
    sample: int = Field(default=0, ge=0)

    def cache_key(self) -> str:
        return stable_hash({"v": CACHE_FORMAT_VERSION, **self.model_dump(mode="json")})


class Completion(BaseModel):
    """What a backend returns: provider output normalized to our types."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    resolved_model: str | None
    usage: Usage
    litellm_cost_usd: float | None = None


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    model: str
    resolved_model: str | None
    usage: Usage
    cost_usd: float = Field(description="Money spent by *this* call: 0.0 on a cache hit.")
    original_cost_usd: float = Field(description="What the response cost when first produced.")
    cache_hit: bool
    latency_ms: int
    attempts: int


class CompletionBackend(Protocol):
    def complete(self, request: LLMRequest, *, timeout_s: float) -> Completion: ...
    def count_prompt_tokens(self, request: LLMRequest) -> int: ...
    def is_retryable(self, err: Exception) -> bool: ...
    def retry_after_s(self, err: Exception) -> float | None: ...


class CallStats(BaseModel):
    """Running totals for one client (one run); written to the run's cost.json."""

    calls: int = 0
    cache_hits: int = 0
    retries: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    saved_by_cache_usd: float = 0.0


class LLMClient:
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
        self.stats = CallStats()

    def complete(self, request: LLMRequest) -> LLMResponse:
        price = self._prices.price_for(request.model)  # unpriced model: refuse before anything
        key = request.cache_key()
        started = self._clock()

        if self._cache is not None and (hit := self._cache.get(key)) is not None:
            cached = LLMResponse.model_validate(hit)
            self.stats.calls += 1
            self.stats.cache_hits += 1
            self.stats.saved_by_cache_usd += cached.original_cost_usd
            return cached.model_copy(
                update={"cache_hit": True, "cost_usd": 0.0, "latency_ms": self._ms_since(started)}
            )

        prompt_tokens = self._backend.count_prompt_tokens(request)
        self._guard.check(worst_case_cost_usd(prompt_tokens, request.max_tokens, price))

        attempts = 0

        def attempt() -> Completion:
            nonlocal attempts
            attempts += 1
            return self._backend.complete(request, timeout_s=self._timeout_s)

        completion = call_with_retries(
            attempt,
            max_attempts=self._retry.max_attempts,
            is_retryable=self._backend.is_retryable,
            delay=lambda n: backoff_delay(
                n, base_s=self._retry.base_delay_s, cap_s=self._retry.max_delay_s, rng=self._rng
            ),
            retry_after=self._backend.retry_after_s,
            sleep=self._sleep,
        )
        spent = cost_usd(completion.usage, price)
        self._guard.charge(spent)
        self._ledger.record(
            SpendEntry(
                at=self._now(),
                run_id=self._run_id,
                model=request.model,
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
            cost_usd=spent,
            original_cost_usd=spent,
            cache_hit=False,
            latency_ms=self._ms_since(started),
            attempts=attempts,
        )
        self.stats.calls += 1
        self.stats.retries += attempts - 1
        self.stats.tokens_in += completion.usage.tokens_in
        self.stats.tokens_out += completion.usage.tokens_out
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
