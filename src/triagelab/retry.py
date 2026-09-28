"""Retries with exponential backoff and full jitter.

We own retries (instead of letting LiteLLM or the provider SDK retry silently) so that
every retry is visible in traces and cost, and so the retry policy is one tested function.
"""

import time
from collections.abc import Callable
from typing import Protocol


class UniformSource(Protocol):
    """Anything with `uniform(a, b)`, e.g. `random.Random`. Injected so tests are deterministic."""

    def uniform(self, a: float, b: float) -> float: ...


def backoff_delay(attempt: int, *, base_s: float, cap_s: float, rng: UniformSource) -> float:
    """Seconds to wait before retry number `attempt` (0 for the first retry).

    # YOUR TURN
    Implement "full jitter" backoff:
        ceiling = min(cap_s, base_s * 2 ** attempt)
        delay   = a uniformly random value in [0, ceiling]

    Why jitter at all? If 50 workers hit a rate limit at the same moment and all wait
    exactly 1s, 2s, 4s..., they retry in lockstep and trip the limit again together.
    Randomizing the whole interval spreads them out.

    Hint: it's two lines. Use `rng.uniform`, not the `random` module, so tests can control
    the randomness.
    Tests: tests/test_retry.py::test_backoff_*
    """
    raise NotImplementedError("YOUR TURN: implement backoff_delay (see docstring)")


def call_with_retries[T](
    fn: Callable[[], T],
    *,
    max_attempts: int,
    is_retryable: Callable[[Exception], bool],
    delay: Callable[[int], float],
    retry_after: Callable[[Exception], float | None] = lambda _: None,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> T:
    """Call `fn`, retrying transient failures up to `max_attempts` total attempts.

    `delay(attempt)` supplies the backoff; a server-provided `retry_after` hint (e.g. from a
    429's Retry-After header) acts as a floor, because retrying sooner is guaranteed to fail.
    Non-retryable errors (bad request, auth) propagate immediately.
    """
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as err:
            is_last = attempt == max_attempts - 1
            if is_last or not is_retryable(err):
                raise
            wait = max(delay(attempt), retry_after(err) or 0.0)
            if on_retry is not None:
                on_retry(attempt, err, wait)
            sleep(wait)
    raise AssertionError("unreachable: the loop either returns or raises")
