"""The agent smoke eval, replayed from recorded model responses: offline, free, deterministic.

It runs the real stack: `triagelab eval`'s runner, the agent loop, the CPython skill, and
repo-intel as a stdio subprocess over a synthetic corpus. Only the model is replaced, by
cassettes in tests/cassettes/agent-smoke. A CassetteMissError here means a prompt, skill,
tool output or agent setting changed, and the cassettes must be re-recorded (see
tests/smoke_dataset.py for the two commands).
"""

from pathlib import Path

from triagelab.config import load_config
from triagelab.eval.runner import run_eval
from triagelab.harness.trace_stats import agent_stats

from .smoke_dataset import AGENT_ISSUES, write_smoke_dataset


def test_agent_smoke_replays_from_cassettes(tmp_path: Path) -> None:
    cfg = load_config(write_smoke_dataset(tmp_path)["agent"])
    assert cfg.cache.replay_only
    outcome = run_eval(
        cfg,
        split="dev",
        runs_dir=cfg.paths.runs_dir,
        command="test",
        log=lambda _: None,
        limit=AGENT_ISSUES,
    )
    assert outcome.completed == AGENT_ISSUES
    assert outcome.scorecard is not None
    assert outcome.spent_usd == 0.0  # every model call came from a cassette
    stats = agent_stats(outcome.run_dir)
    assert stats.issues == AGENT_ISSUES
    assert "search_similar_issues" in stats.tools  # it really went through MCP
