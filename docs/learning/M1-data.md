# M1: Data

**What M1 built:** the dataset every later result stands on:
- CPython issues collected with their full history;
- each reconstructed exactly as it looked when opened;
- silver ground truth for all four tasks, each label with its evidence;
- time-based splits with stratified, weighted dev/test samples;
- a generated statistics report.

**Why it matters:** an eval is only as good as its labels and its leakage discipline. Most "LLM triage" demos quietly feed the model today's issue text, which often already names the fix.

```
triagelab data collect -p configs/repos/python__cpython.yaml
  search (date-sliced, <1,000 results per slice) → issue numbers
  GraphQL batches (25/query, halved on 502) → data/raw/python__cpython/issues.jsonl   (resumable)
  fixing PRs (merged into main, gh-<issue>: titles) → pr_files.jsonl
triagelab data build -p configs/repos/python__cpython.yaml
  RawIssue ──to_snapshot──► IssueSnapshot (7 creation-time fields)   → data/snapshots/*.parquet
          ──derive───────► SilverTruth (T1–T4 + provenance)        → data/silver/*.parquet
          ──assign_splits► train | dev | test | *_reserve | excluded → data/splits/*.parquet
          ──compute_stats► reports/data/python__cpython.md (+ .json, dataset hash)
```

**Result (2026-09-29):**
- **Collected:** 5,476 CPython issues for 357 GraphQL points (0 missing).
- **Reconstructed:** 94.7% of bodies were edited after creation, and all were rebuilt from edit history.
- **Leakage check on real data:** **70% of current bodies name the fixing PRs** (the bot's "Linked PRs" section); **0 snapshots do**.
- **Splits:** dev 100 and test 50, meeting every positive minimum.
- **Weights check out:** weighted rates track the natural pool (e.g. duplicates 2.6% natural, 13% sampled, 3.1% weighted on dev).
- **Report:** [reports/data/python__cpython.md](../../reports/data/python__cpython.md).

---

## 1. Concepts, and where they live

| Concept | What to take away | Code |
|---|---|---|
| **Label provenance** | "Labelled" isn't the same as "triaged". Issue forms auto-apply labels the *author* chose. Measure who applied each label before trusting it. | `data/ground_truth.py`: `_source`, `human_triaged` |
| **Creation-time reconstruction** | The API returns *current* text. Rebuild the title from renames and the body from the oldest edit revision. Refuse, don't guess, when it can't be proven. | `data/snapshot.py`: `title_at_creation`, `body_at_creation`, `to_snapshot` |
| **The leakage contract** | One type (`IssueSnapshot`) is the agent's whole world. Its field set is pinned by a test, and every other field is proven irrelevant by a mutation test. | `data/models.py`: `IssueSnapshot`; `tests/test_leakage.py` |
| **As-of views** | To show a *past* issue to someone at time t, replay events strictly before t, and never show a later body revision. | `data/snapshot.py`: `view_as_of` |
| **Rules as config, not code** | Taxonomy, component map and link conventions are per-repo YAML, kept separate from skills so ground truth never depends on an ablation variable. | `data/profile.py`; `configs/repos/python__cpython.yaml` |
| **Voting with roles** | Component = majority over fix files, but tests and docs only vote when nothing else changed, because nearly every fix ships a test. | `data/ground_truth.py`: `t3_component` |
| **Stratified sampling + weights** | Oversample rare positives, store `N_h/n_h`, and report both views. Uniform selection *within* strata is what makes the weights valid. | `data/splits.py`: `stratified_sample`, `stratum_weights` |
| **Resumable, adaptive collection** | Append-only JSONL, date-sliced search under a result cap, and batches halved on server-side 502s. | `data/collect.py`, `data/github.py` |
| **Parse at the boundary** | Nullable, nested GraphQL JSON becomes complete typed records exactly once. | `data/parse.py` |

## 2. What we verified before coding (§14, GitHub API; checked live on 2026-09-29)

- **Duplicates:**
  - `Issue.stateReason == DUPLICATE` and `Issue.duplicateOf { number createdAt }` exist.
  - `ClosedEvent.duplicateOf` too.
  - `MarkedAsDuplicateEvent.canonical` names the original.
  - REST's `marked_as_duplicate` does *not*.
- **Body history:**
  - ⚠️ `userContentEdits` returns each revision's **full text** in a field called `diff`, newest first.
  - `userContentEdits(last: 1)` is the creation revision; its `editedAt` equals the issue's `createdAt`.
- **Title history:** `RenamedTitleEvent { previousTitle currentTitle }`.
- **Fixing PRs:**
  - ⚠️ On CPython, `closedByPullRequestsReferences` is usually **empty**; PRs link by title (`gh-154672: …`), visible as `CrossReferencedEvent.source`.
  - Backports use `[3.x] gh-N:` and target release branches.
- **Cost:** ⚠️ a 40-issue batch with timelines, comments and edits costs **1–2 points** (of 5,000/hour), so latency, not budget, is the bottleneck.
- **Timeouts:** ⚠️ expensive queries (e.g. per-label `issues { totalCount }` on CPython) come back as an **HTML 502**, not JSON. Hence the batch-halving.
- **Search:** GitHub search caps results at 1,000 per query, hence the date slicing. The `-no:label` qualifier did not behave as a negation in our scan, which caused an early misreading.

## 3. Pitfalls (most of these happened during M1)

1. **Trusting label counts.** Every candidate repo showed 100% labelled issues, and for transformers almost all of those were author-chosen template labels. Choose a repo by *who* applied labels (ADR-0011).
2. **Current text leaks.** On CPython, 95% of bodies were edited after creation, mostly by a bot appending the fixing PRs. A snapshot built from `body` would hand the model the answer.
3. **`author_association` is current, not historical.** A first-time reporter may be a contributor today. There's no API for history, so it's documented as a limitation.
4. **Every fix ships a test.** A naive majority vote over changed files ties "stdlib" against "tests" on almost every issue. Hence primary/supporting roles.
5. **Backports vote twice.** One fix, 3–4 merged PRs. Only PRs into `main` count.
6. **Windows has no timezone database.** PyArrow reading UTC timestamps needs `tzdata` on Windows; the Windows CI leg exists for this.
7. **Upgrading a package while it runs.** Editing `pyproject.toml` makes `uv run` reinstall, and Windows won't replace a running `.exe`. Use `UV_NO_SYNC=1` during long jobs.

## 4. How an interviewer might probe this

- *"How do you know your eval isn't leaking?"* → A single input type with a pinned field set; a mutation test over every other field; creation-time reconstruction from edit history; and it all runs as its own CI check.
- *"Your ground truth is derived from GitHub. How noisy is it?"* → Every label carries provenance. We measure silver vs. gold agreement (Cohen's κ) on hand-labelled dev/test (M5) and report it as a finding.
- *"Why not just sample dev/test uniformly?"* → 50 issues at a 3% duplicate rate is about one positive, so metrics would be meaningless. Stratify, store the weights, and report both natural and stratified views.
- *"Why split by time instead of randomly?"* → Triage happens forward in time. A random split lets the model (and the retrieval index) learn from the future.

## 5. Try it yourself (optional exercises)

1. In `data/splits.py`, write `natural_rate_ci(...)`: a bootstrap CI for the weighted duplicate rate. (This previews M2's bootstrap.)
2. Add a `needs-mre`-style second needs-info label to a copy of the profile, and write the test first.
3. Using `view_as_of`, print the labels of a real issue one hour, one day and one week after creation. What changes?

## 6. Self-check questions

1. Why is `original < issue.number` a valid "created earlier" check for duplicates?
2. What exactly would leak if snapshots used `RawIssue.body` for an edited CPython issue?
3. Why do weights `N_h / n_h` recover the natural rate, and what assumption makes that true?
4. An issue's fix touches `Lib/foo.py`, `Lib/test/test_foo.py` and `Doc/library/foo.rst`. What's its component, and why?
5. Why is the repo profile deliberately *not* stored inside the triage skill?

<details><summary>Answers</summary>

1. Issues and PRs share one counter that only increases as items are created, so a smaller number was created earlier. It also rules out "duplicates" pointing forward in time.
2. The bot-appended "Linked PRs" section (the fixing PR numbers) and any reporter edits made after triage began ("EDIT: duplicate of #…", "fixed in …"). That's information from after creation, and sometimes the literal answer.
3. Within a stratum, every issue is equally likely to be picked, so the sampled issues represent their stratum. Scaling each stratum back to its pool size (`N_h / n_h`) reconstructs population totals. The assumption is uniform selection *within* strata, which holds because the sampler draws from sorted-then-shuffled candidate lists.
4. `stdlib`. `Lib/foo.py` is a primary component, and tests and docs are supporting roles that only decide when nothing primary changed.
5. Skills are an experimental variable (E2 ablates them, and M6 iterates on them). If ground truth depended on the skill, changing the skill would change the answer key and inflate its measured effect.

</details>
