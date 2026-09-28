"""Shared test doubles."""

from triagelab.cost import Usage
from triagelab.llm_client import Completion, LLMRequest


class RateLimitedError(Exception):
    pass


class FakeBackend:
    """Deterministic stand-in for a provider: no network, no money.

    Always reports 1000 prompt / 100 completion tokens so costs are easy to hand-check.
    """

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
