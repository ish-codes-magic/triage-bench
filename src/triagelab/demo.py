"""The demo (AGENTS.md §17): one issue's path through the live cascade, told from its traces.

Nothing here calls a model. `storyboard` reads a finished cascade run (each tier's
traces, the routing log, the final prediction) and turns one issue into the lines a
terminal would have shown; `render_gif` draws them one step at a time. The GIF is
therefore regenerated from the run registry like every other figure, and shows what the
system did, including the parts that don't flatter it (a tier that ran out of tokens, an
agent that was forced to answer at its step limit).
"""

import json
import textwrap
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from triagelab.data.models import IssueSnapshot
from triagelab.data.storage import read_jsonl
from triagelab.decisions.live_cascade import ROUTES_FILE, Routing
from triagelab.eval.dataset import Gold
from triagelab.triage import TriageResult

Style = Literal["plain", "dim", "head", "accent", "good", "warn"]
WIDTH = 100  # terminal columns
OUTPUT_LIMIT_SHARE = 0.975  # a call this close to max_tokens ran out of room
INDENT = "   "


@dataclass(frozen=True)
class Line:
    text: str
    style: Style = "plain"


@dataclass(frozen=True)
class Step:
    """Lines that appear together, and how long the screen then rests (in the GIF)."""

    lines: tuple[Line, ...]
    hold_ms: int = 1800


def _events(traces: Path, issue_ref: str) -> list[dict[str, Any]]:
    if not traces.is_file():
        return []
    with traces.open(encoding="utf-8") as f:
        events = [json.loads(line) for line in f]
    return [e for e in events if e.get("issue_ref") == issue_ref]


def _clip(text: str, width: int) -> str:
    """`text` on one line, at most `width` characters."""
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def _wrap(text: str, width: int, rows: int) -> list[str]:
    """`text` wrapped to at most `rows` lines, the last one ending in … if it was cut."""
    lines = textwrap.wrap(" ".join(text.split()), width)
    if len(lines) > rows:
        lines = [*lines[: rows - 1], _clip(lines[rows - 1] + " …", width)]
    return lines


def _parsed(output: str) -> dict[str, Any]:
    """A tool result's JSON object; results end with a budget note and may be cut short."""
    try:
        data, _ = json.JSONDecoder().raw_decode(output)
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, Any], data) if isinstance(data, dict) else {}


def _tool_summary(name: str, arguments: dict[str, Any], output: str, is_error: bool) -> str:
    """One line per tool call: what was asked, and the size of what came back."""
    if is_error:
        return f"{name}(…)   refused: {_clip(output, 50)}"
    data = _parsed(output)
    query = str(arguments.get("query", ""))
    if name == "search_similar_issues":
        results = cast(list[dict[str, Any]], data.get("results", []))
        top = f", top #{results[0]['number']}" if results else ""
        return f'search_similar_issues("{_clip(query, 44)}")   {len(results)} results{top}'
    if name == "get_issue":
        return f"get_issue(#{arguments.get('number')})"
    if name == "search_code":
        where = f", {arguments['path_glob']}" if arguments.get("path_glob") else ""
        hits = cast(list[Any], data.get("hits", []))
        return f'search_code("{_clip(query, 30)}"{where})   {len(hits)} hits'
    if name == "get_codeowners":
        return f"get_codeowners({arguments.get('path')})   component {data.get('component')}"
    if name in ("load_skill", "read_skill_file"):
        target = "/".join(str(arguments[k]) for k in ("name", "path") if k in arguments)
        return f"{name}({target})"
    return f"{name}(…)"


def _tier_steps(events: Sequence[dict[str, Any]], max_tokens: int) -> Iterator[Step]:
    """A tier's tool calls and exhausted model calls, in order, then how it ended."""
    for e in events:
        cost = f"${e.get('cost_usd', 0.0):.4f}"
        if e["event"] == "llm":
            out = int(e["tokens_out"])
            if out >= max_tokens * OUTPUT_LIMIT_SHARE and not e["tool_calls"]:
                text = f"model call {e['step']}: {out:,} tokens, hit the output limit, no answer"
                yield Step((Line(INDENT + text, "warn"),))
        elif e["event"] == "tool":
            summary = _tool_summary(e["name"], e["arguments"], e["output"], bool(e["is_error"]))
            yield Step((Line(INDENT + "→ " + summary[: WIDTH - 5]),), hold_ms=1300)
        elif e["event"] == "end":
            if e["answer"] is None:
                text = f"no answer after {e['steps']} model calls   {cost}"
                yield Step((Line(INDENT + text, "warn"),))
            elif e.get("forced"):
                limit = str(e["forced"]).removeprefix("max_").removesuffix("s").replace("_", " ")
                text = f"{limit} limit reached: forced to answer now   {cost}"
                yield Step((Line(INDENT + text, "warn"),))
            else:
                text = f"answered after {e['steps']} model calls   {cost}"
                yield Step((Line(INDENT + text, "good"),))


def _mark(ok: bool) -> str:
    return "✓" if ok else "✗"


def _result(final: TriageResult, types: Sequence[str], escalated: bool) -> Step:
    kind = [label for label in final.labels if label in types]
    others = [label for label in final.labels if label not in types]
    by = "the full agent, after escalation" if escalated else "the cheap tier"
    duplicate = f"#{final.duplicate_of}" if final.duplicate_of else "none"
    comment = _wrap(f'"{final.triage_comment}"', WIDTH - 15, 3)
    return Step(
        (
            Line(""),
            Line(f"result   (decided by {by})", "head"),
            Line(f"{INDENT}labels      {', '.join([*kind, *others]) or 'none'}"),
            Line(f"{INDENT}component   {final.component or 'none'}"),
            Line(f"{INDENT}duplicate   {duplicate}"),
            *(
                Line((f"{INDENT}comment     " if i == 0 else " " * 15) + row, "dim")
                for i, row in enumerate(comment)
            ),
            Line(f"{INDENT}cost        ${final.cost_usd:.4f} for this issue, all tiers", "dim"),
        ),
        5000,
    )


def storyboard(
    run_dir: Path,
    issue: IssueSnapshot,
    reference: Gold | None,
    types: Sequence[str],
    *,
    max_tokens: int = 4000,
) -> list[Step]:
    """Every step of `issue` through the cascade run in `run_dir`."""
    ref = issue.issue_ref
    routing = next(r for r in read_jsonl(run_dir / ROUTES_FILE, Routing) if r.issue_ref == ref)
    final = next(
        p for p in read_jsonl(run_dir / "predictions.jsonl", TriageResult) if p.issue_ref == ref
    )
    opened = f"{issue.created_at:%Y-%m-%d}"
    steps = [
        Step((Line("$ triagelab eval -c configs/experiments/cascade.yaml", "head"),), 1200),
        Step(
            (
                Line(""),
                Line(f"{ref}   opened {opened}", "dim"),
                Line(f"  {_clip(issue.title, WIDTH - 4)}", "head"),
                *(Line(f"  {row}", "dim") for row in _wrap(issue.body, WIDTH - 4, 3)),
            ),
            3500,
        ),
        Step(
            (
                Line(""),
                Line(
                    "1  cheap tier: similar past issues pasted into the prompt, no tools", "accent"
                ),
            )
        ),
        *_tier_steps(_events(run_dir / "cheap" / "traces.jsonl", ref), max_tokens),
    ]
    verdict = "escalate to the full agent" if routing.escalated else "the cheap answer stands"
    sign = "<" if routing.escalated else "≥"
    gate = f"2  gate: confidence {routing.signal:.2f} {sign} τ {routing.tau:.2f}   →   {verdict}"
    steps.append(Step((Line(""), Line(gate, "warn" if routing.escalated else "good")), 3000))
    if routing.escalated:
        heading = f"3  full agent: tools over MCP, each limited to what existed on {opened}"
        steps.append(Step((Line(""), Line(heading, "accent"))))
        steps.extend(_tier_steps(_events(run_dir / "full" / "traces.jsonl", ref), max_tokens))
    steps.append(_result(final, types, routing.escalated))
    if reference is not None:
        kind = sorted(label for label in final.labels if label in types)
        ref_kind = sorted(label for label in reference.labels if label in types)
        type_ok = kind == ref_kind
        component_ok = reference.component is not None and final.component == reference.component
        text = (
            f"reference   {', '.join(ref_kind) or 'none'} · component {reference.component}"
            f"      {_mark(type_ok)} type   {_mark(component_ok)} component"
        )
        style: Style = "good" if type_ok and component_ok else "warn"
        steps.append(Step((Line(""), Line(text, style)), 8000))
    return steps


def render_text(steps: Sequence[Step]) -> str:
    """The finished screen as plain text (for the docs, and for tests)."""
    return "\n".join(line.text for step in steps for line in step.lines) + "\n"


# Terminal colours (GitHub dark).
_BACKGROUND = (13, 17, 23)
_COLOURS: dict[Style, tuple[int, int, int]] = {
    "plain": (201, 209, 217),
    "dim": (139, 148, 158),
    "head": (240, 246, 252),
    "accent": (88, 166, 255),
    "good": (63, 185, 80),
    "warn": (210, 153, 34),
}


def render_gif(
    steps: Sequence[Step],
    out: Path,
    *,
    max_rows: int = 44,
    font_size: int = 15,
    scale: float = 1.0,
) -> None:
    """Draw the steps as a terminal that fills up line by line.

    The terminal is as tall as the whole story, up to `max_rows`; a longer story scrolls.
    `scale` stretches every hold, to bring the whole animation to the length wanted.
    """
    rows = min(max_rows, sum(len(step.lines) for step in steps))
    import matplotlib
    from PIL import Image, ImageDraw, ImageFont

    fonts = Path(matplotlib.get_data_path()) / "fonts" / "ttf"  # DejaVu ships with matplotlib
    regular = ImageFont.truetype(str(fonts / "DejaVuSansMono.ttf"), font_size)
    bold = ImageFont.truetype(str(fonts / "DejaVuSansMono-Bold.ttf"), font_size)
    char_w, line_h, pad = round(regular.getlength("M")), round(font_size * 1.45), 18
    size = (WIDTH * char_w + 2 * pad, rows * line_h + 2 * pad)

    frames: list[Image.Image] = []
    holds: list[int] = []
    screen: list[Line] = []
    for step in steps:
        screen.extend(step.lines)
        image = Image.new("RGB", size, _BACKGROUND)
        draw = ImageDraw.Draw(image)
        for row, line in enumerate(screen[-rows:]):
            font = bold if line.style in ("head", "accent") else regular
            draw.text((pad, pad + row * line_h), line.text, font=font, fill=_COLOURS[line.style])
        frames.append(image.quantize(colors=32, method=Image.Quantize.MEDIANCUT))
        holds.append(round(step.hold_ms * scale))
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out, save_all=True, append_images=frames[1:], duration=holds, loop=0, optimize=True
    )


def total_ms(steps: Sequence[Step]) -> int:
    return sum(step.hold_ms for step in steps)
