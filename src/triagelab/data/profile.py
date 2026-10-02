"""Repo profile: every repo-specific rule used to derive ground truth.

It lives in `configs/repos/<owner>__<repo>.yaml`, deliberately *separate* from the
triage skills. Skills are an experimental variable (E2 ablates them), so the ground
truth must not depend on anything a skill says.
"""

import re
from datetime import date
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Windows(_Strict):
    """Issue creation-date windows (inclusive dates, UTC)."""

    history_start: date = Field(description="Oldest issue collected (train + retrieval history).")
    index_start: date | None = Field(
        default=None,
        description="Optional older start for retrieval-only history (never in any split).",
    )
    eval_start: date = Field(description="First dev/test issue: after every model's cutoff.")
    test_start: date = Field(description="Dev is [eval_start, test_start); test is the rest.")
    eval_end: date = Field(description="Last dev/test issue: leaves time for labels to settle.")

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.index_start is not None and not self.index_start < self.history_start:
            raise ValueError("windows must satisfy index_start < history_start")
        if not self.history_start < self.eval_start < self.test_start <= self.eval_end:
            raise ValueError(
                "windows must satisfy history_start < eval_start < test_start <= eval_end"
            )
        return self


class Minimums(_Strict):
    duplicate: int = Field(ge=0)
    needs_info: int = Field(ge=0)
    component: int = Field(ge=0)


class SplitSpec(_Strict):
    dev_size: int = Field(gt=0)
    test_size: int = Field(gt=0)
    dev_min_positives: Minimums
    test_min_positives: Minimums
    seed: int


class Taxonomy(_Strict):
    """Labels that count for T1. Everything else (status, process, versions) is dropped."""

    type: tuple[str, ...]
    area: tuple[str, ...]
    prefixes: tuple[str, ...] = Field(description="Label families kept by prefix, e.g. 'topic-'.")

    def contains(self, label: str) -> bool:
        return label in self.type or label in self.area or label.startswith(self.prefixes)


class PromptWording(_Strict):
    """How this repository's labels are described to a model.

    The shared prompts used to say "area labels have no prefix" and "Topic and OS labels":
    true for CPython, wrong for a repository whose area labels are `area:...` (ADR-0047).
    The defaults are neutral; each profile states its own wording.
    """

    # Continues "Copy them exactly as written", e.g. '; "area:" is part of the name'.
    label_note: str = ""
    area_heading: str = "Other labels"  # heads `taxonomy.area`
    family_heading: str = "Area labels"  # heads the prefixed families
    # The single-shot baseline's one-line description of what to pick.
    single_shot_labels: str = "normally one type label, plus other labels that clearly apply"


class Component(_Strict):
    name: str
    prefixes: tuple[str, ...]
    # Supporting components (tests, docs) only decide the vote when a PR touches no primary
    # component: nearly every fix ships a test, which would otherwise tie with the fix.
    role: Literal["primary", "supporting"] = "primary"


class RepoProfile(_Strict):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    windows: Windows
    splits: SplitSpec
    taxonomy: Taxonomy
    needs_info_labels: tuple[str, ...]
    main_branch: str
    linked_pr_title_pattern: str = Field(
        description="Regex with a {number} placeholder, matched against linked PR titles."
    )
    components: tuple[Component, ...]
    ignore_paths: tuple[str, ...] = ()
    wording: PromptWording = PromptWording()

    @property
    def slug(self) -> str:
        """Filesystem-safe name: 'python/cpython' -> 'python__cpython'."""
        return self.repo.replace("/", "__")

    def linked_pr_regex(self, number: int) -> re.Pattern[str]:
        return re.compile(self.linked_pr_title_pattern.replace("{number}", str(number)))

    def component_of(self, path: str) -> Component | None:
        """The component owning a repository path (first matching prefix), if any."""
        if path.startswith(self.ignore_paths):
            return None
        return next((c for c in self.components if path.startswith(c.prefixes)), None)


def load_profile(path: Path) -> RepoProfile:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return RepoProfile.model_validate(raw)
