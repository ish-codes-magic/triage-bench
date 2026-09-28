from datetime import date
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from triagelab.cache import DiskCache
from triagelab.config import RetryConfig
from triagelab.cost import (
    BudgetExceededError,
    BudgetGuard,
    ModelPrice,
    PriceTable,
    UnknownModelPriceError,
    Usage,
)
from triagelab.ledger import SpendLedger
from triagelab.llm_client import (
    Completion,
    LLMClient,
    LLMRequest,
    Message,
    prompt_tokens_upper_bound,
)

MODEL = "fake/model"
PRICES = PriceTable(
    models={
        MODEL: ModelPrice(
            input_per_mtok=2.0, output_per_mtok=10.0, source="test", verified_on=date(2026, 9, 29)
        )
    }
)


class RateLimitedError(Exception):
    pass


class FakeBackend:
    """Deterministic stand-in for a provider: no network, no money."""

    def __init__(self, text: str = "hello", fail_first: int = 0) -> None:
        self.text = text
        self.fail_first = fail_first
        self.calls = 0

    def complete(self, request: LLMRequest, *, timeout_s: float) -> Completion:
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RateLimitedError("429")
        return Completion(
            text=self.text,
            resolved_model="fake-model-2026-09-01",
            usage=Usage(tokens_in=1000, tokens_out=100),
        )

    def is_retryable(self, err: Exception) -> bool:
        return isinstance(err, RateLimitedError)

    def retry_after_s(self, err: Exception) -> float | None:
        return None


def _client(
    tmp_path: Path, backend: FakeBackend, *, per_run_usd: float = 1.0, cache: bool = True
) -> LLMClient:
    return LLMClient(
        backend=backend,
        prices=PRICES,
        guard=BudgetGuard(per_run_usd=per_run_usd, total_usd=100.0, spent_before_run_usd=0.0),
        ledger=SpendLedger(tmp_path / "ledger.jsonl"),
        cache=DiskCache(tmp_path / "cache") if cache else None,
        run_id="test-run",
        retry=RetryConfig(max_attempts=3, base_delay_s=0.01, max_delay_s=0.02),
        timeout_s=5.0,
        sleep=lambda _: None,
    )


def _request(model: str = MODEL, sample: int = 0) -> LLMRequest:
    return LLMRequest(
        model=model, messages=(Message(role="user", content="hi"),), max_tokens=100, sample=sample
    )


# 1000 in * $2/M + 100 out * $10/M
EXPECTED_COST = 0.003


def test_first_call_is_billed_and_logged(tmp_path: Path) -> None:
    client = _client(tmp_path, FakeBackend())
    resp = client.complete(_request())
    assert resp.text == "hello"
    assert not resp.cache_hit
    assert resp.cost_usd == pytest.approx(EXPECTED_COST)
    assert resp.resolved_model == "fake-model-2026-09-01"
    assert SpendLedger(tmp_path / "ledger.jsonl").total_usd() == pytest.approx(EXPECTED_COST)


def test_second_identical_call_is_a_free_cache_hit(tmp_path: Path) -> None:
    backend = FakeBackend()
    client = _client(tmp_path, backend)
    client.complete(_request())
    resp = client.complete(_request())
    assert resp.cache_hit
    assert resp.cost_usd == 0.0
    assert resp.original_cost_usd == pytest.approx(EXPECTED_COST)
    assert backend.calls == 1
    assert len(SpendLedger(tmp_path / "ledger.jsonl").entries()) == 1
    assert client.stats.saved_by_cache_usd == pytest.approx(EXPECTED_COST)


def test_cache_survives_a_new_client(tmp_path: Path) -> None:
    _client(tmp_path, FakeBackend()).complete(_request())
    backend = FakeBackend()
    assert _client(tmp_path, backend).complete(_request()).cache_hit
    assert backend.calls == 0


def test_different_sample_index_is_a_different_cache_entry(tmp_path: Path) -> None:
    backend = FakeBackend()
    client = _client(tmp_path, backend)
    client.complete(_request(sample=0))
    assert not client.complete(_request(sample=1)).cache_hit
    assert backend.calls == 2


def test_budget_guard_blocks_before_the_provider_is_called(tmp_path: Path) -> None:
    backend = FakeBackend()
    # worst case = 1018 bound tokens * 2/1e6 + 100 * 10/1e6 ~= 0.003 > 0.001
    client = _client(tmp_path, backend, per_run_usd=0.001)
    with pytest.raises(BudgetExceededError):
        client.complete(_request())
    assert backend.calls == 0


def test_unpriced_model_is_refused(tmp_path: Path) -> None:
    backend = FakeBackend()
    with pytest.raises(UnknownModelPriceError):
        _client(tmp_path, backend).complete(_request(model="fake/unpriced"))
    assert backend.calls == 0


class Verdict(BaseModel):
    label: str
    confidence: float


def test_structured_output_is_validated(tmp_path: Path) -> None:
    client = _client(tmp_path, FakeBackend(text='{"label": "bug", "confidence": 0.9}'))
    verdict, resp = client.complete_structured(_request(), Verdict)
    assert verdict == Verdict(label="bug", confidence=0.9)
    assert not resp.cache_hit


def test_structured_output_rejects_malformed_json(tmp_path: Path) -> None:
    client = _client(tmp_path, FakeBackend(text='{"label": "bug"}'))
    with pytest.raises(ValidationError):
        client.complete_structured(_request(), Verdict)


def test_schema_is_part_of_the_cache_key() -> None:
    plain = _request()
    typed = plain.model_copy(update={"response_schema": Verdict.model_json_schema()})
    assert plain.cache_key() != typed.cache_key()


@pytest.mark.your_turn
def test_transient_errors_are_retried(tmp_path: Path) -> None:
    # Needs backoff_delay (YOUR TURN in retry.py) to compute the wait between attempts.
    backend = FakeBackend(fail_first=2)
    client = _client(tmp_path, backend, cache=False)
    resp = client.complete(_request())
    assert resp.attempts == 3
    assert client.stats.retries == 2


def test_prompt_bound_counts_bytes_not_characters() -> None:
    # "hi" is 2 bytes; "日本" is 6 bytes. A byte bound must never under-count CJK text.
    ascii_bound = prompt_tokens_upper_bound(_request())
    cjk = LLMRequest(model=MODEL, messages=(Message(role="user", content="日本"),), max_tokens=1)
    assert prompt_tokens_upper_bound(cjk) - ascii_bound == 4


def test_prompt_bound_includes_the_schema() -> None:
    typed = _request().model_copy(update={"response_schema": Verdict.model_json_schema()})
    assert prompt_tokens_upper_bound(typed) > prompt_tokens_upper_bound(_request())
