"""GraphQL client tests against httpx.MockTransport: no network."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from triagelab.config import RetryConfig
from triagelab.data.github import GitHubError, GraphQLClient

RETRY = RetryConfig(max_attempts=3, base_delay_s=0.01, max_delay_s=0.02)
OK = {"data": {"rateLimit": {"cost": 3, "remaining": 4000, "resetAt": "2026-09-29T12:00:00Z"}}}


def _client(
    responses: list[httpx.Response], sleeps: list[float], now: float = 0.0
) -> tuple[GraphQLClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[len(seen) - 1]

    client = GraphQLClient(
        "test-token",
        retry=RETRY,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
        now=lambda: now,
    )
    return client, seen


def _json(body: object, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body), headers=headers)


def test_successful_query_tracks_points_and_sends_auth() -> None:
    client, seen = _client([_json(OK)], [])
    result = client.query("{ rateLimit { cost } }")
    assert result.data["rateLimit"]["cost"] == 3
    assert client.points_used == 3
    assert seen[0].headers["Authorization"] == "Bearer test-token"


def test_502_is_retried_then_succeeds() -> None:
    sleeps: list[float] = []
    client, seen = _client([httpx.Response(502, text="<html>"), _json(OK)], sleeps)
    client.query("{ x }")
    assert len(seen) == 2
    assert len(sleeps) == 1


def test_secondary_rate_limit_waits_at_least_retry_after() -> None:
    sleeps: list[float] = []
    limited = httpx.Response(403, text="secondary rate limit", headers={"retry-after": "42"})
    client, _ = _client([limited, _json(OK)], sleeps)
    client.query("{ x }")
    assert sleeps == [42.0]


def test_graphql_errors_without_data_are_not_retried() -> None:
    client, seen = _client([_json({"errors": [{"message": "bad field"}]})], [])
    with pytest.raises(GitHubError, match="bad field"):
        client.query("{ nope }")
    assert len(seen) == 1


def test_partial_errors_are_returned_with_the_data() -> None:
    body = {"data": {"repository": {"i1": None}}, "errors": [{"type": "NOT_FOUND"}]}
    client, _ = _client([_json(body)], [])
    result = client.query("{ x }")
    assert result.errors[0]["type"] == "NOT_FOUND"


def test_low_budget_sleeps_until_reset_before_next_query() -> None:
    low = {"data": {"rateLimit": {"cost": 1, "remaining": 10, "resetAt": "2026-09-29T12:00:00Z"}}}
    sleeps: list[float] = []
    now = datetime(2026, 9, 29, 12, tzinfo=UTC).timestamp() - 100  # 100 s before the reset
    client, _ = _client([_json(low), _json(OK)], sleeps, now=now)
    client.query("{ x }")
    client.query("{ x }")
    assert sleeps == [pytest.approx(105.0)]  # until reset, plus a 5 s margin
