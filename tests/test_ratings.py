"""Rubric validation and the stable judge-dev/judge-test split."""

from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from triagelab.labeling.ratings import Rubric, judge_split, load_rubric

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_the_committed_rubric_is_valid() -> None:
    rubric = load_rubric(REPO_ROOT / "configs" / "judge" / "rubric.yaml")
    assert rubric.scale == [1, 2, 3, 4]
    assert 3 <= len(rubric.criteria) <= 4  # AGENTS.md §12.4


def test_every_criterion_must_describe_every_level() -> None:
    with pytest.raises(ValidationError, match="every level"):
        Rubric.model_validate(
            {
                "version": 1,
                "scale": [1, 2, 3, 4],
                "criteria": [{"name": "c", "question": "q", "levels": {1: "a", 2: "b"}}],
            }
        )


def test_judge_split_is_stable_and_roughly_even() -> None:
    ids = [f"o/r#{n}:agent" for n in range(1000)]
    assert [judge_split(i) for i in ids] == [judge_split(i) for i in ids]
    counts = Counter(judge_split(i) for i in ids)
    assert 450 < counts["judge-dev"] < 550
