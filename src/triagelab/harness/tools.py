"""The tools one agent run can call: MCP tools, skill tools, and their execution.

Every executor returns text for the model plus an error flag; nothing here raises on a
bad call. A malformed argument string, an unknown tool name or a server-side refusal all
come back as an error result the model can react to, so one confused step never kills
the whole issue.

Time safety: MCP tools that take `as_of` never show it to the model. The harness removes
it from the schema and injects the issue's creation time on every call, overriding
anything the model sends. This is the third `as_of` layer (ADR-0021): even a model that
"wants" the future cannot ask for it.
"""

import copy
import json
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict

from triagelab.harness.mcp_client import McpSession, ToolInfo
from triagelab.llm_client import ToolCall, ToolSpec
from triagelab.skills.loader import SkillError, SkillSet

ToolKind = Literal["mcp", "skill", "final"]


class Tool(Protocol):
    @property
    def spec(self) -> ToolSpec: ...
    @property
    def kind(self) -> ToolKind: ...
    def run(self, arguments: Mapping[str, Any]) -> tuple[str, bool]:
        """Returns (text for the model, is_error)."""
        ...


class ToolResult(BaseModel):
    """One executed call, as recorded in the trace."""

    model_config = ConfigDict(frozen=True)

    call_id: str
    name: str
    kind: ToolKind | None  # None: the model called a tool that doesn't exist
    arguments: dict[str, Any] | None  # None: the argument string wasn't a JSON object
    output: str  # exactly what the model sees
    is_error: bool
    truncated: bool
    latency_ms: int


def hide_arguments(schema: Mapping[str, Any], hidden: Iterable[str]) -> dict[str, Any]:
    """A copy of an input schema without the properties the harness fills in itself."""
    out = copy.deepcopy(dict(schema))
    props = cast(dict[str, Any], out.get("properties", {}))
    for name in hidden:
        props.pop(name, None)
    if "required" in out:
        out["required"] = [r for r in cast(list[str], out["required"]) if r not in hidden]
    return out


class McpTool:
    kind: ToolKind = "mcp"

    def __init__(self, info: ToolInfo, session: McpSession, injected: Mapping[str, Any]) -> None:
        self._info = info
        self._session = session
        # Only inject what this tool actually takes (e.g. get_codeowners has no as_of).
        takes = set(cast(dict[str, Any], info.input_schema.get("properties", {})))
        self._injected = {k: v for k, v in injected.items() if k in takes}
        self._spec = ToolSpec(
            name=info.name,
            description=info.description,
            parameters=hide_arguments(info.input_schema, self._injected),
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def run(self, arguments: Mapping[str, Any]) -> tuple[str, bool]:
        out = self._session.call_tool(self._info.name, {**arguments, **self._injected})
        return out.text, out.is_error


class _SkillTool:
    kind: ToolKind = "skill"

    def __init__(self, spec: ToolSpec, run: Callable[[Mapping[str, Any]], str]) -> None:
        self._spec = spec
        self._run = run

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def run(self, arguments: Mapping[str, Any]) -> tuple[str, bool]:
        try:
            return self._run(arguments), False
        except (SkillError, KeyError, TypeError) as err:
            return f"Error: {err}", True


def skill_tools(skills: SkillSet, loaded: set[str]) -> list[Tool]:
    """`load_skill` and `read_skill_file`, or nothing when there are no skills.

    `loaded` is per-issue state: a second `load_skill` of the same skill returns a short
    note instead of re-sending the body (the spec's client guide recommends this).
    """
    if not len(skills):
        return []
    names = sorted(skills.skills)

    def load(args: Mapping[str, Any]) -> str:
        name = str(args["name"])
        if name in loaded:
            return f"Skill {name!r} is already loaded above; follow those instructions."
        text = skills.activate(name)
        loaded.add(name)
        return text

    def read(args: Mapping[str, Any]) -> str:
        return skills.read_file(str(args["name"]), str(args["path"]))

    name_param = {"type": "string", "enum": names, "description": "The skill's name."}
    return [
        _SkillTool(
            ToolSpec(
                name="load_skill",
                description="Load a skill's full instructions. Call this when the task matches "
                "a skill's description in <available_skills>.",
                parameters={
                    "type": "object",
                    "properties": {"name": name_param},
                    "required": ["name"],
                },
            ),
            load,
        ),
        _SkillTool(
            ToolSpec(
                name="read_skill_file",
                description="Read one file a loaded skill points to, e.g. "
                "references/label_taxonomy.md.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": name_param,
                        "path": {
                            "type": "string",
                            "description": "Path relative to the skill folder.",
                        },
                    },
                    "required": ["name", "path"],
                },
            ),
            read,
        ),
    ]


def mcp_tools(
    session: McpSession, infos: Sequence[ToolInfo], injected: Mapping[str, Any]
) -> list[Tool]:
    return [McpTool(info, session, injected) for info in infos]


def truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n[... truncated: {len(text) - limit} more characters]", True


class Toolbox:
    """The tools of one agent run, by name, with bounded, never-raising execution."""

    def __init__(self, tools: Sequence[Tool], *, max_result_chars: int) -> None:
        self._tools = {t.spec.name: t for t in tools}
        self._max_result_chars = max_result_chars

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(t.spec for t in self._tools.values())

    def execute(self, call: ToolCall) -> ToolResult:
        started = time.perf_counter()
        tool = self._tools.get(call.name)
        arguments = _parse_arguments(call.arguments)
        if tool is None:
            text, is_error = (
                f"Error: no tool named {call.name!r}; use one of: " + ", ".join(self._tools),
                True,
            )
        elif arguments is None:
            text, is_error = "Error: the arguments must be a JSON object.", True
        else:
            try:
                text, is_error = tool.run(arguments)
            except Exception as err:  # a transport failure is still just a failed step
                text, is_error = f"Error: {type(err).__name__}: {err}", True
        output, truncated = truncate(text, self._max_result_chars)
        return ToolResult(
            call_id=call.id,
            name=call.name,
            kind=tool.kind if tool else None,
            arguments=arguments,
            output=output,
            is_error=is_error,
            truncated=truncated,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )


def _parse_arguments(raw: str) -> dict[str, Any] | None:
    try:
        parsed: Any = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None
    return cast(dict[str, Any], parsed) if isinstance(parsed, dict) else None
