"""A small repo-intel instance (three issues, one source file) shared by the MCP tests."""

from datetime import timedelta
from pathlib import Path

from triagelab.data.profile import load_profile
from triagelab.mcp_server.code_search import CodeSearcher
from triagelab.mcp_server.codeowners import CodeOwners
from triagelab.mcp_server.server import RepoIntel
from triagelab.retrieval.corpus import build_corpus
from triagelab.retrieval.search import HybridSearcher

from .data_fixtures import raw

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO_ROOT / "configs" / "repos" / "python__cpython.yaml"
PROFILE = load_profile(PROFILE_PATH)

TITLES = (
    (1, "zipfile crashes on empty archive"),
    (2, "asyncio TaskGroup hangs"),
    (3, "zipfile empty archive crash again"),
)


def make_intel(checkout: Path) -> RepoIntel:
    base = raw()
    assert base.original_body is not None
    issues = []
    for n, title in TITLES:
        created = base.created_at + timedelta(days=n - 1)
        issues.append(
            base.model_copy(
                update={
                    "number": n,
                    "created_at": created,
                    "title": title,
                    "title_renames": (),
                    "original_body": base.original_body.model_copy(
                        update={"at": created, "body": title}
                    ),
                }
            )
        )
    (checkout / "Lib").mkdir()
    (checkout / "Lib" / "zipfile.py").write_text(
        "def _EndRecData(fpin):\n    pass\n", encoding="utf-8"
    )
    return RepoIntel(
        profile=PROFILE,
        searcher=HybridSearcher(build_corpus(issues)),
        code=CodeSearcher(checkout, use_ripgrep=False),
        owners=CodeOwners.parse("/Lib/zipfile.py @zip-owner\n"),
        checkout_commit="abc123",
    )
