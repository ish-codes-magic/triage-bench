"""Shared test doubles."""

from datetime import date
from pathlib import Path

from triagelab.cache import DiskCache
from triagelab.config import RetryConfig
from triagelab.cost import BudgetGuard, ModelPrice, PriceTable, Usage
from triagelab.ledger import SpendLedger
from triagelab.llm_client import Completion, LLMClient, LLMRequest, ToolCall


class RateLimitedError(Exception):
    pass


class FakeBackend:
    """Deterministic stand-in for a provider: no network, no money.

    Always reports 1000 prompt / 100 completion tokens so costs are easy to hand-check.
    """

    def __init__(
        self,
        text: str = "hello",
        fail_first: int = 0,
        texts: list[str] | None = None,
        script: list[Completion] | None = None,
    ) -> None:
        self.text = text
        self.texts = texts  # if set, successive calls return these in turn (then repeat the last)
        self.script = script  # like `texts`, but whole completions (e.g. with tool calls)
        self.fail_first = fail_first
        self.calls = 0
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest, *, timeout_s: float) -> Completion:
        self.calls += 1
        self.requests.append(request)
        if self.calls <= self.fail_first:
            raise RateLimitedError("429")
        if self.script:
            return self.script[min(self.calls - self.fail_first, len(self.script)) - 1]
        text = self.text
        if self.texts:
            text = self.texts[min(self.calls, len(self.texts)) - 1]
        return Completion(
            text=text,
            resolved_model="fake-model-2026-09-01",
            usage=Usage(tokens_in=1000, tokens_out=100),
        )

    def is_retryable(self, err: Exception) -> bool:
        return isinstance(err, RateLimitedError)

    def retry_after_s(self, err: Exception) -> float | None:
        return None


FAKE_MODEL = "fake/model"
FAKE_PRICES = PriceTable(
    models={
        FAKE_MODEL: ModelPrice(
            input_per_mtok=2.0, output_per_mtok=10.0, source="test", verified_on=date(2026, 9, 29)
        )
    }
)


def make_client(tmp_path: Path, backend: FakeBackend, *, cache: bool = False) -> LLMClient:
    """A real LLMClient around a fake backend: real budgets, ledger and (optional) cache."""
    return LLMClient(
        backend=backend,
        prices=FAKE_PRICES,
        guard=BudgetGuard(per_run_usd=10.0, total_usd=100.0, spent_before_run_usd=0.0),
        ledger=SpendLedger(tmp_path / "ledger.jsonl"),
        cache=DiskCache(tmp_path / "cache") if cache else None,
        run_id="test-run",
        retry=RetryConfig(max_attempts=1, base_delay_s=0.01, max_delay_s=0.02),
        timeout_s=5.0,
        sleep=lambda _: None,
    )


def completion(
    text: str = "", calls: tuple[ToolCall, ...] = (), tokens: tuple[int, int] = (1000, 100)
) -> Completion:
    return Completion(
        text=text,
        resolved_model="fake-model-2026-09-01",
        usage=Usage(tokens_in=tokens[0], tokens_out=tokens[1]),
        tool_calls=calls,
    )
