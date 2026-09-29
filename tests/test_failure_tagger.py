"""The failure tagger: taxonomy mapping, trace summaries, tagging, agreement, run counts."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from triagelab.config import LLMConfig
from triagelab.eval.failure_tagger import (
    FailureTagger,
    TaggedFailure,
    category_counts,
    human_categories,
    load_taxonomy,
    tag_agreement,
    trace_summary,
    write_failures,
)
from triagelab.eval.failures import Failure
from triagelab.labeling.failure_tags import SEED_CODES, FailureTag

from .fakes import FAKE_MODEL, FakeBackend, make_client

TAXONOMY = load_taxonomy(Path(__file__).resolve().parents[1] / "configs/failures/taxonomy.yaml")
FAILURE = Failure(
    issue_ref="o/r#1", trace_id="t", tasks=["T3"], details={"T3": "said docs, truth stdlib"}
)
EVENTS = [
    {
        "event": "llm",
        "step": 1,
        "tool_calls": [{"name": "search_code", "arguments": '{"query": "x"}'}],
    },
    {"event": "tool", "name": "search_code", "output": "Lib/x.py:1", "is_error": False},
    {"event": "end", "stop_reason": "submitted", "forced": "max_steps"},
]


def test_seed_taxonomy_covers_every_seed_code() -> None:
    assert {TAXONOMY.category_of(code) for code in SEED_CODES} == set(TAXONOMY.names())


def test_human_codes_map_to_categories_and_unknown_codes_drop() -> None:
    tag = FailureTag(
        run_id="r", issue_ref="o/r#1", tasks=["T3"], codes=["retrieval miss", "my new code"],
        annotator="t", tagged_at=datetime(2026, 9, 30, tzinfo=UTC),
    )  # fmt: skip
    assert human_categories(tag, TAXONOMY) == {"retrieval miss"}


def test_trace_summary_keeps_calls_results_and_the_stop_reason() -> None:
    text = trace_summary(EVENTS)
    assert 'step 1: search_code({"query": "x"})' in text
    assert "-> search_code: Lib/x.py:1" in text
    assert "forced: max_steps" in text
    assert trace_summary(EVENTS * 200, limit_chars=500).endswith("[... trace truncated]")


def test_tagger_keeps_only_known_categories(tmp_path: Path) -> None:
    reply = json.dumps({"reasoning": "r", "categories": ["budget exhaustion", "made up"]})
    tagger = FailureTagger(
        make_client(tmp_path, FakeBackend(text=reply)), LLMConfig(model=FAKE_MODEL), TAXONOMY
    )
    tagged = tagger.tag(FAILURE, EVENTS, "a title")
    assert tagged.categories == ["budget exhaustion"]
    assert tagged.details == FAILURE.details


def test_tag_agreement_by_hand() -> None:
    human = {"a": {"retrieval miss"}, "b": {"budget exhaustion"}, "c": {"retrieval miss"}}
    llm = {"a": {"retrieval miss"}, "b": {"retrieval miss"}, "c": {"retrieval miss"}}
    rows, exact, jaccard = tag_agreement(human, llm, ["retrieval miss", "budget exhaustion"])
    by = {r.category: r for r in rows}
    assert (by["retrieval miss"].human, by["retrieval miss"].llm) == (2, 3)
    assert exact == pytest.approx(2 / 3)
    assert jaccard == pytest.approx(2 / 3)  # a and c match; b shares nothing


def test_failures_file_feeds_the_category_counts(tmp_path: Path) -> None:
    assert category_counts(tmp_path) is None
    tagged = [
        TaggedFailure(
            issue_ref=f"o/r#{n}",
            tasks=["T1"],
            details={"T1": "x"},
            categories=cats,
            reasoning="r",
            cost_usd=0.0,
        )
        for n, cats in enumerate([["retrieval miss"], ["retrieval miss", "budget exhaustion"]])
    ]
    write_failures(tmp_path, tagged, taxonomy_version=0)
    assert category_counts(tmp_path) == {"retrieval miss": 2, "budget exhaustion": 1}
