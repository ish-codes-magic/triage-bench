"""LLM-assisted failure tagging, validated against a person's tags (AGENTS.md §12.6).

The taxonomy (configs/failures/taxonomy.yaml) maps each category to the open codes a
person used for it, so human tags and LLM tags meet on the same categories. The tagger
sees the failure (what differed, per task) and a compact trace, and picks every category
that applies, explaining first. Before its counts are trusted, it's compared with the
person's tags: per-category kappa on presence, exact set agreement, and mean Jaccard.
"""

import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from triagelab.config import LLMConfig
from triagelab.data.storage import read_parquet, write_parquet
from triagelab.eval.agreement import cohen_kappa
from triagelab.eval.failures import Failure
from triagelab.labeling.failure_tags import FailureTag
from triagelab.llm_client import LLMClient, LLMRequest, Message

TAGGER_PROMPT_VERSION = 1
FAILURES_FILE = "failures.parquet"


class Category(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    definition: str
    codes: list[str]


class Taxonomy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    categories: list[Category]

    def names(self) -> list[str]:
        return [c.name for c in self.categories]

    def category_of(self, code: str) -> str | None:
        return next((c.name for c in self.categories if code in c.codes), None)


def load_taxonomy(path: Path) -> Taxonomy:
    return Taxonomy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def human_categories(tag: FailureTag, taxonomy: Taxonomy) -> set[str]:
    """The person's open codes, mapped to categories (unmapped codes are dropped)."""
    return {c for code in tag.codes if (c := taxonomy.category_of(code)) is not None}


def trace_summary(events: Sequence[dict[str, Any]], limit_chars: int = 6_000) -> str:
    """The agent's steps in a few lines each: what it called and what came back."""
    lines: list[str] = []
    for e in events:
        if e.get("event") == "llm":
            calls = ", ".join(
                f"{c['name']}({str(c['arguments'])[:160]})" for c in e.get("tool_calls", [])
            )
            lines.append(f"step {e['step']}: {calls or 'text: ' + str(e.get('text', ''))[:160]}")
        elif e.get("event") == "tool":
            status = "ERROR " if e.get("is_error") else ""
            lines.append(f"  -> {e['name']}: {status}{str(e.get('output', ''))[:240]}")
        elif e.get("event") == "end":
            lines.append(f"stopped: {e.get('stop_reason')} (forced: {e.get('forced')})")
    text = "\n".join(lines)
    return text if len(text) <= limit_chars else text[:limit_chars] + "\n[... trace truncated]"


SYSTEM = """You diagnose why an AI agent triaged a GitHub issue wrongly. The agent searched \
earlier issues and the code with tools, then submitted labels, a component, a possible \
duplicate and whether more information was needed.

Given what it got wrong and a summary of its steps, choose every failure category that \
explains the error (usually one or two). Use only these categories:

{categories}

Explain your reasoning in two or three sentences first, then list the categories."""


class TaggerVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasoning: str
    categories: list[str]


class TaggedFailure(BaseModel):
    issue_ref: str
    tasks: list[str]
    details: dict[str, str]
    categories: list[str]
    reasoning: str
    cost_usd: float


class FailureTagger:
    def __init__(self, client: LLMClient, llm: LLMConfig, taxonomy: Taxonomy) -> None:
        self._client = client
        self._llm = llm
        self._taxonomy = taxonomy
        self._system = SYSTEM.format(
            categories="\n".join(f"- {c.name}: {c.definition}" for c in taxonomy.categories)
        )

    def tag(self, failure: Failure, events: Sequence[dict[str, Any]], title: str) -> TaggedFailure:
        wrong = "\n".join(f"- {task}: {detail}" for task, detail in failure.details.items())
        user = (
            f"Issue: {title}\n\nWhat the agent got wrong:\n{wrong}\n\n"
            f"Agent steps:\n{trace_summary(events)}"
        )
        request = LLMRequest(
            model=self._llm.model,
            route=self._llm.route,
            messages=(
                Message(role="system", content=self._system),
                Message(role="user", content=user),
            ),
            max_tokens=self._llm.max_tokens,
            temperature=self._llm.temperature,
            seed=self._llm.seed,
            reasoning=self._llm.reasoning,
        )
        verdict, response = self._client.complete_structured(request, TaggerVerdict)
        known = set(self._taxonomy.names())
        return TaggedFailure(
            issue_ref=failure.issue_ref,
            tasks=failure.tasks,
            details=failure.details,
            categories=[c for c in verdict.categories if c in known],
            reasoning=verdict.reasoning,
            cost_usd=response.original_cost_usd,
        )


class TagAgreement(BaseModel):
    category: str
    n: int
    human: int  # how often the person used it
    llm: int
    kappa: float | None


def tag_agreement(
    human: dict[str, set[str]], llm: dict[str, set[str]], categories: Sequence[str]
) -> tuple[list[TagAgreement], float, float]:
    """Per-category kappa on presence, plus exact-set agreement and mean Jaccard."""
    shared = sorted(set(human) & set(llm))
    rows = [
        TagAgreement(
            category=c,
            n=len(shared),
            human=sum(c in human[r] for r in shared),
            llm=sum(c in llm[r] for r in shared),
            kappa=cohen_kappa([c in human[r] for r in shared], [c in llm[r] for r in shared]),
        )
        for c in categories
    ]
    exact = sum(human[r] == llm[r] for r in shared) / len(shared) if shared else 0.0
    jaccard = (
        sum(len(human[r] & llm[r]) / max(len(human[r] | llm[r]), 1) for r in shared) / len(shared)
        if shared
        else 0.0
    )
    return rows, exact, jaccard


def write_failures(run_dir: Path, tagged: Sequence[TaggedFailure], taxonomy_version: int) -> None:
    write_parquet(
        run_dir / FAILURES_FILE,
        [
            {
                "issue_ref": t.issue_ref,
                "tasks": t.tasks,
                "details": json.dumps(t.details),
                "categories": t.categories,
                "reasoning": t.reasoning,
                "taxonomy_version": taxonomy_version,
                "tagger_prompt_version": TAGGER_PROMPT_VERSION,
            }
            for t in tagged
        ],
    )


def category_counts(run_dir: Path) -> Counter[str] | None:
    path = run_dir / FAILURES_FILE
    if not path.exists():
        return None
    return Counter(c for row in read_parquet(path) for c in row["categories"])
