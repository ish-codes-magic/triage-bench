from pathlib import Path

from triagelab.data.ground_truth import fix_prs
from triagelab.data.profile import load_profile

from .data_fixtures import raw

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE = load_profile(REPO_ROOT / "configs" / "repos" / "python__cpython.yaml")


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
