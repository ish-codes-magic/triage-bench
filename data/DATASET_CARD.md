# Dataset card: triagelab / python/cpython

*Generated statistics:* [`reports/data/python__cpython.md`](../reports/data/python__cpython.md). *Rules as code:* `src/triagelab/data/` and `configs/repos/python__cpython.yaml`. *Decisions:* ADR-0011 to ADR-0014.

## Summary

GitHub issues from [python/cpython](https://github.com/python/cpython), each reconstructed **as it existed when opened**, with derived ("silver") labels for four triage tasks:
- **T1:** labels
- **T2:** duplicate detection
- **T3:** component routing
- **T4:** needs-info

Collected on 2026-09-29 through the GitHub GraphQL API.

<!-- KEY-NUMBERS:START -->
| | |
|---|---|
| Issues collected | 5,476 (2025-05-19 → 2026-08-18); 0 missing, 0 excluded |
| Splits | train 4,152 · dev 100 · test 50 · dev_reserve 752 · test_reserve 422 |
| Bodies edited after creation | 5,185 (94.7%), all rebuilt from edit history (creation revision matched to the second) |
| Current bodies naming the fix (bot "Linked PRs") | 3,852 (70%). In snapshots: **0** |
| Natural positive rates (dev+test pool, n = 1,324) | duplicate 2.6% · needs-info 8.6% · component 45.9% |
| Sampled rates (dev / test) | duplicate 13% / 12% · needs-info 15% / 22% · component 54% / 46% |
| Human-triaged | train 71.8% · dev 71.0% · test 60.0% (newest issues are less triaged) |
| Fixing PRs with files | 3,550; component ties skipped: 80 |
| Dataset hash (build of 2026-09-29) | `23ee2ef6f25bf3cd…` (full hash in the report JSON) |
<!-- KEY-NUMBERS:END -->

## Time windows and splits

| Split | Issues created | How chosen |
|---|---|---|
| train | 2025-05-19 → 2026-05-18 | all eligible issues (classifier baseline, retrieval history) |
| dev | 2026-05-19 → 2026-07-18 | stratified sample of 100 |
| test | 2026-07-19 → 2026-08-18 | stratified sample of 50 (evaluated at most twice, M8/M9) |
| dev_reserve / test_reserve | same windows | unsampled issues; `test_reserve` is never used for tuning |
| excluded | any | bot-authored, or creation-time text unrecoverable |

- **Why dev/test start on 2026-05-19:** that's after the training cutoff of every evaluated model. GPT-6 Luna states 2026-05-18, and Qwen3.5 (no stated cutoff) was released earlier. The training split may predate cutoffs, since those issues are legitimately "the past" for every eval issue (approved by the owner, 2026-09-29).
- **Why the test window ends 6 weeks before collection:** so labels, duplicate closures and fixing PRs have time to settle.
- **Sampling:** each window first meets per-task positive minimums, then fills uniformly (seed 20260929). Every sampled issue stores a post-stratification weight `N_h / n_h`. Report both stratified metrics and weighted (natural-rate) estimates.

## What the model sees (leakage policy)

The agent input is exactly: `issue_ref`, `repo`, `number`, `title`, `body`, `author_association`, `created_at`.
- **Title:** the title before any rename (`RenamedTitleEvent.previousTitle`).
- **Body:** the oldest revision in the edit history, which must be timestamped at creation.
  - Almost all CPython bodies are edited later, typically by a bot appending the fixing PRs. The current body is never used.
  - If an edited issue's original text can't be proven, the issue is **excluded**.
- **Never included:** comments, labels, events, state, linked PRs, or anything else after creation.
- **Enforcement:** `tests/test_leakage.py`, which runs as its own CI check ("Leakage guard").

## Ground-truth rules (silver)

| Task | Rule | Evidence kept |
|---|---|---|
| **T1 labels** | Taxonomy labels present at collection: *type* (`type-bug/crash/feature/refactor/security`), *area* (`stdlib`, `extension-modules`, `interpreter-core`, `docs`, `tests`, `build`, `infra`, `performance`), and the `topic-*` / `OS-*` families. Status, process and version labels are dropped. | Who applied each label: `author` (issue form or self-labelled), `triager`, `bot`, `unknown`; plus `human_triaged` |
| **T2 duplicates** | Evidence in this order: (1) closed with state reason *duplicate*; (2) otherwise, the latest still-active "marked as duplicate" event; (3) otherwise, a "Duplicate of #N" comment by an owner/member/collaborator. The original must have a smaller issue number, i.e. it was created earlier. | `duplicate_source` |
| **T3 component** | The fixing PRs are merged into `main` and either GitHub-linked or titled `gh-<issue>:`; backports are excluded. Changed files are mapped with the maintainers' own area-label descriptions (e.g. `Modules/` → extension-modules; `Objects/ Python/ Grammar/ Parser/ Include/` → interpreter-core). The majority over primary components wins. `tests` and `docs` only decide when nothing else changed. Ties are skipped. `Misc/NEWS.d` is ignored. | votes per component, fix PR numbers |
| **T4 needs-info** | A human applied `pending` ("will be closed if no feedback is provided") at any point, even if it was later removed. | first time applied |

**Silver vs. gold:**
- The owner hand-labels all 100 dev and 50 test issues ("gold", M5).
- Silver–gold agreement (Cohen's κ per task) is itself reported.
- Headline numbers use gold.

## Known limitations

- **`author_association`** is as of collection, not creation. A reporter may have become a contributor since, and the API keeps no history.
- **Untriaged issues:** issues nobody triaged have no T1 labels because nobody got to them, not because none apply. T1 silver metrics should be read on `human_triaged` issues.
- **Truncation:** timelines are fetched up to 100 events, and comments up to 40. The truncation counts are in the report.
- **T3 coverage:** only issues with a merged fix have a component. Issues closed without code changes (questions, invalid reports) have none.
- **Search:** issue enumeration goes through GitHub search, which can omit hidden or spam-filtered issues.
- **Duplicates are rare,** so duplicate metrics at n = 50 have wide confidence intervals.

## Provenance, licensing and privacy

- **Content:** public GitHub content, © its authors, used for research evaluation under GitHub's Terms of Service.
- **Not redistributed:** raw data lives in the gitignored `data/` directory; only this card and the aggregate report are committed.
- **Logins:** public GitHub usernames are stored, because label provenance needs them. No private data is collected.
- **Reproducible:** `triagelab data collect` then `triagelab data build`. Results can drift slightly as GitHub content changes. The dataset hash recorded with every run identifies the exact build.
