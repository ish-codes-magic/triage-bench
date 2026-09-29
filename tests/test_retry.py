import random
from collections.abc import Callable

import pytest

from triagelab.retry import backoff_delay, call_with_retries


class TransientError(Exception):
    pass


class FatalError(Exception):
    pass


def _flaky(
    failures: int, exc: type[Exception] = TransientError
) -> tuple[list[int], Callable[[], str]]:
    calls: list[int] = []

    def fn() -> str:
        calls.append(1)
        if len(calls) <= failures:
            raise exc("boom")
        return "ok"

    return calls, fn


def test_succeeds_after_transient_failures() -> None:
    calls, fn = _flaky(2)
    waits: list[float] = []
    result = call_with_retries(
        fn,
        max_attempts=4,
        is_retryable=lambda e: isinstance(e, TransientError),
        delay=lambda attempt: float(attempt),
        sleep=waits.append,
    )
    assert result == "ok"
    assert len(calls) == 3
    assert waits == [0.0, 1.0]


def test_non_retryable_error_propagates_immediately() -> None:
    calls, fn = _flaky(5, FatalError)
    with pytest.raises(FatalError):
        call_with_retries(
            fn,
            max_attempts=4,
            is_retryable=lambda e: isinstance(e, TransientError),
            delay=lambda _: 0.0,
            sleep=lambda _: None,
        )
    assert len(calls) == 1


def test_gives_up_after_max_attempts() -> None:
    calls, fn = _flaky(10)
    with pytest.raises(TransientError):
        call_with_retries(
            fn,
            max_attempts=3,
            is_retryable=lambda _: True,
            delay=lambda _: 0.0,
            sleep=lambda _: None,
        )
    assert len(calls) == 3


def test_retry_after_hint_is_a_floor() -> None:
    _, fn = _flaky(1)
    waits: list[float] = []
    call_with_retries(
        fn,
        max_attempts=2,
        is_retryable=lambda _: True,
        delay=lambda _: 0.5,
        retry_after=lambda _: 7.0,
        sleep=waits.append,
    )
    assert waits == [7.0]


# ---- backoff_delay ---------------------------------------------------------------------


class _MaxRng:
    """Always returns the top of the interval, exposing the ceiling deterministically."""

    def uniform(self, a: float, b: float) -> float:
        return b


def test_backoff_ceiling_doubles_each_attempt() -> None:
    rng = _MaxRng()
    got = [backoff_delay(a, base_s=1.0, cap_s=100.0, rng=rng) for a in range(4)]
    assert got == [1.0, 2.0, 4.0, 8.0]


def test_backoff_is_capped() -> None:
    assert backoff_delay(10, base_s=1.0, cap_s=30.0, rng=_MaxRng()) == 30.0


def test_backoff_is_jittered_within_bounds() -> None:
    rng = random.Random(0)
    delays = [backoff_delay(3, base_s=1.0, cap_s=100.0, rng=rng) for _ in range(200)]
    assert all(0.0 <= d <= 8.0 for d in delays)
    assert len(set(delays)) > 100  # genuinely random, not a constant


def test_backoff_huge_attempt_does_not_overflow() -> None:
    assert backoff_delay(5000, base_s=1.0, cap_s=30.0, rng=_MaxRng()) == 30.0
