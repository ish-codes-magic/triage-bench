"""Minimal GitHub GraphQL client: the network edge of the data layer.

Only what collection needs: POST a query, retry what is transient, and stay inside both
of GitHub's rate limits:
  - the *primary* budget (5,000 points/hour): every query asks for `rateLimit`, and the
    client sleeps until the reset time when the remaining budget gets low;
  - *secondary* limits (bursts, concurrency): a 403/429 with `Retry-After` is retried
    after at least that long.
Docs: https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api
"""

import random
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

import httpx
from pydantic import BaseModel

from triagelab.config import RetryConfig
from triagelab.retry import backoff_delay, call_with_retries

GRAPHQL_URL = "https://api.github.com/graphql"


class GitHubError(RuntimeError):
    """A failure that retrying the same request cannot fix (bad query, auth, not found)."""


class TransientGitHubError(GitHubError):
    """A failure worth retrying: 5xx, timeout, or a rate limit."""

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class RateLimit(BaseModel):
    cost: int
    remaining: int
    reset_at: datetime


class GraphQLResult(BaseModel):
    data: dict[str, Any]
    # GraphQL can succeed partially, e.g. one aliased issue in a batch was deleted.
    errors: list[dict[str, Any]]


class GraphQLClient:
    def __init__(
        self,
        token: str,
        *,
        retry: RetryConfig,
        http: httpx.Client | None = None,
        min_remaining: int = 200,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._http = http if http is not None else httpx.Client(timeout=60.0)
        self._headers = {"Authorization": f"Bearer {token}", "User-Agent": "triagelab"}
        self._retry = retry
        self._min_remaining = min_remaining
        self._sleep = sleep
        self._now = now
        self._rng = random.Random()
        self.last_rate_limit: RateLimit | None = None
        self.points_used = 0

    def query(self, query: str, variables: dict[str, Any] | None = None) -> GraphQLResult:
        self._wait_for_budget()
        result = call_with_retries(
            lambda: self._post(query, variables or {}),
            max_attempts=self._retry.max_attempts,
            is_retryable=lambda err: isinstance(err, TransientGitHubError),
            delay=lambda n: backoff_delay(
                n, base_s=self._retry.base_delay_s, cap_s=self._retry.max_delay_s, rng=self._rng
            ),
            retry_after=lambda err: getattr(err, "retry_after_s", None),
            sleep=self._sleep,
        )
        rate = result.data.get("rateLimit")
        if isinstance(rate, dict):
            rl = cast(dict[str, Any], rate)
            self.last_rate_limit = RateLimit(
                cost=rl["cost"], remaining=rl["remaining"], reset_at=rl["resetAt"]
            )
            self.points_used += self.last_rate_limit.cost
        return result

    def _post(self, query: str, variables: dict[str, Any]) -> GraphQLResult:
        try:
            response = self._http.post(
                GRAPHQL_URL, json={"query": query, "variables": variables}, headers=self._headers
            )
        except httpx.TimeoutException as err:
            raise TransientGitHubError(f"timeout: {err}") from err
        except httpx.TransportError as err:
            raise TransientGitHubError(f"transport error: {err}") from err

        status = response.status_code
        if status >= 500:
            # GitHub answers an over-expensive query with a 502 HTML page; the caller may
            # retry with a smaller batch if this keeps happening.
            raise TransientGitHubError(f"HTTP {status} from GitHub")
        if status in (403, 429) and _is_rate_limited(response):
            raise TransientGitHubError(
                f"rate limited (HTTP {status})", retry_after_s=_retry_after(response, self._now)
            )
        if status != 200:
            raise GitHubError(f"HTTP {status}: {response.text[:300]}")

        payload = cast(dict[str, Any], response.json())
        errors = cast(list[dict[str, Any]], payload.get("errors") or [])
        if any(e.get("type") == "RATE_LIMITED" for e in errors):
            raise TransientGitHubError("GraphQL RATE_LIMITED", retry_after_s=60.0)
        data = payload.get("data")
        if data is None:
            raise GitHubError(f"GraphQL errors: {errors[:3]}")
        return GraphQLResult(data=cast(dict[str, Any], data), errors=errors)

    def _wait_for_budget(self) -> None:
        rl = self.last_rate_limit
        if rl is None or rl.remaining >= self._min_remaining:
            return
        wait = rl.reset_at.timestamp() - self._now() + 5  # small margin past the reset
        if wait > 0:
            self._sleep(wait)
        self.last_rate_limit = None


def _is_rate_limited(response: httpx.Response) -> bool:
    return (
        "retry-after" in response.headers
        or response.headers.get("x-ratelimit-remaining") == "0"
        or "rate limit" in response.text.lower()
    )


def _retry_after(response: httpx.Response, now: Callable[[], float]) -> float:
    """GitHub's documented order: Retry-After, else the reset time, else at least a minute."""
    if (value := response.headers.get("retry-after")) is not None:
        try:
            return float(value)
        except ValueError:
            pass
    if response.headers.get("x-ratelimit-remaining") == "0":
        reset = response.headers.get("x-ratelimit-reset")
        if reset is not None and reset.isdigit():
            return max(0.0, float(reset) - now()) + 1
    return 60.0
