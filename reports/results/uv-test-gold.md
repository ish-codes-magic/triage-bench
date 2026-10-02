# Results: astral-sh/uv, test split (gold labels)

| experiment | system | T1 micro-F1 | T1 type F1 | T1 area F1 | T2 link F1 | T3 acc | T3 top-3 | fallbacks | $/issue | p50 latency |
|---|---|---|---|---|---|---|---|---|---|---|
| uv-agent | agent | 0.75 [0.65, 0.85] | 0.77 [0.65, 0.88] | 0.67 [0.00, 1.00] | 0.29 [0.00, 0.80] | 0.68 [0.53, 0.82] | 0.93 [0.84, 1.00] | 0 | $0.01015 | 147.6s |
| uv-classifier | classifier | 0.38 [0.25, 0.51] | 0.42 [0.27, 0.56] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.63 [0.49, 0.79] | 0.83 [0.71, 0.93] | 0 | $0.00000 | 0.0s |
| uv-llm-single-shot | llm_single_shot | 0.67 [0.57, 0.77] | 0.73 [0.61, 0.85] | 0.38 [0.14, 0.86] | 0.00 [0.00, 0.00] | 0.68 [0.53, 0.82] | 0.95 [0.88, 1.00] | 0 | $0.00024 | 61.5s |
| uv-routed | routed | 0.70 [0.60, 0.79] | 0.78 [0.66, 0.88] | 0.24 [0.00, 1.00] | 0.00 [0.00, 0.00] | 0.56 [0.40, 0.71] | 0.90 [0.80, 0.98] | 2 | $0.00184 | 202.1s |
| uv-stuffed | agent | 0.68 [0.57, 0.77] | 0.76 [0.63, 0.87] | 0.24 [0.00, 1.00] | 0.00 [0.00, 0.00] | 0.59 [0.43, 0.72] | 0.85 [0.74, 0.95] | 2 | $0.00168 | replay |

Gold labels (adjudicated issues only), test split (n = 50). Cells are point estimates with 95% bootstrap intervals (1,000 issue resamples). Fallbacks are issues the system could not answer; they are scored as wrong. Dataset hash: 3ba60bc3186f. Runs: `20261002-063047-uv-agent-63270f`, `20261002-065415-uv-classifier-d51e13`, `20261002-065430-uv-llm-single-shot-45059a`, `20261002-055359-uv-routed-960e05`, `20261002-065402-uv-stuffed-cd92c1`.

"replay": the run re-used every model answer from the cache (a post-processing change, or an earlier run that made the same calls), so its latency measures the replay; the live run's latency applies.
