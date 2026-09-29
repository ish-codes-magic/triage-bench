"""Load repo-intel's state from disk and serve it over stdio.

    python -m triagelab.mcp_server --profile configs/repos/python__cpython.yaml
    triagelab mcp serve --profile configs/repos/python__cpython.yaml

For the MCP Inspector (Node >= 22.19):
    npx @modelcontextprotocol/inspector uv run python -m triagelab.mcp_server -p <profile>
"""

import argparse
import os
from datetime import datetime
from functools import partial
from pathlib import Path

from triagelab.data.checkout import CheckoutInfo, checkout_dir
from triagelab.data.profile import load_profile
from triagelab.mcp_server.code_search import CodeSearcher
from triagelab.mcp_server.codeowners import CodeOwners
from triagelab.mcp_server.server import RepoIntel, build_server
from triagelab.retrieval.dense import Encoder
from triagelab.retrieval.index import load_searcher
from triagelab.retrieval.search import HybridSearcher


def load_intel(
    profile_path: Path,
    data_dir: Path,
    *,
    dense: bool = True,
    as_of_ceiling: datetime | None = None,
) -> RepoIntel:
    profile = load_profile(profile_path)

    def build_searcher() -> HybridSearcher:
        encoder: Encoder | None = None
        if dense:
            from triagelab.retrieval.encoders import FastEmbedEncoder

            encoder = FastEmbedEncoder()
        return load_searcher(data_dir, profile, encoder=encoder)

    root = checkout_dir(data_dir, profile)
    info_path = root / "checkout.json"
    commit = (
        CheckoutInfo.model_validate_json(info_path.read_text(encoding="utf-8")).commit
        if info_path.is_file()
        else "unknown"
    )
    return RepoIntel(
        profile=profile,
        searcher=build_searcher,  # built lazily on the first search (see RepoIntel)
        code=CodeSearcher(root) if root.is_dir() else None,
        owners=CodeOwners.from_checkout(root) if root.is_dir() else CodeOwners([]),
        checkout_commit=commit,
        as_of_ceiling=as_of_ceiling,
    )


def main(argv: list[str] | None = None) -> None:
    # Every option can also come from the environment, so launchers that take no
    # arguments (e.g. the MCP Inspector, IDE configs) can configure the server.
    env = partial(os.environ.get)
    parser = argparse.ArgumentParser(prog="repo-intel", description=__doc__)
    parser.add_argument(
        "-p",
        "--profile",
        type=Path,
        default=env("REPO_INTEL_PROFILE"),
        required=env("REPO_INTEL_PROFILE") is None,
    )
    parser.add_argument("--data-dir", type=Path, default=Path(env("REPO_INTEL_DATA_DIR", "data")))
    parser.add_argument(
        "--no-dense",
        action="store_true",
        default=env("REPO_INTEL_DENSE", "1") == "0",
        help="BM25 only (no model load). Env: REPO_INTEL_DENSE=0.",
    )
    parser.add_argument(
        "--as-of-ceiling",
        type=datetime.fromisoformat,
        default=None,
        help="Reject any as_of later than this ISO 8601 time.",
    )
    args = parser.parse_args(argv)
    intel = load_intel(
        args.profile, args.data_dir, dense=not args.no_dense, as_of_ceiling=args.as_of_ceiling
    )
    build_server(intel).run()  # stdio transport
