"""Shared test doubles."""

from triagelab.cost import Usage
from triagelab.llm_client import Completion, LLMRequest


class RateLimitedError(Exception):
    pass


class FakeBackend:
    """Deterministic stand-in for a provider: no network, no money.

    Always reports 1000 prompt / 100 completion tokens so costs are easy to hand-check.
    """

    def __init__(
        self, text: str = "hello", fail_first: int = 0, texts: list[str] | None = None
    ) -> None:
        self.text = text
        self.texts = texts  # if set, successive calls return these in turn (then repeat the last)
        self.fail_first = fail_first
        self.calls = 0
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest, *, timeout_s: float) -> Completion:
        self.calls += 1
        self.requests.append(request)
        if self.calls <= self.fail_first:
            raise RateLimitedError("429")
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
