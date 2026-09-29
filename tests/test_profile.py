from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from triagelab.data.profile import Windows, load_profile

REPO_ROOT = Path(__file__).resolve().parents[1]
CPYTHON = REPO_ROOT / "configs" / "repos" / "python__cpython.yaml"


def test_cpython_profile_loads() -> None:
    profile = load_profile(CPYTHON)
    assert profile.repo == "python/cpython"
    assert profile.slug == "python__cpython"
    assert profile.windows.eval_start == date(2026, 5, 19)


def test_taxonomy_keeps_type_area_and_prefixed_families_only() -> None:
    tax = load_profile(CPYTHON).taxonomy
    assert tax.contains("type-bug")
    assert tax.contains("stdlib")
    assert tax.contains("topic-asyncio")
    assert tax.contains("OS-windows")
    for process_label in ("pending", "triaged", "3.14", "needs backport to 3.14", "stale"):
        assert not tax.contains(process_label)


def test_linked_pr_pattern_matches_main_and_backport_titles_only_for_that_issue() -> None:
    rx = load_profile(CPYTHON).linked_pr_regex(150599)
    assert rx.match("gh-150599: Prevent bz2 decompressor reuse")
    assert rx.match("[3.13] gh-150599: Prevent bz2 decompressor reuse (GH-150600)")
    assert not rx.match("gh-1505991: a different issue")
    assert not rx.match("Fix typo mentioning gh-150599")


def test_windows_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="history_start < eval_start"):
        Windows(
            history_start=date(2026, 1, 1),
            eval_start=date(2026, 5, 19),
            test_start=date(2026, 5, 1),
            eval_end=date(2026, 8, 18),
        )
