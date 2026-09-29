"""The agent's tools: as_of injection, never-raising execution, bounded output, skills."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from triagelab.harness.mcp_client import McpSession
from triagelab.harness.tools import Toolbox, hide_arguments, mcp_tools, skill_tools
from triagelab.llm_client import ToolCall
from triagelab.mcp_server.server import build_server
from triagelab.skills.loader import SkillSet, parse_skill

from .mcp_fixtures import make_intel
from .skill_fixtures import make_skill


def call(name: str, arguments: str, id_: str = "c1") -> ToolCall:
    return ToolCall(id=id_, name=name, arguments=arguments)


def test_hidden_arguments_leave_the_schema_and_its_required_list() -> None:
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}, "as_of": {"type": "string"}},
        "required": ["query", "as_of"],
    }
    hidden = hide_arguments(schema, ["as_of"])
    assert hidden["properties"] == {"query": {"type": "string"}}
    assert hidden["required"] == ["query"]
    assert "as_of" in schema["properties"]  # the original is untouched


def test_the_model_never_sees_as_of_and_cannot_override_it(tmp_path: Path) -> None:
    intel = make_intel(tmp_path)
    issue_3 = intel.searcher.corpus.issues[2]
    with McpSession.in_process(build_server(intel)) as mcp:
        box = Toolbox(
            mcp_tools(mcp, mcp.list_tools(), {"as_of": issue_3.created_at.isoformat()}),
            max_result_chars=10_000,
        )
        specs = {s.name: s for s in box.specs}
        for spec in specs.values():
            assert "as_of" not in json.dumps(spec.parameters)
        future = (issue_3.created_at + timedelta(days=30)).isoformat()
        sneaky = box.execute(
            call("search_similar_issues", json.dumps({"query": "zipfile", "as_of": future}))
        )
        owners = box.execute(call("get_codeowners", '{"path": "Lib/zipfile.py"}'))
    numbers = [r["number"] for r in json.loads(sneaky.output)["results"]]
    assert 3 not in numbers  # the injected creation time won over the model's date
    assert not owners.is_error  # tools without as_of get nothing injected
    assert sneaky.kind == "mcp"


def test_bad_calls_become_error_results_not_exceptions(tmp_path: Path) -> None:
    with McpSession.in_process(build_server(make_intel(tmp_path))) as mcp:
        box = Toolbox(mcp_tools(mcp, mcp.list_tools(), {}), max_result_chars=10_000)
        unknown = box.execute(call("delete_repo", "{}"))
        malformed = box.execute(call("get_codeowners", "{not json"))
        not_object = box.execute(call("get_codeowners", "[1, 2]"))
        refused = box.execute(call("get_issue", '{"number": 99}'))  # missing as_of here
    assert unknown.is_error
    assert unknown.kind is None
    assert "search_similar_issues" in unknown.output  # tells the model what exists
    assert malformed.is_error
    assert malformed.arguments is None
    assert not_object.is_error
    assert refused.is_error


def test_long_results_are_truncated_with_a_marker(tmp_path: Path) -> None:
    with McpSession.in_process(build_server(make_intel(tmp_path))) as mcp:
        box = Toolbox(mcp_tools(mcp, mcp.list_tools(), {}), max_result_chars=40)
        result = box.execute(call("list_components", "{}"))
    assert result.truncated
    assert "[... truncated:" in result.output


def test_skill_tools_load_once_and_read_files(tmp_path: Path) -> None:
    d = make_skill(tmp_path, "demo", "name: demo\ndescription: Demo.", body="See references/a.md")
    (d / "references").mkdir()
    (d / "references" / "a.md").write_text("alpha", encoding="utf-8")
    loaded: set[str] = set()
    box = Toolbox(skill_tools(SkillSet([parse_skill(d)]), loaded), max_result_chars=10_000)
    first = box.execute(call("load_skill", '{"name": "demo"}'))
    again = box.execute(call("load_skill", '{"name": "demo"}'))
    ref = box.execute(call("read_skill_file", '{"name": "demo", "path": "references/a.md"}'))
    escape = box.execute(call("read_skill_file", '{"name": "demo", "path": "../x"}'))
    missing_arg = box.execute(call("read_skill_file", '{"name": "demo"}'))
    assert "See references/a.md" in first.output
    assert loaded == {"demo"}
    assert "already loaded" in again.output
    assert ref.output == "alpha"
    assert escape.is_error
    assert missing_arg.is_error


@pytest.mark.parametrize("names", [[], ["demo"]])
def test_no_skills_means_no_skill_tools(tmp_path: Path, names: list[str]) -> None:
    make_skill(tmp_path, "demo", "name: demo\ndescription: Demo.")
    tools = skill_tools(SkillSet.from_dir(tmp_path, names), set())
    assert len(tools) == (2 if names else 0)
