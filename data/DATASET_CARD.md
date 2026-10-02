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

**Silver vs. gold (M5):**
- **Who labeled.** At the owner's request, the "gold" labels were produced by a **model annotator** (Claude Opus 5.5, `annotator: claude-opus-5-5`), not a person (ADR-0035).
- **How.** Each issue got two passes: blind from the creation-time text, then adjudicated with the evidence (labels and who applied them, the fixing PRs' files, the duplicate closure).
- **Coverage so far.** 100 dev issues; 3 were marked unusable (spam or non-issues). The 50 test issues will be labeled at M8, after all development decisions are frozen.
- **Label noise, silver vs. gold on dev** (`reports/gold/dev.md`):

  | task | Cohen's κ | agreement |
  |---|---|---|
  | T1 type label | 0.72 | 81% |
  | T1 all labels, pooled per label | 0.84 | 98% |
  | T2 is-a-duplicate | 1.00 | 100% |
  | T3 component | 0.90 | 93% |
  | T4 needs-info | 0.00 | 85% |

- **T4 doesn't survive adjudication.** Silver marks 15 of the 97 usable dev issues as needing information, because a human applied `pending`. The adjudicated gold marks **none**: the annotator judged every one of those reports already actionable, with `pending` meaning "awaiting a maintainer decision" or "closing unless someone objects". Silver T4 metrics should be read as "predicts `pending`", not "detects missing information".
- **Systematic silver errors the annotator reported:**
  - demonstrated segfaults and aborts labeled `type-bug`;
  - `extension-modules` applied to fixes in pure-Python `Lib/` code;
  - derived components pulled toward side files (`configure`, generated headers, docstring-only edits).
- Headline numbers use the adjudicated labels (`--labels gold`), with this provenance stated.

## Known limitations

- **`author_association`** is as of collection, not creation. A reporter may have become a contributor since, and the API keeps no history.
- **Untriaged issues:** issues nobody triaged have no T1 labels because nobody got to them, not because none apply. T1 silver metrics should be read on `human_triaged` issues.
- **Truncation:** timelines are fetched up to 100 events, and comments up to 40. The truncation counts are in the report.
- **T3 coverage:** only issues with a merged fix have a component. Issues closed without code changes (questions, invalid reports) have none.
- **Search:** issue enumeration goes through GitHub search, which can omit hidden or spam-filtered issues.
- **Duplicates are rare,** so duplicate metrics at n = 50 have wide confidence intervals.
- **Retrieval index history:** the search index also holds 6,413 older issues (2024-01-01 → 2025-05-18, `index_history.jsonl`).
  - They're **not** part of any split. They're there because half of all duplicate originals predate the dataset window.
  - Originals from before 2024 (about 50 of 202 duplicates) remain unfindable.
- **Code search** runs on a source tree frozen at the last `main` commit before the dev window (`398d7e1`, 2026-05-18).
  - An August issue therefore sees May's code.
  - Train-window issues see code from after they were filed, but they're never evaluated.

## Provenance, licensing and privacy

- **Content:** public GitHub content, © its authors, used for research evaluation under GitHub's Terms of Service.
- **Redistribution:** raw data lives in the gitignored `data/` directory. Two kinds of derived pack are published as GitHub release assets, so that CI can run evaluations (ADR-0040, ADR-0046):
  - the **eval pack** (`evalpack-v1`): creation-time snapshots, silver labels and the retrieval history for the train and dev periods only. It holds nothing from the test period.
  - the **test packs**: everything, published only once a test session is frozen.

  Issue texts remain © their authors.
- **Logins:** public GitHub usernames are stored, because label provenance needs them. No private data is collected.
- **Reproducible:** `triagelab data collect` then `triagelab data build`. Results can drift slightly as GitHub content changes. The dataset hash recorded with every run identifies the exact build.

## Transfer dataset: astral-sh/uv (E8)

Built with the same pipeline and the same time windows, from `configs/repos/astral-sh__uv.yaml`. Aggregate report: `reports/data/astral-sh__uv.md`. 2,826 issues were collected (2,543 train, 100 dev, 50 test), plus 6,064 retrieval-only issues back to February 2024.

- **How the profile was written:** from the repository's label list and its directory layout at the freeze commit (`c22efa1`, 2026-05-18). No issue from the evaluation window was read.
- **The dev split is never evaluated or tuned on.** Transfer means swapping the profile and the skill only.
- **Label provenance is the main caveat (ADR-0045):**
  - uv's issue forms attach `bug`, `enhancement` or `question` at creation. On eval-window issues, 188 of 261 taxonomy labels were applied by the author and 72 by a maintainer.
  - A maintainer triaged 26–32% of issues (CPython: 70%).
  - Silver type labels therefore partly measure "which form did the author choose". Maintainers do correct them: on train, 277 form-filed issues were relabelled `question`.
  - Headline transfer results use the adjudicated test labels. Type labels are also reported on the maintainer-triaged subset.
- **Area labels (`area:*`) are sparse.** Only four have 10 or more training examples and enter the vocabulary: `area:error-messages`, `area:windows`, `area:build-backend`, `area:configuration`.
- **Duplicates:** GitHub's structured duplicate closures (85 in the collected window).
- **Components:** 11 groups of crates. About 20% of issues have a linked fixing PR; 33 fixes that spanned groups equally were skipped as ties.
- **Needs-info:** the `needs-mre` label ("Needs more information for reproduction"), on about 5% of issues. Unlike CPython's `pending`, it means what its name says, so uv gives a valid T4.

## Test-split labels (M8)

The 50 test issues of each repository were adjudicated by the same model annotator and process as dev (blind pass from the issue text, then a final pass with the evidence), **after** the test session was frozen and before any system was scored on them. Files: `data/gold/python__cpython.jsonl` and `data/gold/astral-sh__uv.jsonl`; agreement reports: `reports/gold/test.md` and `reports/gold/uv/test.md`.

| | python/cpython | astral-sh/uv |
|---|---|---|
| usable issues | 50 | 50 |
| final answer differs from the blind one | 6 | 11 |
| type labels | bug 32, feature 10, crash 8 | bug 26, enhancement 16, question 8 |
| duplicates | 6 | 3 |
| needs info | 0 | 6 |
| no component | 2 | 9 |
| silver vs. gold, type label: Cohen's κ (n) | 0.79 (30) | 0.66 (16) |

- **The CPython test sample is easier than dev on the type label.** It has no refactor or security issues (dev: 7 of 97), and blind and final type labels agree on 49 of 50. Dev numbers and test numbers for the type label are not directly comparable.
- **On uv, what maintainers label is not a random sample.** Of the 16 test issues a maintainer triaged, 6 carry `question`; the 34 others mostly keep the reporter's own `bug`. Scores against silver and against gold therefore answer different questions (`reports/test-eval/RESULTS.md`, section 4).
- **Too few positives to interpret:** duplicates (6 and 3) and needs-info (0 and 6).
- **Redistribution:** the test packs (`testpack-python__cpython-v1`, `testpack-astral-sh__uv-v1`) contain the full dataset including the test period. They were published only after the freeze, to let the approval-protected workflow run (ADR-0046).
