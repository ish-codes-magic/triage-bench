# Results: python/cpython, test split (silver labels)

| experiment | system | T1 micro-F1 | T1 type F1 | T1 area F1 | T2 link F1 | T3 acc | T3 top-3 | fallbacks | $/issue | p50 latency |
|---|---|---|---|---|---|---|---|---|---|---|
| agent | agent | 0.72 [0.60, 0.82] | 0.82 [0.67, 0.95] | 0.72 [0.55, 0.86] | 0.55 [0.00, 0.86] | 0.74 [0.56, 0.90] | 0.83 [0.67, 0.96] | 2 | $0.00650 | 107.2s |
| e1-classifier | classifier | 0.71 [0.61, 0.81] | 0.78 [0.64, 0.91] | 0.70 [0.55, 0.84] | 0.00 [0.00, 0.00] | 0.65 [0.45, 0.85] | 0.91 [0.79, 1.00] | 0 | $0.00000 | 0.1s |
| e1-llm-single-shot-thinking-floor | llm_single_shot | 0.69 [0.57, 0.80] | 0.84 [0.70, 0.96] | 0.60 [0.46, 0.75] | 0.00 [0.00, 0.00] | 0.61 [0.42, 0.82] | 0.78 [0.61, 0.95] | 0 | $0.00028 | 60.5s |
| e3-stuffed | agent | 0.78 [0.69, 0.86] | 0.91 [0.80, 0.98] | 0.77 [0.65, 0.88] | 0.36 [0.00, 0.71] | 0.78 [0.61, 0.94] | 0.87 [0.74, 1.00] | 0 | $0.00120 | replay |
| routed | routed | 0.78 [0.69, 0.86] | 0.91 [0.80, 0.98] | 0.77 [0.65, 0.88] | 0.36 [0.00, 0.71] | 0.70 [0.50, 0.88] | 0.87 [0.74, 1.00] | 0 | $0.00136 | 169.8s |

Silver labels, test split (n = 50). Cells are point estimates with 95% bootstrap intervals (1,000 issue resamples). Fallbacks are issues the system could not answer; they are scored as wrong. Dataset hash: 23ee2ef6f25b. Runs: `20261002-012957-agent-5f73a1`, `20261002-014930-e1-classifier-bc8659`, `20261002-015034-e1-llm-single-shot-thinking-floor-27a296`, `20261002-014913-e3-stuffed-dde819`, `20261002-010112-routed-bb4345`.

"replay": the run re-used every model answer from the cache (a post-processing change, or an earlier run that made the same calls), so its latency measures the replay; the live run's latency applies.
