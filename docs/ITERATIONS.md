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
