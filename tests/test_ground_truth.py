"""Hand-built cases for every ground-truth rule (AGENTS.md: rules live in code *and* tests)."""

from datetime import timedelta
from pathlib import Path

from triagelab.data.ground_truth import (
    component_of,
    derive,
    fix_prs,
    human_triaged,
    t1_labels,
    t2_duplicate,
    t3_component,
    t4_needs_info,
)
from triagelab.data.models import (
    Actor,
    Comment,
    DuplicateMark,
    IssueRef,
    LabelEvent,
    PRFiles,
    RawIssue,
)
from triagelab.data.profile import load_profile

from .data_fixtures import raw

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE = load_profile(REPO_ROOT / "configs" / "repos" / "python__cpython.yaml")
TRIAGER = Actor(login="triager", is_bot=False)
BOT = Actor(login="bedevere-app", is_bot=True)


def _files(*paths: str, number: int = 1002) -> dict[int, PRFiles]:
    return {
        number: PRFiles(repo="python/cpython", number=number, files=paths, files_total=len(paths))
    }


# ---- fixing PRs --------------------------------------------------------------------------


def test_fix_prs_keeps_the_main_branch_fix_and_drops_its_backport() -> None:
    assert fix_prs(raw(), PROFILE) == [1002]


def test_fix_prs_ignores_unmerged_and_unrelated_prs() -> None:
    issue = raw()
    unmerged = issue.model_copy(
        update={
            "linked_prs": tuple(p.model_copy(update={"merged": False}) for p in issue.linked_prs)
        }
    )
    assert fix_prs(unmerged, PROFILE) == []
    other = issue.model_copy(update={"number": 999})  # titles say gh-1000, not gh-999
    assert fix_prs(other, PROFILE) == []


# ---- T1 labels -----------------------------------------------------------------------------


def test_t1_keeps_taxonomy_labels_with_provenance_and_drops_versions() -> None:
    labels = {(lt.name, lt.group, lt.source) for lt in t1_labels(raw(), PROFILE)}
    # Fixture: type-bug from the issue form (author), stdlib from a triager, 3.15 from a bot.
    assert labels == {("type-bug", "type", "author"), ("stdlib", "area", "triager")}


def test_t1_topic_family_and_unknown_source() -> None:
    issue = raw().model_copy(update={"labels_current": ("topic-asyncio",)})
    assert t1_labels(issue, PROFILE)[0].model_dump() == {
        "name": "topic-asyncio",
        "group": "family",
        "source": "unknown",  # no event recorded for it
    }


def test_human_triaged_requires_a_non_author_human() -> None:
    issue = raw()
    assert human_triaged(issue, PROFILE)  # the triager added "stdlib"
    only_author_and_bot = issue.model_copy(
        update={"label_events": tuple(e for e in issue.label_events if e.actor.login != "triager")}
    )
    assert not human_triaged(only_author_and_bot, PROFILE)


# ---- T2 duplicates -------------------------------------------------------------------------


def _dup_issue(**update: object) -> RawIssue:
    return raw().model_copy(update=update)


def test_t2_prefers_the_state_reason() -> None:
    issue = _dup_issue(
        state_reason="DUPLICATE", duplicate_of=IssueRef(number=900, created_at=raw().created_at)
    )
    assert t2_duplicate(issue) == (900, "state_reason")


def test_t2_rejects_an_original_newer_than_the_issue() -> None:
    issue = _dup_issue(
        state_reason="DUPLICATE", duplicate_of=IssueRef(number=5000, created_at=raw().created_at)
    )
    assert t2_duplicate(issue) == (None, None)


def test_t2_uses_the_latest_active_mark_and_respects_unmarking() -> None:
    at = raw().created_at
    marks = (
        DuplicateMark(
            at=at + timedelta(hours=1),
            canonical=800,
            canonical_created_at=None,
            unmarked=False,
            actor=TRIAGER,
        ),
        DuplicateMark(
            at=at + timedelta(hours=2),
            canonical=800,
            canonical_created_at=None,
            unmarked=True,
            actor=TRIAGER,
        ),
        DuplicateMark(
            at=at + timedelta(hours=3),
            canonical=850,
            canonical_created_at=None,
            unmarked=False,
            actor=TRIAGER,
        ),
    )
    assert t2_duplicate(_dup_issue(duplicate_marks=marks)) == (850, "marked")
    assert t2_duplicate(_dup_issue(duplicate_marks=marks[:2])) == (None, None)


def test_t2_comment_counts_only_from_triage_roles() -> None:
    at = raw().created_at + timedelta(hours=1)
    stranger = Comment(
        at=at,
        author=Actor(login="x", is_bot=False),
        author_association="NONE",
        body="Duplicate of #700",
    )
    member = stranger.model_copy(update={"author_association": "MEMBER"})
    assert t2_duplicate(_dup_issue(comments=(stranger,))) == (None, None)
    assert t2_duplicate(_dup_issue(comments=(member,))) == (700, "comment")


# ---- T3 component --------------------------------------------------------------------------


def test_component_map_most_specific_prefix_and_ignores() -> None:
    assert component_of("Lib/test/test_foo.py", PROFILE) == ("tests", "supporting")
    assert component_of("Lib/foo.py", PROFILE) == ("stdlib", "primary")
    assert component_of("Objects/listobject.c", PROFILE) == ("interpreter-core", "primary")
    assert component_of("Misc/NEWS.d/next/Library/x.rst", PROFILE) is None
    assert component_of("README.rst", PROFILE) is None


def test_t3_fix_plus_test_is_the_fix_component() -> None:
    comp, votes, prs = t3_component(
        raw(), _files("Lib/foo.py", "Lib/test/test_foo.py", "Misc/NEWS.d/x.rst"), PROFILE
    )
    assert comp == "stdlib"
    assert votes == {"stdlib": 1, "tests": 1}
    assert prs == (1002,)


def test_t3_tests_only_fix_is_tests() -> None:
    comp, _, _ = t3_component(raw(), _files("Lib/test/test_a.py", "Lib/test/test_b.py"), PROFILE)
    assert comp == "tests"


def test_t3_tie_between_primaries_is_skipped() -> None:
    comp, votes, _ = t3_component(raw(), _files("Lib/foo.py", "Modules/_foo.c"), PROFILE)
    assert comp is None
    assert votes == {"stdlib": 1, "extension-modules": 1}


def test_t3_without_fetched_files_is_unknown() -> None:
    assert t3_component(raw(), {}, PROFILE)[0] is None


# ---- T4 needs-info ------------------------------------------------------------------------


def test_t4_counts_a_human_pending_label_even_if_removed_later() -> None:
    at = raw().created_at + timedelta(days=1)
    events = (
        LabelEvent(at=at, label="pending", added=True, actor=TRIAGER),
        LabelEvent(at=at + timedelta(days=2), label="pending", added=False, actor=TRIAGER),
    )
    assert t4_needs_info(raw().model_copy(update={"label_events": events}), PROFILE) == (True, at)


def test_t4_ignores_bot_applied_pending() -> None:
    at = raw().created_at + timedelta(days=1)
    events = (LabelEvent(at=at, label="pending", added=True, actor=BOT),)
    assert t4_needs_info(raw().model_copy(update={"label_events": events}), PROFILE) == (
        False,
        None,
    )


def test_derive_combines_all_tasks() -> None:
    truth = derive(raw(), _files("Lib/foo.py", "Lib/test/test_foo.py"), PROFILE)
    assert truth.component == "stdlib"
    assert truth.duplicate_of is None
    assert not truth.needs_info
    assert truth.human_triaged
