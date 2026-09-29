"""Silver ground truth: one documented, tested rule per task (AGENTS.md §7.3).

Every function here is pure: it reads a `RawIssue` (and the repo profile) and returns a
label plus *where the label came from*, so noise can be analysed later. The rules are
restated in plain words in data/DATASET_CARD.md.
"""

from triagelab.data.models import RawIssue
from triagelab.data.profile import RepoProfile


def fix_prs(issue: RawIssue, profile: RepoProfile) -> list[int]:
    """Merged PRs into the main branch that fixed this issue.

    A PR counts if GitHub links it as closing the issue, or (CPython's convention) its
    title starts with "gh-<issue>:". Backports target release branches, so requiring the
    main branch keeps one fix from voting several times.
    """
    title_rx = profile.linked_pr_regex(issue.number)
    return [
        pr.number
        for pr in issue.linked_prs
        if pr.merged
        and pr.base_ref == profile.main_branch
        and (pr.via == "closing_reference" or title_rx.match(pr.title))
    ]
