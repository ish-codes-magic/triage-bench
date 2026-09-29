"""A synthetic dataset for CI smoke evals: realistic structure, no GitHub or model access.

`python -m tests.smoke_dataset <dir>` writes raw issues, builds them with the real
pipeline, builds a BM25 retrieval corpus, and writes experiment configs pointing at
them. CI then runs the baselines and the agent through `triagelab eval` exactly as on
real data.

The agent config replays recorded model responses (cassettes, `tests/cassettes/`) and
fails on any request that wasn't recorded, so CI is free and deterministic. To record
them again after a prompt, skill or tool change (needs OPENROUTER_API_KEY, ~5 cents):

    uv run python -m tests.smoke_dataset smoke --record
    uv run triagelab eval -c smoke/agent.yaml --split dev --limit 10
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from triagelab.data.build import build_dataset
from triagelab.data.collect import raw_paths
from triagelab.data.models import Actor, IssueRef, LabelEvent, LinkedPR, PRFiles, RawIssue
from triagelab.data.profile import load_profile
from triagelab.data.storage import append_jsonl
from triagelab.retrieval.index import build_corpus_from_raw, corpus_path

from .data_fixtures import raw

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO_ROOT / "configs" / "repos" / "python__cpython.yaml"
CASSETTES = REPO_ROOT / "tests" / "cassettes" / "agent-smoke"
AGENT_ISSUES = 10  # how many dev issues the agent smoke eval covers
TRIAGER = Actor(login="triager", is_bot=False)

# component -> (vocabulary, type label, file path)
TOPICS = {
    "stdlib": ("asyncio pathlib glob event loop task cancel", "type-bug", "Lib/asyncio/tasks.py"),
    "interpreter-core": (
        "segfault refcount dealloc bytecode eval loop",
        "type-crash",
        "Objects/listobject.c",
    ),
    "extension-modules": (
        "_sqlite3 C module cursor sqlite binding",
        "type-bug",
        "Modules/_sqlite/cursor.c",
    ),
    "docs": ("documentation typo howto sphinx wording", "type-feature", "Doc/library/os.rst"),
}


def _issue(n: int, created: datetime, comp: str, i: int) -> tuple[RawIssue, PRFiles | None]:
    words, type_label, path = TOPICS[comp]
    needs_info = i % 7 == 0
    body = f"{words} observed in scenario {i % 5}." + (
        " Cannot reproduce, version unknown." if needs_info else ""
    )
    labels = (type_label, comp)
    events = tuple(
        LabelEvent(at=created + timedelta(hours=1), label=lab, added=True, actor=TRIAGER)
        for lab in (*labels, *(("pending",) if needs_info else ()))
    )
    fixed = i % 3 != 0
    pr_number = 100_000 + n
    issue = raw().model_copy(
        update={
            "number": n,
            "created_at": created,
            "title": f"{words.split()[0]} problem {n}",
            "body": body,
            "last_edited_at": None,
            "original_body": None,
            "title_renames": (),
            "labels_current": labels,
            "label_events": events,
            "linked_prs": (
                LinkedPR(
                    number=pr_number,
                    title=f"gh-{n}: fix",
                    merged=True,
                    merged_at=created,
                    base_ref="main",
                    via="cross_reference",
                ),
            )
            if fixed
            else (),
        }
    )
    files = (
        PRFiles(repo=issue.repo, number=pr_number, files=(path,), files_total=1) if fixed else None
    )
    return issue, files


def write_smoke_dataset(root: Path, *, record: bool = False) -> dict[str, Path]:
    profile = load_profile(PROFILE_PATH)
    w = profile.windows
    starts = {
        "train": datetime.combine(w.history_start, datetime.min.time(), tzinfo=UTC),
        "dev": datetime.combine(w.eval_start, datetime.min.time(), tzinfo=UTC),
        "test": datetime.combine(w.test_start, datetime.min.time(), tzinfo=UTC),
    }
    issues: list[RawIssue] = []
    pr_files: list[PRFiles] = []
    n = 1
    for window, count in (("train", 120), ("dev", 40), ("test", 20)):
        for i in range(count):
            comp = list(TOPICS)[i % len(TOPICS)]
            issue, files = _issue(n, starts[window] + timedelta(hours=i), comp, i)
            if window != "train" and i % 9 == 4:  # duplicates of an earlier train issue
                original = IssueRef(number=max(1, n - 100), created_at=starts["train"])
                issue = issue.model_copy(
                    update={"state_reason": "DUPLICATE", "duplicate_of": original}
                )
            issues.append(issue)
            pr_files += [files] if files else []
            n += 1

    data_dir = root / "data"
    issues_path, prs_path = raw_paths(data_dir, profile)
    issues_path.parent.mkdir(parents=True, exist_ok=True)
    issues_path.write_bytes(b"")
    prs_path.write_bytes(b"")
    append_jsonl(issues_path, issues)
    append_jsonl(prs_path, pr_files)
    build_dataset(profile, data_dir, root / "reports")
    build_corpus_from_raw(data_dir, profile).save(corpus_path(data_dir, profile))

    configs: dict[str, Path] = {}
    for kind in ("majority", "classifier", "agent"):
        # Replayed runs spend nothing; a recording run's spend must count against the
        # project's all-time budget, so it uses the real ledger.
        ledger = (
            REPO_ROOT / "runs" / "spend_ledger.jsonl"
            if kind == "agent" and record
            else root / "runs" / "ledger.jsonl"
        )
        cfg: dict[str, object] = {
            "extends": (REPO_ROOT / "configs" / "experiments" / "agent.yaml").as_posix()
            if kind == "agent"
            else (REPO_ROOT / "configs" / "base.yaml").as_posix(),
            "name": f"smoke-{kind}",
            "system": {"kind": kind, "min_label_count": 3},
            "paths": {
                "runs_dir": (root / "runs").as_posix(),
                "prices_file": (REPO_ROOT / "configs" / "prices.yaml").as_posix(),
                "ledger_file": ledger.as_posix(),
            },
            "dataset": {
                "profile": PROFILE_PATH.as_posix(),
                "data_dir": data_dir.as_posix(),
                "reports_dir": (root / "reports").as_posix(),
            },
            "eval": {"concurrency": 2, "bootstrap_resamples": 200},
        }
        if kind == "agent":
            cfg["system"] = {
                "kind": "agent",
                "min_label_count": 3,
                "agent": {
                    "skills": ["triage-cpython"],
                    "skills_dir": (REPO_ROOT / "skills").as_posix(),
                    # No source checkout in CI, so no code search or CODEOWNERS.
                    "tools": ["search_similar_issues", "get_issue", "list_components"],
                    "budget": {"max_steps": 8, "max_tool_calls": 6},
                    "mcp": {"transport": "stdio", "dense": False},
                },
            }
            cfg["cache"] = {"dir": CASSETTES.as_posix(), "replay_only": not record}
        path = root / f"{kind}.yaml"
        path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
        configs[kind] = path
    return configs


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--record"]
    out = Path(args[0] if args else "smoke")
    for kind, path in write_smoke_dataset(out, record="--record" in sys.argv).items():
        print(f"{kind}: {path.as_posix()}")
