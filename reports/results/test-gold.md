# Results: python/cpython, test split (gold labels)

| experiment | system | T1 micro-F1 | T1 type F1 | T1 area F1 | T2 link F1 | T3 acc | T3 top-3 | fallbacks | $/issue | p50 latency |
|---|---|---|---|---|---|---|---|---|---|---|
| agent | agent | 0.80 [0.72, 0.87] | 0.88 [0.79, 0.96] | 0.76 [0.65, 0.86] | 0.55 [0.00, 0.86] | 0.81 [0.69, 0.92] | 0.92 [0.83, 0.98] | 2 | $0.00650 | 107.2s |
| e1-classifier | classifier | 0.74 [0.68, 0.80] | 0.82 [0.73, 0.90] | 0.71 [0.61, 0.80] | 0.00 [0.00, 0.00] | 0.71 [0.58, 0.83] | 0.94 [0.86, 1.00] | 0 | $0.00000 | 0.1s |
| e1-llm-single-shot-thinking-floor | llm_single_shot | 0.73 [0.64, 0.81] | 0.86 [0.76, 0.94] | 0.61 [0.50, 0.72] | 0.00 [0.00, 0.00] | 0.67 [0.53, 0.80] | 0.90 [0.80, 0.98] | 0 | $0.00028 | 60.5s |
| e3-stuffed | agent | 0.87 [0.83, 0.91] | 0.99 [0.97, 1.00] | 0.82 [0.74, 0.90] | 0.36 [0.00, 0.71] | 0.81 [0.70, 0.91] | 0.92 [0.83, 0.98] | 0 | $0.00120 | replay |
| routed | routed | 0.88 [0.83, 0.92] | 1.00 [1.00, 1.00] | 0.82 [0.74, 0.90] | 0.36 [0.00, 0.71] | 0.73 [0.60, 0.84] | 0.92 [0.83, 0.98] | 0 | $0.00136 | 169.8s |

Gold labels (adjudicated issues only), test split (n = 50). Cells are point estimates with 95% bootstrap intervals (1,000 issue resamples). Fallbacks are issues the system could not answer; they are scored as wrong. Dataset hash: 23ee2ef6f25b. Runs: `20261002-012957-agent-5f73a1`, `20261002-014930-e1-classifier-bc8659`, `20261002-015034-e1-llm-single-shot-thinking-floor-27a296`, `20261002-014913-e3-stuffed-dde819`, `20261002-010112-routed-bb4345`.

"replay": the run re-used every model answer from the cache (a post-processing change, or an earlier run that made the same calls), so its latency measures the replay; the live run's latency applies.
