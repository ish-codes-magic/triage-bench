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
