"""File-based annotation: export batches for an annotator, validate and import their answers.

The Streamlit app is for a person. A model annotator (or anyone labeling offline) works
on files instead: `export_*` writes self-contained Markdown batches, and `import_*`
checks every answer against the same rules the app enforces before storing it through
the same stores. Records keep their `annotator`, so model labels are never confused with
human ones (ADR-0035).

Blindness is enforced by ordering, not trust: final-pass evidence can only be exported
for issues whose blind answers are already stored, and rating batches never name the
system that wrote a comment.
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from triagelab.data.profile import RepoProfile
from triagelab.eval.failure_tagger import trace_summary
from triagelab.eval.failures import Failure, find_failures
from triagelab.eval.report import Labels, examples_for, load_run
from triagelab.harness.trace_stats import load_events
from triagelab.labeling.failure_tags import SEED_CODES, FailureTag, FailureTagStore
from triagelab.labeling.gold import (
    Decision,
    GoldRecord,
    GoldStore,
    LabelingItem,
    gold_path,
    label_vocabulary,
    load_items,
)
from triagelab.labeling.ratings import Rating, RatingItem, RatingStore, Rubric

MAX_BODY_CHARS = 12_000  # what the systems see (system.max_body_chars)


class AnnotationError(ValueError):
    pass


def _batches[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _body(text: str) -> str:
    body = text or "(empty body)"
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + f"\n[... truncated at {MAX_BODY_CHARS} characters]"
    return body.replace("~~~", "~ ~ ~")  # keep the fence below unbreakable


def _issue_block(item: LabelingItem) -> str:
    s = item.snapshot
    return (
        f"## {s.issue_ref}\n\n"
        f"**{s.title}** · opened {s.created_at:%Y-%m-%d} · author: {s.author_association}\n\n"
        f"~~~text\n{_body(s.body)}\n~~~\n"
    )


def _write(out_dir: Path, name: str, text: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_bytes(text.encode("utf-8"))
    return path


def _read_lines(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(cast(dict[str, Any], json.loads(line)))
            except json.JSONDecodeError as err:
                raise AnnotationError(f"{path.name}:{n}: not JSON ({err})") from err
    return rows


# --- Gold labels ------------------------------------------------------------------------


def _check_decision(
    row: dict[str, Any], vocab: dict[str, list[str]], components: Sequence[str], where: str
) -> Decision:
    try:
        decision = Decision.model_validate(
            {k: row[k] for k in ("labels", "component", "needs_info", "duplicate_of") if k in row}
        )
    except ValidationError as err:
        raise AnnotationError(f"{where}: {err}") from err
    allowed = {label for group in vocab.values() for label in group}
    unknown = [x for x in decision.labels if x not in allowed]
    types = [x for x in decision.labels if x in vocab["type"]]
    if unknown:
        raise AnnotationError(f"{where}: labels not in the vocabulary: {unknown}")
    if len(types) != 1:
        raise AnnotationError(f"{where}: exactly one type label is required, got {types}")
    if decision.component is not None and decision.component not in components:
        raise AnnotationError(f"{where}: unknown component {decision.component!r}")
    return decision.model_copy(update={"labels": list(dict.fromkeys(decision.labels))})


def export_gold_blind(
    items: Sequence[LabelingItem],
    done: dict[str, GoldRecord],
    vocab: dict[str, list[str]],
    components: Sequence[str],
    out_dir: Path,
    batch_size: int = 20,
) -> list[Path]:
    todo = [i for i in items if i.snapshot.issue_ref not in done]
    header = (
        "# Gold labels, blind pass\n\n"
        "Label each issue from the text below only. Do not look anything up.\n\n"
        f"- Type labels (exactly one): {', '.join(vocab['type'])}\n"
        f"- Area labels (any that apply): {', '.join(vocab['area'])}\n"
        f"- Topic/OS labels (only if squarely about it): {', '.join(vocab['family'])}\n"
        f"- Components (or null if you can't tell): {', '.join(components)}\n\n"
        "Answer with one JSON object per line, e.g.\n"
        '`{"issue_ref": "python/cpython#1", "labels": ["type-bug", "stdlib"], '
        '"component": "stdlib", "needs_info": false}`\n\n'
    )
    return [
        _write(
            out_dir, f"gold-blind-{n:02d}.md", header + "\n".join(_issue_block(i) for i in batch)
        )
        for n, batch in enumerate(_batches(todo, batch_size), 1)
    ]


def import_gold_blind(
    path: Path,
    store: GoldStore,
    items: dict[str, LabelingItem],
    vocab: dict[str, list[str]],
    components: Sequence[str],
    annotator: str,
) -> int:
    rows = _read_lines(path)
    records: list[GoldRecord] = []
    for row in rows:
        ref = str(row.get("issue_ref"))
        if ref not in items:
            raise AnnotationError(f"{path.name}: unknown issue {ref!r}")
        decision = _check_decision(row, vocab, components, f"{path.name} {ref}")
        records.append(
            GoldRecord(
                issue_ref=ref,
                number=items[ref].snapshot.number,
                split=items[ref].split,
                blind=decision.model_copy(update={"duplicate_of": None}),
                annotator=annotator,
                blind_seconds=float(row.get("seconds", 0.0)),
                updated_at=datetime.now(UTC),
            )
        )
    for record in records:  # validate the whole file before storing any of it
        store.save(record)
    return len(records)


def _evidence_block(item: LabelingItem, blind: Decision) -> str:
    ev = item.evidence
    labels = ", ".join(f"{label} ({source})" for label, source in ev.labels) or "none"
    lines = [
        f"- Your blind answer: labels {blind.labels}, component {blind.component}, "
        f"needs_info {str(blind.needs_info).lower()}",
        f"- Labels applied afterwards: {labels}",
        f"- `pending` (needs info) applied: {'yes' if ev.needs_info else 'no'}",
        f"- Derived component: {ev.component} (votes: {json.dumps(ev.component_votes)})",
    ]
    if ev.duplicate_of:
        lines.append(
            f"- Closed as a duplicate of #{ev.duplicate_of} ({ev.duplicate_source}): "
            f"{ev.duplicate_title or '(title unknown)'}"
        )
    for pr in ev.fix_prs:
        lines.append(f"- Fix PR #{pr.number} ({pr.files_total} files): {pr.title}")
        lines += [f"  - {f}" for f in pr.files[:15]]
    return _issue_block(item) + "\n**What happened next**\n\n" + "\n".join(lines) + "\n"


def export_gold_final(
    items: Sequence[LabelingItem], done: dict[str, GoldRecord], out_dir: Path, batch_size: int = 20
) -> list[Path]:
    """Only issues with a stored blind answer and no final one: blind comes first."""
    todo = [
        i for i in items if (r := done.get(i.snapshot.issue_ref)) is not None and r.final is None
    ]
    header = (
        "# Gold labels, final pass\n\n"
        "The gold answer is what is true, given everything below. Start from your blind "
        "answer and change it only where the evidence convinces you; maintainers' labels "
        "and derived components can be wrong.\n\n"
        "Answer with one JSON object per line, adding `duplicate_of` (issue number or "
        "null), `unusable` (true for spam/non-issues) and `notes`, e.g.\n"
        '`{"issue_ref": "python/cpython#1", "labels": ["type-bug", "stdlib"], '
        '"component": "stdlib", "needs_info": false, "duplicate_of": null, '
        '"unusable": false, "notes": ""}`\n\n'
    )
    return [
        _write(
            out_dir,
            f"gold-final-{n:02d}.md",
            header + "\n".join(_evidence_block(i, done[i.snapshot.issue_ref].blind) for i in batch),
        )
        for n, batch in enumerate(_batches(todo, batch_size), 1)
    ]


def import_gold_final(
    path: Path,
    store: GoldStore,
    vocab: dict[str, list[str]],
    components: Sequence[str],
) -> int:
    done = store.load()
    updates: list[GoldRecord] = []
    for row in _read_lines(path):
        ref = str(row.get("issue_ref"))
        record = done.get(ref)
        if record is None:
            raise AnnotationError(f"{path.name}: no blind answer stored for {ref!r}")
        decision = _check_decision(row, vocab, components, f"{path.name} {ref}")
        updates.append(
            record.model_copy(
                update={
                    "final": decision,
                    "unusable": bool(row.get("unusable", False)),
                    "notes": str(row.get("notes", "")),
                    "updated_at": datetime.now(UTC),
                }
            )
        )
    for record in updates:
        store.save(record)
    return len(updates)


# --- Comment ratings --------------------------------------------------------------------


def export_ratings(
    items: Sequence[RatingItem],
    issues: dict[str, LabelingItem],
    rubric: Rubric,
    done: set[str],
    out_dir: Path,
    batch_size: int = 25,
) -> list[Path]:
    """The system that wrote each comment is never written to the batch."""
    todo = [i for i in items if i.item_id not in done]
    criteria = "\n".join(
        f"- **{c.name}**: {c.question}\n"
        + "\n".join(f"  - {level}: {text}" for level, text in sorted(c.levels.items()))
        for c in rubric.criteria
    )
    header = (
        "# Rate draft triage comments\n\n"
        f"Score every criterion 1-4 using only these descriptions:\n\n{criteria}\n\n"
        "Answer with one JSON object per line, e.g.\n"
        '`{"item_id": "…", "scores": {'
        + ", ".join(f'"{c.name}": 3' for c in rubric.criteria)
        + "}}`\n\n"
    )

    def block(opaque_id: str, item: RatingItem) -> str:
        issue = issues[item.issue_ref]
        ev = issue.evidence
        facts = (
            f"labels applied: {', '.join(label for label, _ in ev.labels) or 'none'}; "
            f"component: {ev.component}; needs info: {'yes' if ev.needs_info else 'no'}"
            + (f"; duplicate of #{ev.duplicate_of}" if ev.duplicate_of else "")
        )
        return (
            f"### item_id: {opaque_id}\n\n"
            + _issue_block(issue)
            + f"\n**What happened next:** {facts}\n\n"
            + f"**Draft comment:**\n\n~~~text\n{item.comment}\n~~~\n"
        )

    # Item ids name the system ("<ref>:<system>"), so batches use opaque ids, and the
    # mapping back is kept in a separate key file the annotator doesn't need to read.
    files: list[Path] = []
    for n, batch in enumerate(_batches(todo, batch_size), 1):
        key = {f"r{n:02d}-{k:02d}": item for k, item in enumerate(batch, 1)}
        text = header + "\n".join(block(opaque, item) for opaque, item in key.items())
        files.append(_write(out_dir, f"ratings-{n:02d}.md", text))
        key_json = json.dumps({opaque: item.item_id for opaque, item in key.items()})
        _write(out_dir.parent / f"{out_dir.name}-keys", f"ratings-{n:02d}.key.json", key_json)
    return files


def import_ratings(
    path: Path, key_path: Path, store: RatingStore, rubric: Rubric, annotator: str
) -> int:
    key = cast(dict[str, str], json.loads(key_path.read_text(encoding="utf-8")))
    names = [c.name for c in rubric.criteria]
    ratings: list[Rating] = []
    for row in _read_lines(path):
        opaque = str(row.get("item_id"))
        if opaque not in key:
            raise AnnotationError(f"{path.name}: unknown item {opaque!r}")
        scores = cast(dict[str, Any], row.get("scores") or {})
        if sorted(scores) != sorted(names) or any(s not in rubric.scale for s in scores.values()):
            raise AnnotationError(f"{path.name} {opaque}: need {names} scored in {rubric.scale}")
        ratings.append(
            Rating(
                item_id=key[opaque],
                scores={k: int(v) for k, v in scores.items()},
                rubric_version=rubric.version,
                annotator=annotator,
                seconds=float(row.get("seconds", 0.0)),
                rated_at=datetime.now(UTC),
            )
        )
    for rating in ratings:
        store.save(rating)
    return len(ratings)


# --- Failure tags -----------------------------------------------------------------------


def export_failures(
    run_id: str,
    failures: Sequence[Failure],
    events: dict[str, list[dict[str, Any]]],
    issues: dict[str, LabelingItem],
    done: set[str],
    out_dir: Path,
    limit: int,
    batch_size: int = 25,
) -> list[Path]:
    todo = [f for f in failures if f.issue_ref not in done][:limit]
    header = (
        f"# Failure review (run {run_id})\n\n"
        "For each failure, write short codes for *why* the agent got it wrong. Start from "
        f"these seed codes: {', '.join(SEED_CODES)}. Invent a new short code when none "
        "fits, and reuse your own codes.\n\n"
        "Answer with one JSON object per line: "
        '`{"issue_ref": "…", "codes": ["…"], "note": "…"}`\n\n'
    )

    def block(f: Failure) -> str:
        issue = issues.get(f.issue_ref)
        wrong = "\n".join(f"- {task}: {detail}" for task, detail in f.details.items())
        head = _issue_block(issue) if issue else f"## {f.issue_ref}\n"
        return (
            f"{head}\n**What the agent got wrong**\n\n{wrong}\n\n**Agent steps**\n\n"
            f"~~~text\n{trace_summary(events.get(f.trace_id, []))}\n~~~\n"
        )

    return [
        _write(out_dir, f"failures-{n:02d}.md", header + "\n".join(block(f) for f in batch))
        for n, batch in enumerate(_batches(todo, batch_size), 1)
    ]


class _TagRow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    issue_ref: str
    codes: list[str]
    note: str = ""


def import_failure_tags(
    path: Path,
    run_id: str,
    failures: dict[str, Failure],
    store: FailureTagStore,
    annotator: str,
) -> int:
    tags: list[FailureTag] = []
    for row in _read_lines(path):
        try:
            parsed = _TagRow.model_validate(row)
        except ValidationError as err:
            raise AnnotationError(f"{path.name}: {err}") from err
        failure = failures.get(parsed.issue_ref)
        codes = [c.strip() for c in parsed.codes if c.strip()]
        if failure is None or not codes:
            raise AnnotationError(
                f"{path.name}: {parsed.issue_ref!r} is not a failure or has no codes"
            )
        tags.append(
            FailureTag(
                run_id=run_id,
                issue_ref=parsed.issue_ref,
                tasks=failure.tasks,
                codes=codes,
                note=parsed.note,
                annotator=annotator,
                tagged_at=datetime.now(UTC),
            )
        )
    for tag in tags:
        store.save(tag)
    return len(tags)


# --- Loading what the commands need -----------------------------------------------------


class GoldContext(NamedTuple):
    items: list[LabelingItem]
    store: GoldStore
    vocab: dict[str, list[str]]
    components: list[str]


def gold_context(data_dir: Path, profile: RepoProfile) -> GoldContext:
    return GoldContext(
        items=load_items(data_dir, profile),
        store=GoldStore(gold_path(data_dir, profile)),
        vocab=label_vocabulary(data_dir, profile),
        components=[c.name for c in profile.components],
    )


def run_failures(
    run_dir: Path, labels: Labels
) -> tuple[list[Failure], dict[str, list[dict[str, Any]]]]:
    """A run's failures against silver or gold, and its trace events by trace id."""
    run_cfg, split, _ = load_run(run_dir)
    predictions, events = load_events(run_dir)
    return find_failures(examples_for(run_cfg, split, labels), predictions), dict(events)
