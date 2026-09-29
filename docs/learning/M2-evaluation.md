# M2: Baselines and scoring

**What M2 built:** the measuring instrument, plus the first measurements:
- one output contract (`TriageResult`) for every system;
- hand-written task metrics and a bootstrap (single and paired);
- a parallel, resumable, budget-safe eval runner with a locked test split;
- three E1 baselines (majority, TF-IDF classifier, single-shot LLM);
- a results table built from the run registry;
- the first documented iteration, and an eval job in CI.

**Why it matters:** with n = 100 (dev) and n = 50 (test), the confidence interval *is* the result. A system that "gets 0.6" means little until you know it's 0.6 [0.47, 0.72], and that a competitor's interval overlaps it.

```
triagelab eval -c configs/experiments/e1-classifier.yaml --split dev
  load_split(dev) ──► EvalExample(snapshot, gold, weight) × 100
  build_triager ──► Majority | Classifier(TF-IDF+LR, fitted on train) | LLMSingleShot(client)
  ThreadPoolExecutor(4–8) ─► triager.triage(snapshot) ─► predictions.jsonl (append, resumable)
      exceptions ─► "infra:" results ─► one 1-worker retry pass
      BudgetGuard.reserve/settle under a lock ─► can't overshoot with parallel calls
  score() ─► METRICS[name](golds, preds, weights) ─► bootstrap_ci (1,000 issue resamples)
  runs/<id>/ metrics.json · predictions.{jsonl,parquet} · cost.json · manifest(details: split, dataset hash)
triagelab compare A B [--exclude-errors] ─► paired_bootstrap per metric ─► "significant" iff CI ∌ 0
triagelab results --split dev ─► reports/results/dev.md
```

---

## 1. Concepts, and where they live

| Concept | What to take away | Code |
|---|---|---|
| **One contract, many systems** | Baselines, agent and cascade all return `TriageResult`, so one scorer is fair to all of them. | `triage.py`: `TriageResult`, `Triager` |
| **Metrics as a registry** | Each headline metric is one function over (gold, pred, weight). Points, intervals and comparisons reuse it. | `eval/score.py`: `METRICS`, `statistic` |
| **Subsets are part of a metric** | T1 is scored on triaged issues, T3 where a gold component exists. Otherwise "no label because nobody looked" counts as a wrong answer. | `eval/score.py`: `_t1`, `_t3` |
| **Entity-linking F1 for duplicates** | Naming the wrong original is both an FP and an FN. "Detection F1" is the looser view. | `eval/metrics.py`: `duplicate_prf` |
| **Percentile bootstrap** | Resample issues with replacement, recompute, take the 2.5/97.5 percentiles. Drop undefined resamples; don't zero them. | `eval/bootstrap.py`: `bootstrap_ci` |
| **Paired bootstrap** | Resample the *same* issues for both systems. Issue difficulty cancels out, so it's far more sensitive than overlapping two intervals. | `eval/bootstrap.py`: `paired_bootstrap` |
| **Weighted (natural-rate) estimates** | The stratified sample oversamples duplicates. Weights `N_h/n_h` give the natural-population estimate beside the sample one. | `eval/metrics.py` (every metric takes weights) |
| **Budget reservation** | With parallel calls, "check then charge" overshoots. Reserve the worst case atomically, then settle. | `cost.py`: `BudgetGuard.reserve/settle/release` |
| **Infra vs. model failures** | A 429 is not a wrong answer. Mark raised errors `infra:`, retry them, and never score them as answers. | `eval/runner.py`: `_timed`, `_needs_run` |
| **Policy as code** | The test split needs a flag and is capped at two logged evaluations. | `eval/runner.py`: `TestSetGuard` |
| **Time-respecting retrieval** | Duplicate search considers only issues created strictly before the query. | `baselines/classifier.py`: `_neighbours` |

## 2. Findings so far (dev, silver)

- **The classifier is a strong floor:**
  - T1 micro-F1 0.71 [0.64, 0.77];
  - T3 accuracy 0.65 [0.52, 0.77], and top-3 0.94.
  - A 9B LLM with generic instructions does *not* beat it on T1 or T3. That's the E1 answer, and the reason the agent needs skills and tools.
- **Iteration 1** (`docs/ITERATIONS.md`): the prompt listed labels as `area: stdlib, …`, and the model wrote `area-stdlib` on 57% of issues.
  - The fix: exact strings.
  - The result: area F1 +0.475 [+0.349, +0.591].
  - That was found only because out-of-taxonomy labels are *recorded*, not silently dropped.
- **Duplicates:**
  - TF-IDF nearest neighbour gets link-F1 0.11 [0.00, 0.32], so most duplicates aren't lexically obvious. That's M3's job.
  - The single-shot LLM can't do T2 at all (no retrieval).

## 3. Pitfalls (most happened during M2)

1. **Scoring outages as answers.** 5 OpenRouter 429s became "empty predictions" and dragged v1's metrics down. Separate infra errors from model errors.
2. **Sampled comparisons.** v1 and v2 ran at the default temperature, so part of the "delta" is randomness that a bootstrap over issues can't see. Set temperature 0 where possible, and measure consistency (M6).
3. **Vocabulary formatting leaks into answers.** Small models copy the presentation (`area:` → `area-stdlib`). List exact strings.
4. **A subset metric computed on everything.** Scoring T1 on untriaged issues punishes correct labels that nobody applied.
5. **A vectoriser fitted on everything.** Fitting TF-IDF on dev/test text leaks their vocabulary and IDF into training. Fit on train only.
6. **Heredoc escapes.** Python edit scripts embedded in shell heredocs turned `\n` into real newlines twice. Use the file-editing tool for escape-heavy edits.

## 4. How an interviewer might probe this

- *"Your model scored 0.59 and the baseline 0.65. Is the baseline better?"* → Maybe not. Look at the paired bootstrap interval of the difference. If it spans 0, you have no evidence either way at n = 100.
- *"Why a paired bootstrap rather than comparing two CIs?"* → Both systems are scored on the same issues. Pairing cancels issue difficulty, so the variance of the *difference* is much smaller than the two separate variances suggest. Overlapping CIs can still hide a significant paired difference.
- *"How do you stop parallel evals from blowing the budget?"* → Atomic reservation of the worst case (`max_tokens` output plus a byte-bounded input) before the call, settled after it.
- *"How do you keep yourself honest about the test set?"* → Code-level lock, a flag, a cap of two, and a log.
- *"What is your strongest baseline, and why does it matter?"* → TF-IDF + LR. If an agent can't beat it, its extra cost isn't justified. E1 exists to set that bar.

## 5. Self-check questions

1. Why is T1 scored only on human-triaged issues?
2. A paired bootstrap gives Δ = +0.08 [−0.01, +0.17]. What do you conclude?
3. Why does `BudgetGuard.reserve` hold a lock, and what would go wrong without reservation?
4. Why does the classifier's duplicate search filter by `created_at` even though every indexed issue is historical?
5. What does the weighted T2 recall estimate that the unweighted one doesn't?

<details><summary>Answers</summary>

1. Silver labels only exist where someone triaged. An untriaged issue has no labels for lack of attention, so a correct prediction there would be scored as a false positive.
2. No evidence of an improvement at this sample size: the interval includes 0. It *might* help; you'd need more issues or a larger effect to know.
3. Eight workers could each see enough headroom before any has been charged, and together overshoot the cap. Reserving the worst case under a lock makes check-and-claim atomic, so later workers see the claimed amount.
4. "Historical" is relative to each query. For a dev issue created in June, a July dev issue is the future. Without the filter, the model could find an issue's own later duplicate report and name it as the "original", which is time travel.
5. The dev sample oversamples duplicates (13% vs. about 3% naturally). Weighting each issue by its stratum's `N_h/n_h` estimates recall on the natural population, which is what a deployed system would face.

</details>
