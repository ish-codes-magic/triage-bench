"""repo-intel: a read-only MCP server over one repository's issue history and code.

Five tools (AGENTS.md §8), all read-only:
  search_similar_issues(query, as_of, k)   hybrid BM25 + dense search, as of a time
  get_issue(number, as_of)                 one past issue as it looked at `as_of`
  search_code(query, path_glob, max_results)  literal search in the frozen checkout
  get_codeowners(path)                     owners from the checkout's CODEOWNERS
  list_components()                        the component taxonomy

`as_of` is enforced here, in the server, never left to the prompt:
  - only issues created strictly before `as_of` exist for a query;
  - past issues show their creation-time text, with labels and state replayed to `as_of`;
  - an optional ceiling rejects any `as_of` later than the moment being triaged (the M4
    harness also injects `as_of` itself, so a model cannot pick a later one).

Tool descriptions are prompts written for a model; changing one changes behaviour, so the
set is versioned by TOOLS_VERSION.
"""

import inspect
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from triagelab.data.profile import RepoProfile
from triagelab.mcp_server.code_search import CodeHit, CodeSearcher
from triagelab.mcp_server.codeowners import CodeOwners
from triagelab.retrieval.corpus import NotVisibleError
from triagelab.retrieval.search import HybridSearcher

# 2 (iteration 6): code hits and owner lookups name the component owning the path.
TOOLS_VERSION = "2"
_SNIPPET_CHARS = 300
_BODY_CHARS = 6000
_TRUNCATED = " …[truncated]"

# Parameter descriptions are part of the tools' prompt (see TOOLS_VERSION).
_SEARCH_QUERY = "Text to search for: an issue's title and body, an error message, or keywords."
_CODE_QUERY = "Literal text to find (case-insensitive), e.g. a function name or error message."

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


class SimilarIssue(BaseModel):
    number: int
    title: str
    created_at: datetime
    state: str
    labels: list[str]
    snippet: str
    score: float


class SimilarIssues(BaseModel):
    as_of: datetime
    results: list[SimilarIssue]


class IssueDetail(BaseModel):
    number: int
    url: str
    created_at: datetime
    title: str
    body: str
    body_truncated: bool
    labels: list[str]
    state: str
    state_reason: str | None
    as_of: datetime


class CodeSearchResult(BaseModel):
    checkout_commit: str
    hits: list[CodeHit]
    truncated: bool


class Owners(BaseModel):
    path: str
    owners: list[str]
    matched_pattern: str | None
    component: str | None


class ComponentInfo(BaseModel):
    name: str
    role: str
    paths: list[str]


class Components(BaseModel):
    components: list[ComponentInfo]


class RepoIntel:
    """Everything the tools read. Built once; every tool call is a pure lookup.

    The searcher may be given as a factory: building it (loading ~12k issues and indexing
    them) takes longer than MCP clients wait for the initial handshake, so the server
    answers initialize/tools/list immediately and pays that cost on the first search.
    """

    def __init__(
        self,
        *,
        profile: RepoProfile,
        searcher: HybridSearcher | Callable[[], HybridSearcher],
        code: CodeSearcher | None = None,
        owners: CodeOwners | None = None,
        checkout_commit: str = "unknown",
        as_of_ceiling: datetime | None = None,
    ) -> None:
        self.profile = profile
        self._searcher = searcher if isinstance(searcher, HybridSearcher) else None
        self._factory = None if isinstance(searcher, HybridSearcher) else searcher
        self._lock = threading.Lock()
        self.code = code
        self.owners = owners or CodeOwners([])
        self.checkout_commit = checkout_commit
        self.as_of_ceiling = as_of_ceiling

    @property
    def searcher(self) -> HybridSearcher:
        if self._searcher is None:
            with self._lock:
                if self._searcher is None and self._factory is not None:
                    self._searcher = self._factory()
        assert self._searcher is not None
        return self._searcher

    def component_name(self, path: str) -> str | None:
        comp = self.profile.component_of(path.lstrip("/"))
        return comp.name if comp else None

    def check_as_of(self, as_of: datetime) -> datetime:
        aware = as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=UTC)
        if self.as_of_ceiling is not None and aware > self.as_of_ceiling:
            raise ToolError(
                f"as_of {aware.isoformat()} is after this server's ceiling "
                f"{self.as_of_ceiling.isoformat()}; it cannot show later history."
            )
        return aware


def _snippet(text: str) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= _SNIPPET_CHARS else flat[:_SNIPPET_CHARS] + _TRUNCATED


def build_server(intel: RepoIntel) -> MCPServer:
    repo = intel.profile.repo
    mcp = MCPServer(
        name="repo-intel",
        version=f"tools-v{TOOLS_VERSION}",
        instructions=(
            f"Read-only history and source code for {repo}. Issue tools take `as_of` and only "
            "ever show what was known at that moment: pass the creation time of the issue you "
            "are triaging."
        ),
    )

    def tool[F: Callable[..., BaseModel]](fn: F) -> F:
        # Docstrings are the tools' prompts; cleandoc strips their source indentation.
        mcp.add_tool(fn, annotations=READ_ONLY, description=inspect.cleandoc(fn.__doc__ or ""))
        return fn

    @tool
    def search_similar_issues(
        query: Annotated[
            str,
            Field(description=_SEARCH_QUERY),
        ],
        as_of: Annotated[
            datetime,
            Field(description="Only issues created before this moment are searched (ISO 8601)."),
        ],
        k: Annotated[int, Field(ge=1, le=20, description="How many results to return.")] = 8,
    ) -> SimilarIssues:
        """Find earlier issues similar to the given text, best match first.

        Use it to spot duplicates or related reports. Each result shows the title, a short
        snippet of the original report, and labels/state as they were at `as_of`. Call
        get_issue for the full text of a promising result.
        """
        when = intel.check_as_of(as_of)
        results: list[SimilarIssue] = []
        for hit in intel.searcher.search(query, as_of=when, k=k):
            view = intel.searcher.corpus.get(hit.number, when)
            results.append(
                SimilarIssue(
                    number=view.number,
                    title=view.title,
                    created_at=view.created_at,
                    state=view.state,
                    labels=list(view.labels),
                    snippet=_snippet(view.body),
                    score=round(hit.score, 4),
                )
            )
        return SimilarIssues(as_of=when, results=results)

    @tool
    def get_issue(
        number: Annotated[int, Field(description="Issue number.")],
        as_of: Annotated[
            datetime, Field(description="Show the issue as it was at this moment (ISO 8601).")
        ],
    ) -> IssueDetail:
        """Read one earlier issue: its original report, and its labels and open/closed state
        as they were at `as_of`. Issues created at or after `as_of` are not available."""
        when = intel.check_as_of(as_of)
        try:
            view = intel.searcher.corpus.get(number, when)
        except NotVisibleError as err:
            raise ToolError(str(err)) from err
        truncated = len(view.body) > _BODY_CHARS
        return IssueDetail(
            number=view.number,
            url=f"https://github.com/{repo}/issues/{view.number}",
            created_at=view.created_at,
            title=view.title,
            body=view.body[:_BODY_CHARS] + (_TRUNCATED if truncated else ""),
            body_truncated=truncated,
            labels=list(view.labels),
            state=view.state,
            state_reason=view.state_reason,
            as_of=when,
        )

    @tool
    def search_code(
        query: Annotated[
            str,
            Field(description=_CODE_QUERY),
        ],
        path_glob: Annotated[
            str | None, Field(description="Optional path filter, e.g. 'Lib/asyncio/**' or '*.c'.")
        ] = None,
        max_results: Annotated[int, Field(ge=1, le=50, description="Maximum hits to return.")] = 20,
    ) -> CodeSearchResult:
        """Search the repository's source code as it was just before the evaluation period.

        Returns file paths, line numbers, the matching line, and the component that owns
        each file. Useful for finding which module or file an issue is about."""
        if intel.code is None:
            raise ToolError("No source checkout is available on this server.")
        hits, truncated = intel.code.search(query, path_glob=path_glob, max_results=max_results)
        return CodeSearchResult(
            checkout_commit=intel.checkout_commit,
            hits=[h.model_copy(update={"component": intel.component_name(h.path)}) for h in hits],
            truncated=truncated,
        )

    @tool
    def get_codeowners(
        path: Annotated[
            str, Field(description="Repository-relative file path, e.g. 'Lib/asyncio/tasks.py'.")
        ],
    ) -> Owners:
        """Who owns a file, according to the repository's CODEOWNERS (the last matching rule),
        and which component the file belongs to."""
        owners, pattern = intel.owners.owners_for(path)
        return Owners(
            path=path,
            owners=list(owners),
            matched_pattern=pattern,
            component=intel.component_name(path),
        )

    @tool
    def list_components() -> Components:
        """The repository's components and the paths each covers. Use these names when
        deciding which part of the codebase an issue belongs to."""
        return Components(
            components=[
                ComponentInfo(name=c.name, role=c.role, paths=list(c.prefixes))
                for c in intel.profile.components
            ]
        )

    return mcp
