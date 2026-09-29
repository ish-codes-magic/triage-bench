"""CODEOWNERS semantics, using the examples from GitHub's documentation."""

import pytest

from triagelab.mcp_server.codeowners import CodeOwners

FILE = """
# Comment lines are ignored
*                   @global-owner
*.js                @js-owner  # trailing comments too
/build/logs/        @doctocat
docs/*              docs@example.com
apps/               @octocat
**/logs             @octocat-logs
/Lib/asyncio/       @asyncio-team
/Lib/asyncio/runners.py
"""


@pytest.mark.parametrize(
    ("path", "owners"),
    [
        ("README.md", ("@global-owner",)),
        ("src/app.js", ("@js-owner",)),
        ("build/other.txt", ("@global-owner",)),
        # "**/logs" comes later and also matches build/logs/, so it wins (last match).
        ("build/logs/a/b.txt", ("@octocat-logs",)),
        ("docs/getting-started.md", ("docs@example.com",)),
        ("docs/build-app/troubleshooting.md", ("@global-owner",)),  # docs/* is one level only
        ("nested/apps/x.py", ("@octocat",)),  # unanchored directory matches anywhere
        ("deeply/nested/logs/x.txt", ("@octocat-logs",)),
        ("Lib/asyncio/tasks.py", ("@asyncio-team",)),
        ("Lib/asyncio/runners.py", ()),  # a later line with no owners wins: "no owner"
    ],
)
def test_documented_patterns(path: str, owners: tuple[str, ...]) -> None:
    assert CodeOwners.parse(FILE).owners_for(path)[0] == owners


def test_last_match_wins_and_reports_the_pattern() -> None:
    _, pattern = CodeOwners.parse(FILE).owners_for("Lib/asyncio/tasks.py")
    assert pattern == "/Lib/asyncio/"


def test_anchored_pattern_does_not_match_nested_directories() -> None:
    co = CodeOwners.parse("/build/logs/ @a\n")
    assert co.owners_for("x/build/logs/f")[0] == ()


def test_no_rules_means_no_owner() -> None:
    assert CodeOwners.parse("").owners_for("anything.py") == ((), None)
