"""A synchronous MCP client for the agent harness.

The harness runs on the eval runner's worker threads, but the MCP SDK is async-only
(2.2.0 ships no sync wrapper). One anyio blocking portal owns an event loop in a
background thread plus a single MCP `Client` session, and worker threads submit calls
to it. The session multiplexes concurrent requests, so one server, in-process or a
stdio subprocess, serves every thread.

    with McpSession.stdio(*repo_intel_command(profile, data_dir)) as mcp:
        tools = mcp.list_tools()
        out = mcp.call_tool("get_issue", {"number": 1, "as_of": "..."})
"""

import json
import sys
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from types import TracebackType
from typing import Any, Self, TextIO

from anyio.from_thread import BlockingPortal, start_blocking_portal
from mcp import Client, StdioServerParameters, stdio_client
from mcp.server import MCPServer
from mcp_types import CallToolResult, TextContent, Tool
from pydantic import BaseModel, ConfigDict


class ToolInfo(BaseModel):
    """A tool as the server describes it, trimmed to what the harness uses."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool


class ToolOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    is_error: bool


def render_result(result: CallToolResult) -> str:
    """Tool output as the model will read it.

    Structured content (our server returns it for every tool) is exact, so it wins.
    Otherwise the text blocks are joined; other content types are only named, since
    this harness sends text-only messages.
    """
    if result.structured_content is not None:
        return json.dumps(result.structured_content, ensure_ascii=False)
    parts = [
        block.text if isinstance(block, TextContent) else f"[{block.type} content omitted]"
        for block in result.content
    ]
    return "\n".join(parts)


def _tool_info(tool: Tool) -> ToolInfo:
    return ToolInfo(
        name=tool.name,
        description=tool.description or "",
        input_schema=dict(tool.input_schema),
        read_only=bool(tool.annotations and tool.annotations.read_only_hint),
    )


class McpSession:
    """One MCP client session, usable from any thread while the `with` block is open."""

    def __init__(self, client: Client) -> None:
        self._client = client
        self._stack = ExitStack()
        self._portal: BlockingPortal | None = None

    @classmethod
    def in_process(cls, server: MCPServer) -> Self:
        """Talk to a server object over an in-memory transport (tests, CI)."""
        return cls(Client(server))

    @classmethod
    def stdio(
        cls,
        command: str,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        errlog: TextIO = sys.stderr,
    ) -> Self:
        """Launch the server as a subprocess and speak MCP over its stdin/stdout.

        On Windows the SDK passes the child only a minimal environment (PATH, TEMP, ...),
        so anything else it needs must be in `env`.
        """
        params = StdioServerParameters(
            command=command, args=list(args), env=dict(env) if env else None, cwd=cwd
        )
        return cls(Client(stdio_client(params, errlog=errlog)))

    def __enter__(self) -> Self:
        try:
            portal = self._stack.enter_context(start_blocking_portal())
            self._stack.enter_context(portal.wrap_async_context_manager(self._client))
        except BaseException:
            self._stack.close()
            raise
        self._portal = portal
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._portal = None
        self._stack.close()

    @property
    def portal(self) -> BlockingPortal:
        if self._portal is None:
            raise RuntimeError("McpSession is not open; use it as a context manager")
        return self._portal

    def list_tools(self) -> list[ToolInfo]:
        tools: list[ToolInfo] = []
        cursor: str | None = None
        while True:
            page = self.portal.call(partial(self._client.list_tools, cursor=cursor))
            tools += [_tool_info(t) for t in page.tools]
            cursor = page.next_cursor
            if not cursor:
                return tools

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> ToolOutput:
        """Errors the server reports (bad arguments, refused `as_of`) come back as
        `is_error=True` outputs, for the model to read; transport failures raise."""
        result = self.portal.call(partial(self._client.call_tool, name, dict(arguments)))
        return ToolOutput(text=render_result(result), is_error=result.is_error)


def repo_intel_command(
    profile: Path, data_dir: Path, *, dense: bool = True
) -> tuple[str, list[str]]:
    """The command that serves repo-intel over stdio with this interpreter."""
    args = ["-m", "triagelab.mcp_server", "--profile", str(profile), "--data-dir", str(data_dir)]
    return sys.executable, [*args, *([] if dense else ["--no-dense"])]
