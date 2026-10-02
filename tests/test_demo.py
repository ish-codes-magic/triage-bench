"""The demo storyboard: built from a cascade run's files, with no model and no network."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triagelab.data.models import IssueSnapshot
from triagelab.data.storage import append_jsonl
from triagelab.decisions.live_cascade import ROUTES_FILE, Routing
from triagelab.demo import WIDTH, render_gif, render_text, storyboard, total_ms
from triagelab.eval.dataset import Gold
from triagelab.triage import TriageResult

TYPES = ["type-bug", "type-crash", "type-feature"]
REF = "o/r#7"
ISSUE = IssueSnapshot(
    issue_ref=REF, repo="o/r", number=7, title="Interpreter aborts on a deep recursion",
    body="Running the attached script ends with a fatal error.\n\nSecond paragraph.",
    author_association="NONE", created_at=datetime(2026, 6, 1, 9, 30, tzinfo=UTC),
)  # fmt: skip
GOLD = Gold(
    labels=frozenset({"type-crash", "interpreter-core"}), label_groups={}, human_triaged=True,
    duplicate_of=None, component="interpreter-core", needs_info=False,
)  # fmt: skip


def event(kind: str, **fields: Any) -> dict[str, Any]:
    return {"issue_ref": REF, "event": kind, **fields}


def write_run(run: Path, *, escalated: bool) -> None:
    """A cascade run folder for one issue, as the runner would leave it."""
    cheap = [
        event("llm", step=1, tokens_out=4000, tool_calls=[], cost_usd=0.001),
        event("end", answer=None, steps=1, cost_usd=0.001, forced=None),
    ]
    results = {"results": [{"number": 3, "labels": ["type-crash"]}, {"number": 2, "labels": []}]}
    full = [
        event("llm", step=1, tokens_out=120, tool_calls=[{"name": "search_similar_issues"}]),
        event(
            "tool", name="search_similar_issues", arguments={"query": "fatal error recursion"},
            output=json.dumps(results) + "\n[tool calls used: 1 of 15]", is_error=False,
        ),
        event(
            "tool", name="search_code", output=json.dumps({"hits": [{"path": "Python/ceval.c"}]}),
            arguments={"query": "Py_FatalError", "path_glob": "Python/*"}, is_error=False,
        ),
        event("tool", name="get_issue", arguments={"number": 99}, output="not available",
              is_error=True),
        event("end", answer={"labels": []}, steps=4, cost_usd=0.006, forced="max_steps"),
    ]  # fmt: skip
    for tier, events in (("cheap", cheap), ("full", full)):
        (run / tier).mkdir(parents=True)
        lines = "".join(json.dumps(e) + "\n" for e in events)
        (run / tier / "traces.jsonl").write_text(lines, encoding="utf-8")
    routing = Routing(
        issue_ref=REF, signal=0.0 if escalated else 0.85, tau=0.7, escalated=escalated,
        cheap_trace_id="c",
    )  # fmt: skip
    append_jsonl(run / ROUTES_FILE, [routing])
    final = TriageResult(
        issue_ref=REF, labels=["interpreter-core", "type-crash"], component="interpreter-core",
        triage_comment="Looks like a hard crash in the evaluation loop. " * 12, cost_usd=0.007,
        decided_by={"cascade": "escalated" if escalated else "cheap tier"},
    )  # fmt: skip
    append_jsonl(run / "predictions.jsonl", [final])


def test_an_escalated_issue_tells_all_three_stages(tmp_path: Path) -> None:
    write_run(tmp_path, escalated=True)
    text = render_text(storyboard(tmp_path, ISSUE, GOLD, TYPES))
    lines = text.splitlines()
    assert "o/r#7   opened 2026-06-01" in lines
    assert "   model call 1: 4,000 tokens, hit the output limit, no answer" in lines
    assert "   no answer after 1 model calls   $0.0010" in lines
    assert "2  gate: confidence 0.00 < τ 0.70   →   escalate to the full agent" in lines
    assert '   → search_similar_issues("fatal error recursion")   2 results, top #3' in lines
    assert '   → search_code("Py_FatalError", Python/*)   1 hits' in lines
    assert "   → get_issue(…)   refused: not available" in lines
    assert "   step limit reached: forced to answer now   $0.0060" in lines
    assert "result   (decided by the full agent, after escalation)" in lines
    assert "   labels      type-crash, interpreter-core" in lines  # the type label comes first
    assert lines[-1].endswith("✓ type   ✓ component")
    assert max(len(line) for line in lines) <= WIDTH
    comment = [line for line in lines if "Looks like a hard crash" in line]
    assert len(comment) == 3  # a long comment is cut to three lines
    assert comment[-1].endswith("…")


def test_a_kept_issue_never_shows_the_agent(tmp_path: Path) -> None:
    write_run(tmp_path, escalated=False)
    text = render_text(storyboard(tmp_path, ISSUE, None, TYPES))
    assert "2  gate: confidence 0.85 ≥ τ 0.70   →   the cheap answer stands" in text
    assert "full agent" not in text
    assert "result   (decided by the cheap tier)" in text
    assert "reference" not in text  # no reference given, none shown


def test_a_wrong_answer_is_marked_wrong(tmp_path: Path) -> None:
    write_run(tmp_path, escalated=True)
    other = GOLD.model_copy(update={"labels": frozenset({"type-bug"}), "component": "stdlib"})
    text = render_text(storyboard(tmp_path, ISSUE, other, TYPES))
    assert text.splitlines()[-1].endswith("✗ type   ✗ component")


def test_the_gif_has_one_frame_per_step_and_the_requested_length(tmp_path: Path) -> None:
    from PIL import Image, ImageSequence

    write_run(tmp_path, escalated=True)
    steps = storyboard(tmp_path, ISSUE, GOLD, TYPES)
    out = tmp_path / "figures" / "demo.gif"
    render_gif(steps, out, scale=60_000 / total_ms(steps))
    with Image.open(out) as gif:
        durations = [int(frame.info["duration"]) for frame in ImageSequence.Iterator(gif)]
    assert len(durations) == len(steps)
    assert abs(sum(durations) - 60_000) <= 10 * len(steps)  # GIF timing has 10 ms steps
