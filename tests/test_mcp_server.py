"""Layer 2 of the server's tests: a real MCP client talking to the server in-process.

(Layer 1 is the unit tests of corpus/BM25/code search/CODEOWNERS; layer 3 is the manual
MCP Inspector check, documented in docs/learning/M3-retrieval-and-mcp.md.)
"""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from triagelab.mcp_server.server import RepoIntel, build_server
from triagelab.retrieval.search import HybridSearcher

from .mcp_fixtures import PROFILE, make_intel

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def intel(tmp_path: Path) -> RepoIntel:
    return make_intel(tmp_path)


async def call(intel: RepoIntel, tool: str, args: dict[str, Any]) -> Any:
    async with Client(build_server(intel), raise_exceptions=True) as client:
        return await client.call_tool(tool, args)


async def test_exposes_five_read_only_tools(intel: RepoIntel) -> None:
    async with Client(build_server(intel)) as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == {
        "search_similar_issues",
        "get_issue",
        "search_code",
        "get_codeowners",
        "list_components",
    }
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.description  # descriptions are written for the model


async def test_search_only_returns_issues_created_before_as_of(intel: RepoIntel) -> None:
    issue_3 = intel.searcher.corpus.issues[2]
    result = await call(
        intel,
        "search_similar_issues",
        {"query": "zipfile empty archive crash", "as_of": issue_3.created_at.isoformat()},
    )
    numbers = [r["number"] for r in result.structured_content["results"]]
    assert numbers[0] == 1  # the earlier duplicate is found
    assert 3 not in numbers  # the query issue itself doesn't exist yet
    later = await call(
        intel,
        "search_similar_issues",
        {"query": "zipfile", "as_of": (issue_3.created_at + timedelta(days=1)).isoformat()},
    )
    assert 3 in [r["number"] for r in later.structured_content["results"]]


async def test_get_issue_refuses_the_future(intel: RepoIntel) -> None:
    t = intel.searcher.corpus.issues[1].created_at
    ok = await call(intel, "get_issue", {"number": 1, "as_of": t.isoformat()})
    assert ok.structured_content["title"] == "zipfile crashes on empty archive"
    future = await call(intel, "get_issue", {"number": 3, "as_of": t.isoformat()})
    assert future.is_error
    assert "not visible" in future.content[0].text


async def test_as_of_ceiling_is_enforced_by_the_server(intel: RepoIntel) -> None:
    intel.as_of_ceiling = intel.searcher.corpus.issues[1].created_at
    late = (intel.as_of_ceiling + timedelta(days=30)).isoformat()
    result = await call(intel, "search_similar_issues", {"query": "zipfile", "as_of": late})
    assert result.is_error
    assert "ceiling" in result.content[0].text


async def test_code_owners_and_components(intel: RepoIntel) -> None:
    code = await call(intel, "search_code", {"query": "_EndRecData"})
    assert code.structured_content["hits"][0]["path"] == "Lib/zipfile.py"
    assert code.structured_content["checkout_commit"] == "abc123"
    owners = await call(intel, "get_codeowners", {"path": "Lib/zipfile.py"})
    assert owners.structured_content["owners"] == ["@zip-owner"]
    components = await call(intel, "list_components", {})
    names = [c["name"] for c in components.structured_content["components"]]
    assert "stdlib" in names
    assert "interpreter-core" in names


async def test_invalid_arguments_are_rejected_by_schema(intel: RepoIntel) -> None:
    result = await call(
        intel, "search_similar_issues", {"query": "x", "as_of": "2026-01-01T00:00:00Z", "k": 500}
    )
    assert result.is_error  # k is capped at 20 by the tool schema


async def test_searcher_is_built_lazily_and_once(intel: RepoIntel) -> None:
    built: list[int] = []
    real = intel.searcher

    def factory() -> HybridSearcher:
        built.append(1)
        return real

    lazy = RepoIntel(profile=PROFILE, searcher=factory)
    async with Client(build_server(lazy)) as client:
        await client.list_tools()
        assert built == []  # the handshake and tools/list never build the index
        as_of = real.corpus.issues[2].created_at.isoformat()
        await client.call_tool("search_similar_issues", {"query": "zipfile", "as_of": as_of})
        await client.call_tool("search_similar_issues", {"query": "asyncio", "as_of": as_of})
    assert built == [1]
