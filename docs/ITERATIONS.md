# Iteration log

Each iteration records one change, its metric delta with a paired-bootstrap 95% CI (dev, silver labels), and the change in failure categories. A change only counts as an improvement when its interval excludes zero (AGENTS.md §12.2). Tuning happens on **dev only**; the test split is locked (`--allow-test`, at most twice).

Reproduce any comparison with `triagelab compare <run_a> <run_b> [--exclude-errors]`.

---

## Iteration 1: the prompt's label list caused invented labels

- **Date:** 2026-09-29 · **System:** E1 single-shot LLM (Qwen3.5-9B @ deepinfra/bf16, thinking off) · **Commit:** `af4a19a`
- **Runs:** A = `20260929-100441-e1-llm-single-shot-8cfa51` (v1), B = `20260929-101229-e1-llm-single-shot-4e35d3` (v2)

**Observation.**
- v1 printed the vocabulary as `- area: stdlib, extension-modules, …`.
- The model answered **`area-stdlib`** on 57 of 100 dev issues (and `area-interpreter-core`, …). None of those are real labels, so all were rejected as out-of-taxonomy.
- Area-label F1 collapsed to 0.08, even though the model had usually picked the *right* area.

**Change.** List labels as exact strings to copy, and say so ("write `stdlib`, never `area-stdlib`").

**Result** (paired bootstrap, 95 issues where both runs produced an answer):

| metric | v1 | v2 | Δ [95% CI] | |
|---|---|---|---|---|
| T1 area micro-F1 | 0.083 | 0.559 | **+0.475 [+0.349, +0.591]** | significant |
| T1 micro-F1 | 0.467 | 0.554 | **+0.088 [+0.025, +0.153]** | significant |
| T1 type micro-F1 | 0.781 | 0.746 | −0.035 [−0.094, +0.027] | no evidence |
| T3 accuracy | 0.673 | 0.592 | −0.082 [−0.236, +0.076] | no evidence |
| T4 F1 | 0.122 | 0.286 | +0.163 [−0.003, +0.328] | no evidence (borderline) |

**Failure categories:**

| category | v1 | v2 |
|---|---|---|
| issues with invented labels | 84 | 31 |
| invented labels (`area-*` prefix) | 78 | 8 |
| infrastructure fallbacks (OpenRouter 429) | 5 | 0 |

**Caveats.**
- Both runs sampled at the provider's default temperature, so part of every delta is run-to-run model randomness, which the issue bootstrap does not capture. The T3 and T4 swings are within that noise.
- From here on, the Qwen route runs at temperature 0 (`b357fb2`), and M6 measures consistency explicitly (pass^k).
- The 5 v1 fallbacks were infrastructure failures that got scored as empty answers. That led to the runner's infra-retry pass (`b2471fd`) and to `--exclude-errors`.

**Takeaway.** Small models copy the *format* of a vocabulary as literally as its content. The cheapest fix in this whole project so far was a prompt-presentation bug, and it was only visible because out-of-taxonomy labels are recorded instead of silently dropped.

---

## Iteration 2: does thinking pay for a 9B model?

- **Date:** 2026-09-30 · **System:** E1 single-shot LLM (Qwen3.5-9B @ deepinfra/bf16), same prompt as iteration 1's v2, temperature 0
- **Runs:** A = `20260929-102356-e1-llm-single-shot-f80f1d` (reasoning `none`, max 1,500 output tokens), B = `20260929-134512-e1-llm-single-shot-thinking-075806` (reasoning `default`, max 8,000)
- **No prompt drift:** `git diff b357fb2 aeca21c` touches no baseline, metric or scoring code.

**Change.** Let the model reason before answering (OpenRouter `reasoning.effort` left at the provider default instead of `none`).

**Result** (paired bootstrap, all 100 issues, no errors in either run):

| metric | no thinking | thinking | Δ [95% CI] | |
|---|---|---|---|---|
| T1 micro-F1 | 0.585 | 0.686 | **+0.101 [+0.061, +0.136]** | significant |
| T1 macro-F1 | 0.468 | 0.622 | **+0.154 [+0.060, +0.221]** | significant |
| T1 area micro-F1 | 0.571 | 0.646 | **+0.075 [+0.012, +0.142]** | significant |
| T1 type micro-F1 | 0.788 | 0.832 | +0.044 [+0.000, +0.101] | no evidence (borderline) |
| T3 accuracy | 0.685 | 0.759 | +0.074 [−0.064, +0.218] | no evidence |
| T4 F1 | 0.195 | 0.200 | +0.005 [−0.178, +0.176] | no evidence |

**Against the TF-IDF classifier** (`20260929-100338-e1-classifier-aabfa4`):
- **T1 micro-F1:** −0.023 [−0.086, +0.046]. The significant gap from M2 (−0.124) is gone: there's now no evidence of a difference.
- **T1 macro-F1:** +0.117 [−0.025, +0.188]. The LLM does better on rare labels, though the interval still includes zero.
- **T3 accuracy:** +0.111 [+0.000, +0.240]. That's borderline, and not significant.

**Failure categories and cost:**

| | no thinking | thinking |
|---|---|---|
| issues with invented labels | 5 | 1 |
| mean output tokens per issue | 266 | 940 (3,574 of the last 4,629 were reasoning) |
| cost per issue | $0.00015 | $0.00026 (1.7×) |
| p50 latency | 16.7 s | 22.8 s |

**Caveats.**
- **Execution:** the laptop's memory reaper stopped the thinking run with 5 issues left, and the run was resumed a day later. The resumed issues are identical requests at temperature 0, so resuming doesn't bias the comparison.
- **Sample size:** macro-F1 moves on few examples of rare labels (n = 100).

**Takeaway.**
- **Reasoning is the cheapest lever so far for a small model:** +0.10 micro-F1 for about a hundredth of a cent per issue.
- **M4 default:** the agent runs with thinking on.
- **The bar for M4:** the plain classifier is still as good on labels, so the agent must beat 0.71 micro-F1 *and* justify ~25 s and $0.0003+ per issue with what tools add: duplicates (T2) and components (T3).

---

## Iteration 3: a required field restores top-3 (and helps top-1)

- **Date:** 2026-09-30 · **System:** agent (Qwen3.5-9B, thinking on, CPython skill, repo-intel over MCP)
- **Runs:** A = `20260929-193240-agent-b2e7e0` (M4 agent v1, prompt v1), B = `20260929-213632-agent-11599c` (prompt v2)

**Observation.**
- In v1, `component_top3` in the `submit_triage` schema had a default.
- The model omitted it on 77 of 100 issues, so the agent's "top-3" was really top-1.
- It scored significantly *below* both baselines on top-3 accuracy (−0.15 vs. TF-IDF).

**Change.** Make `component_top3` required, as in the single-shot schema. This is the only change: prompt version 2.

**Result** (paired bootstrap, 100 issues, no errors in either run):

| metric | v1 | v2 | Δ [95% CI] | |
|---|---|---|---|---|
| T3 top-3 accuracy | 0.796 | 0.944 | **+0.148 [+0.059, +0.250]** | significant |
| T3 accuracy | 0.722 | 0.796 | **+0.074 [+0.017, +0.151]** | significant |
| T1 micro-F1 | 0.717 | 0.743 | +0.026 [−0.017, +0.069] | no evidence |
| T2 link F1 | 0.435 | 0.316 | −0.119 [−0.344, +0.084] | no evidence (about 13 duplicates) |
| T4 F1 | 0.083 | 0.160 | +0.077 [−0.190, +0.340] | no evidence |

**Behaviour** (`runs stats`):

| | v1 | v2 |
|---|---|---|
| issues with 3 component candidates | 17 | 79 |
| skill load rate | 1% | 2% |
| answers forced by a budget | 53 | 55 |
| issues with a validation error | 0 | 2 |

**Caveats.**
- **Different requests:** every request differs (the schema is in every call's tool list), so some of each delta is the model's different path, even at temperature 0.
- **Provider overload:** DeepInfra's shared pool was overloaded for about 20 minutes during run B (`engine_overloaded`). 89 issues failed with 429s and were resumed after the agent's retry budget was raised (8 attempts, back-off up to 60 s). Resumed steps replay from the cache, so this didn't change any answer.

**Takeaway.**
- **Required fields beat optional ones:** a one-line schema fix turned the agent's worst metric (top-3) into its best (0.94, level with TF-IDF).
- **Top-1 improved too.** Asking for ranked alternatives seems to make the first choice more deliberate, a cheap form of self-consistency.

---

## Iteration 4: forcing the skill in doesn't help this model (negative result, reverted)

- **Date:** 2026-09-30 · **System:** agent, prompt v2
- **Runs:** A = `20260929-213632-agent-11599c` (iteration 3), B = `20260929-224959-agent-fcf838` (`skill_activation: first_call`)

**Observation.**
- Left to decide, the agent called `load_skill` on 1–2% of issues.
- So every result so far is effectively "no skill", and H1 (do repository skills help?) was untestable.

**Change.** The harness makes the first model call `tool_choice=load_skill`: the skill body always enters the context, and the model still chooses which reference files to read.

**Result** (paired bootstrap, 100 issues, no errors in either run):

| metric | A | B | Δ [95% CI] | |
|---|---|---|---|---|
| T1 micro-F1 | 0.743 | 0.709 | −0.035 [−0.079, +0.010] | no evidence |
| T1 type micro-F1 | 0.859 | 0.809 | −0.050 [−0.123, +0.014] | no evidence |
| T2 link F1 | 0.316 | 0.333 | +0.018 [−0.042, +0.079] | no evidence |
| T3 accuracy | 0.796 | 0.778 | −0.019 [−0.100, +0.070] | no evidence |
| T4 F1 | 0.160 | 0.000 | −0.160 [−0.364, +0.000] | no evidence (about 15 positives) |

**Behaviour:**

| | A | B |
|---|---|---|
| skill load rate | 2% | 100% |
| reference files read (per issue) | 0.13 | 0.04 |
| `search_similar_issues` calls per issue | 4.0 | 5.0 |
| `search_code` calls per issue | 4.0 | 2.3 |
| tool calls per issue (all) | 9.2 | 9.0 |
| answers forced by the step budget | 55 | 63 |
| cost per issue | $0.0071 | $0.0065 |

**Reading.**
- **The skill was read, but its procedure wasn't followed.** It says "1–3 focused queries" and "most issues need 2–6 tool calls". Total tool use didn't fall (9.2 → 9.0): it moved from code search to issue search, and more answers had to be forced.
- **Reference files were opened *less* once the body was in context** (0.13 → 0.04 per issue). In A, the model sometimes read references directly without loading the skill.
- **Needs-info:** both runs flagged 10 of 100 issues, B on different and all-wrong ones. With about 15 positives, that's noise, not a mechanism.

**Decision.**
- **Reverted** from the reference agent: no measured benefit, and one extra step per issue.
- The mechanism stays. E2 (the skills ablation, M6) uses `first_call` for every skill variant, so it compares skill *content*, not whether the model happened to look.

**Takeaway.**
- **A negative result for H1 at this model size:** repository knowledge delivered as a skill, even force-fed, didn't improve a 9B model's triage.
- **Progressive disclosure assumes a model that decides to read, and then follows what it read.** Qwen3.5-9B did neither reliably. E5 (27B) will show whether that's a size effect.

---

## Iteration 5: a repeat guard makes the agent cheaper, not smarter

- **Date:** 2026-09-30 · **System:** agent, prompt v2 (iteration 3's configuration)
- **Runs:** A = `20260929-213632-agent-11599c` (iteration 3), B = `20260930-000255-agent-cf734a` (`repeat_guard: true`)

**Observation.**
- In M4's traces, 9% of tool calls exactly repeated an earlier call, and 39% were near-duplicate queries (same tool, ≥ 50% word overlap).
- 60 of 100 issues had three or more of them, and about half of all answers were forced by the step budget.

**Change.** The toolbox (`RepeatGuard`) now does three things:
- answers an exact repeat from history instead of running it;
- tags a near-duplicate query's result with "this query overlaps an earlier one; if it added nothing new, decide";
- ends every result with "tool calls used: k of 15".

**Result** (paired bootstrap, 100 issues; B has one genuine `no_answer` fallback, which is scored):

| metric | A | B | Δ [95% CI] | |
|---|---|---|---|---|
| T1 micro-F1 | 0.743 | 0.728 | −0.015 [−0.044, +0.015] | no evidence |
| T2 link F1 | 0.316 | 0.435 | +0.119 [−0.087, +0.342] | no evidence |
| T3 accuracy | 0.796 | 0.815 | +0.019 [−0.041, +0.088] | no evidence |
| T4 F1 | 0.160 | 0.083 | −0.077 [−0.250, +0.014] | no evidence |
| cost per issue | $0.00709 | $0.00645 | **−$0.00064 [−0.00124, −0.00007]** | significant (−9%) |
| input tokens per issue | 68.1k | 61.4k | **−6.7k [−12.6k, −1.0k]** | significant |
| tool calls per issue | 9.2 | 9.1 | −0.19 [−0.74, +0.34] | no evidence |

**Behaviour:**
- 64 of 917 tool calls (7%) were exact repeats answered from history.
- 270 (29%) got an overlap note.
- Forced answers: 55 → 48.

**Reading.**
- **The guard fired constantly, but the model kept rephrasing.** Tool-call counts didn't move.
- **The savings are real, and they come from not re-sending repeated results**, not from the agent deciding sooner.

**Decision.** Kept in the reference agent: the same accuracy for 9% less.

**Takeaway across iterations 3–5.**
- **What worked:**
  - a **schema** change (iteration 3: +0.15 top-3, +0.07 top-1 components);
  - a **mechanical** harness change (iteration 5: −9% cost).
- **What didn't:** *telling* the model how to behave, whether through a skill it was made to read (iteration 4) or through in-context notes (iteration 5's overlap notes). Qwen3.5-9B largely ignores process guidance.
- **Next** (M6/E5): does a larger model follow the same guidance?

---

## M6 iterations: the taxonomy chooses the target

From iteration 6 on, each iteration starts from the M5 failure taxonomy (`docs/FAILURE_TAXONOMY.md`):
- pick the biggest category;
- make one change aimed at it;
- report the headline delta on the **adjudicated (gold)** labels, with silver alongside;
- report the change in category counts from the LLM tagger.

The tables are regenerated by `triagelab deltas reports/experiments/m6-iterations.yaml` → [gold](../reports/experiments/m6-iterations-gold.md), [silver](../reports/experiments/m6-iterations-silver.md).

Infrastructure note: from 2026-09-30 21:00 UTC, the 9B runs use the owner's DeepInfra key (ADR-0041). The model, route and prices are unchanged; only the shared-pool 429s went away.

---

## Iteration 6: the tools name the component that owns each file (kept)

- **Date:** 2026-09-30 · **System:** reference agent, tools v1 → v2 · **Commits:** `96aae9a`, `bce0829`
- **Runs:** A = `20260930-000255-agent-cf734a` (iteration 5), B = `20260930-122125-agent-deb407`

**Observation.**
- **Code-location confusion** was the second-largest category (24 reference tags, 31 from the tagger). The agent found the right file, then mapped it to the wrong component, or labelled where the symptom showed instead of where the fix would go.
- Mapping a path to a component is a lookup, not a judgement, yet the model was doing it in its head from a list in the prompt.

**Change.**
- `search_code` hits and `get_codeowners` results now carry the `component` that owns the path. It's computed by `RepoProfile.component_of`, the same function the T3 ground truth uses (TOOLS_VERSION 2).
- No prompt change.

**Result** (paired bootstrap, 97 adjudicated issues):

| metric | A | B | Δ gold [95% CI] | Δ silver [95% CI] |
|---|---|---|---|---|
| T1 micro-F1 | 0.752 | 0.775 | +0.023 [−0.019, +0.062] | +0.015 [−0.024, +0.054] |
| T1 area micro-F1 | 0.748 | 0.807 | **+0.060 [+0.015, +0.114]** | +0.052 [−0.010, +0.121] |
| T3 accuracy | 0.802 | 0.844 | +0.042 [−0.021, +0.105] | −0.037 [−0.108, +0.034] |
| T3 top-3 | 0.948 | 0.990 | **+0.042 [+0.010, +0.083]** | +0.019 [+0.000, +0.065] |
| T2 link-F1 | 0.455 | 0.286 | −0.169 [−0.409, +0.000] | −0.149 [−0.374, +0.015] |
| cost per issue | $0.0071 | $0.0067 | | |

**Failure categories** (LLM tagger): **code-location confusion 31 → 23**, correct evidence ignored 14 → 11. Failing issues fell from 72 to 69.

**Reading.**
- The change hit its target: area labels and top-3 components improved, and the category shrank.
- The T2 drop (13 duplicate pairs; the interval touches 0) is most likely run-to-run variance in which candidates the agent opens. The tool change doesn't touch issue search. It's flagged to watch, not acted on.

**Decision.** Kept.

---

## Iteration 7: a stricter label schema (negative result, reverted)

- **Date:** 2026-09-30 · **System:** reference agent, prompt v2 → v3 · **Commits:** `3f521c8`, reverted in `04e6bf7`
- **Runs:** A = `deb407` (iteration 6), B = `20260930-213951-agent-f93e7d`

**Observation.**
- **Topic/OS over-labeling** was the largest category (42). Topic/OS labels had precision 0.50 and recall 0.96 on gold.
- About 5 answers in 100 had no type label at all.
- Iteration 3 had shown that a *required* field changes this model's behaviour.

**Change.** Two schema changes:
- `type_label` became a required single field;
- every other label got a required `basis: central | incidental`, and the harness kept only `central` labels.

**Result** (gold): T1 micro-F1 −0.031 [−0.071, +0.015], area −0.050 [−0.108, +0.005], T3 −0.010.

**What happened inside:**
- **Missing type labels went from 5 to 0, but type precision fell 0.83 → 0.79.** The forced guesses were often wrong.
- **The model marked only 24 of 228 labels "incidental".** Topic/OS precision stayed at 0.49, and area recall fell 0.80 → 0.74 (some true areas were marked incidental).
- **Failure categories:** failing issues rose 69 → 75, and correct evidence ignored went 11 → 20.

**Decision.** Reverted.

**Takeaway.** This refines iteration 3's lesson. A schema can force **structure** (a field gets filled), but it can't force **judgement**: a self-reported "basis" is only as good as the model's ability to tell central from incidental. The 27B makes 16 fewer topic/OS errors on the same prompt (E5), which points to capacity rather than prompting.

---

## Iteration 8: drop low-confidence topic/OS labels (kept)

- **Date:** 2026-10-01 · **System:** every LLM labeller (`system.family_label_min_confidence`, `triagelab/labels.py`) · **Commits:** `338b586`, `a2a4a37`, `3af02f9`
- **Runs:** A = `deb407` (iteration 6), B = `20260930-233640-agent-1f32af` (the same model answers, replayed from the cache: $0)

**Observation.** The model can't tell which topic labels are wrong, but it *says* so:

| topic/OS label confidence | right / total (gold) |
|---|---|
| < 0.95 | **3 / 44** |
| ≥ 0.95 | 42 / 46 |

Type and area labels are nearly all given ≥ 0.9, so a floor barely touches them.

**Change.**
- Topic/OS labels below a confidence floor are dropped.
- **Choosing the floor on dev, honestly:**
  - Confidences are discrete (0.9, 0.95, 0.99, 1.0).
  - Over the grid {0.8, 0.9, 0.95, 0.97, 0.99, 1.0, drop-all}, 0.95 is an interior optimum on all three 9B runs checked (iterations 5 and 6, and E2's no-skill run).
  - **2-fold cross-fitting** (choose on one half of dev, score on the other) picked 0.95 in every fold. The cross-fitted gold micro-F1, 0.831, equals the in-sample value, so there's no sign the choice overfits dev.

**Result:**

| metric | Δ gold [95% CI] | Δ silver [95% CI] |
|---|---|---|
| T1 micro-F1 | **+0.056 [+0.037, +0.077]** | **+0.057 [+0.030, +0.083]** |
| T1 macro-F1 | **+0.148 [+0.077, +0.211]** | **+0.075 [+0.032, +0.166]** |
| type, area, T2, T3 | exactly 0 | exactly 0 |

**Failure categories:**
- **topic/OS over-labeling 42 → 8.** Failing issues fell 69 → 56.
- Every other category moved by at most ±4, even though the traces are byte-identical between A and B. **That ±4 is the tagger's own noise**, and a useful calibration for reading every other category delta.

**Fairness check.** The floor is post-processing that helps any LLM labeller, so the single-shot baseline gets it too (`e1-llm-single-shot-thinking-floor`): its gold micro-F1 rises 0.70 → 0.76 (silver 0.69 → 0.74). With the floor on both, the agent still leads by **+0.075 [+0.027, +0.127]**, down from the +0.13 without it.

**Decision.** Kept, at system level for every LLM labeller.

**Takeaway across M6.**
- What worked:
  - a **mechanical** change in the tool (iteration 6);
  - a **mechanical** change on the model's own confidence (iteration 8).
- What didn't: a schema asking the model to judge itself (iteration 7).
- The pattern from iterations 3–5 holds. With a 9B model, improve what the harness computes and filters, not what you ask the model to decide.
