# Results: astral-sh/uv, test split (silver labels)

| experiment | system | T1 micro-F1 | T1 type F1 | T1 area F1 | T2 link F1 | T3 acc | T3 top-3 | fallbacks | $/issue | p50 latency |
|---|---|---|---|---|---|---|---|---|---|---|
| uv-agent | agent | 0.39 [0.13, 0.63] | 0.29 [0.07, 0.56] | 1.00 [0.00, 1.00] | 0.29 [0.00, 0.80] | 0.59 [0.33, 0.82] | 0.88 [0.71, 1.00] | 0 | $0.01015 | 147.6s |
| uv-classifier | classifier | 0.41 [0.16, 0.67] | 0.43 [0.11, 0.70] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.53 [0.28, 0.79] | 0.65 [0.40, 0.88] | 0 | $0.00000 | 0.0s |
| uv-llm-single-shot | llm_single_shot | 0.29 [0.10, 0.50] | 0.22 [0.00, 0.46] | 1.00 [0.00, 1.00] | 0.00 [0.00, 0.00] | 0.71 [0.47, 0.91] | 1.00 [1.00, 1.00] | 0 | $0.00024 | 61.5s |
| uv-routed | routed | 0.25 [0.06, 0.47] | 0.21 [0.00, 0.44] | 1.00 [0.00, 1.00] | 0.00 [0.00, 0.00] | 0.53 [0.29, 0.78] | 0.94 [0.80, 1.00] | 2 | $0.00184 | 202.1s |
| uv-stuffed | agent | 0.30 [0.08, 0.53] | 0.29 [0.07, 0.54] | 1.00 [0.00, 1.00] | 0.00 [0.00, 0.00] | 0.65 [0.39, 0.87] | 0.88 [0.70, 1.00] | 2 | $0.00168 | replay |

Silver labels, test split (n = 50). Cells are point estimates with 95% bootstrap intervals (1,000 issue resamples). Fallbacks are issues the system could not answer; they are scored as wrong. Dataset hash: 3ba60bc3186f. Runs: `20261002-063047-uv-agent-63270f`, `20261002-065415-uv-classifier-d51e13`, `20261002-065430-uv-llm-single-shot-45059a`, `20261002-055359-uv-routed-960e05`, `20261002-065402-uv-stuffed-cd92c1`.

"replay": the run re-used every model answer from the cache (a post-processing change, or an earlier run that made the same calls), so its latency measures the replay; the live run's latency applies.
