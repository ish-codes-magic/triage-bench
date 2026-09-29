"""The harness's synchronous MCP client: in-process, across threads, and over real stdio."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from triagelab.harness.mcp_client import McpSession, repo_intel_command
from triagelab.mcp_server.server import build_server

from .mcp_fixtures import PROFILE_PATH, make_intel

TOOLS = {"search_similar_issues", "get_issue", "search_code", "get_codeowners", "list_components"}


def test_lists_tools_with_their_input_schemas(tmp_path: Path) -> None:
    with McpSession.in_process(build_server(make_intel(tmp_path))) as mcp:
        tools = {t.name: t for t in mcp.list_tools()}
    assert set(tools) == TOOLS
    assert all(t.read_only for t in tools.values())
    assert "as_of" in tools["search_similar_issues"].input_schema["properties"]


def test_results_are_json_text_and_server_errors_are_outputs(tmp_path: Path) -> None:
    intel = make_intel(tmp_path)
    t = intel.searcher.corpus.issues[1].created_at.isoformat()
    with McpSession.in_process(build_server(intel)) as mcp:
        ok = mcp.call_tool("get_issue", {"number": 1, "as_of": t})
        refused = mcp.call_tool("get_issue", {"number": 3, "as_of": t})
    assert not ok.is_error
    assert json.loads(ok.text)["title"] == "zipfile crashes on empty archive"
    assert refused.is_error
    assert "not available" in refused.text


def test_one_session_serves_many_threads(tmp_path: Path) -> None:
    intel = make_intel(tmp_path)
    as_of = intel.searcher.corpus.issues[2].created_at.isoformat()
    with McpSession.in_process(build_server(intel)) as mcp, ThreadPoolExecutor(8) as pool:
        outs = list(
            pool.map(
                lambda q: mcp.call_tool("search_similar_issues", {"query": q, "as_of": as_of}),
                ["zipfile", "asyncio", "archive", "crash"] * 4,
            )
        )
    assert not any(o.is_error for o in outs)


def test_calls_outside_the_with_block_fail_loudly(tmp_path: Path) -> None:
    mcp = McpSession.in_process(build_server(make_intel(tmp_path)))
    with pytest.raises(RuntimeError, match="not open"):
        mcp.list_tools()


def test_real_stdio_subprocess(tmp_path: Path) -> None:
    # BM25-only and an empty data dir: the handshake, tools/list and list_components need
    # no index (it loads lazily), so this proves the transport without any data.
    command, args = repo_intel_command(PROFILE_PATH, tmp_path, dense=False)
    with (
        (tmp_path / "server.log").open("w", encoding="utf-8") as errlog,
        McpSession.stdio(command, args, errlog=errlog) as mcp,
    ):
        names = {t.name for t in mcp.list_tools()}
        components = mcp.call_tool("list_components", {})
    assert names == TOOLS
    assert not components.is_error
    assert "stdlib" in [c["name"] for c in json.loads(components.text)["components"]]
