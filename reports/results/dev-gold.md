# Results: dev split (gold labels)

| experiment | system | T1 micro-F1 | T1 area F1 | T2 link F1 | T3 acc | T3 top-3 | $/issue | p50 latency |
|---|---|---|---|---|---|---|---|---|
| agent | agent | 0.83 [0.78, 0.88] | 0.81 [0.74, 0.87] | 0.29 [0.00, 0.52] | 0.84 [0.77, 0.91] | 0.99 [0.97, 1.00] | $0.00684 | replay |
| e1-classifier | classifier | 0.72 [0.67, 0.77] | 0.70 [0.63, 0.78] | 0.11 [0.00, 0.36] | 0.72 [0.62, 0.81] | 0.98 [0.95, 1.00] | $0.00000 | 0.1s |
| e1-llm-single-shot | llm_single_shot | 0.60 [0.56, 0.65] | 0.59 [0.52, 0.67] | 0.00 [0.00, 0.00] | 0.73 [0.64, 0.81] | 0.94 [0.89, 0.98] | $0.00015 | 16.6s |
| e1-llm-single-shot-thinking | llm_single_shot | 0.70 [0.65, 0.74] | 0.69 [0.62, 0.76] | 0.00 [0.00, 0.00] | 0.76 [0.67, 0.84] | 0.95 [0.91, 0.99] | $0.00026 | 22.8s |
| e1-llm-single-shot-thinking-floor | llm_single_shot | 0.76 [0.71, 0.80] | 0.69 [0.62, 0.76] | 0.00 [0.00, 0.00] | 0.76 [0.67, 0.84] | 0.95 [0.91, 0.99] | $0.00026 | replay |
| e1-majority | majority | 0.38 [0.32, 0.44] | 0.37 [0.28, 0.46] | 0.00 [0.00, 0.00] | 0.22 [0.14, 0.31] | 0.79 [0.71, 0.87] | $0.00000 | 0.0s |
| e2-skills-auto | agent | 0.82 [0.77, 0.87] | 0.83 [0.76, 0.89] | 0.13 [0.00, 0.38] | 0.83 [0.76, 0.91] | 0.97 [0.93, 1.00] | $0.00744 | replay |
| e2-skills-generic | agent | 0.81 [0.77, 0.86] | 0.82 [0.76, 0.87] | 0.35 [0.00, 0.62] | 0.83 [0.76, 0.91] | 0.99 [0.97, 1.00] | $0.00687 | replay |
| e2-skills-none | agent | 0.82 [0.77, 0.86] | 0.81 [0.74, 0.87] | 0.36 [0.10, 0.62] | 0.85 [0.78, 0.92] | 0.96 [0.92, 0.99] | $0.00671 | replay |
| e2-skills-repo | agent | 0.83 [0.78, 0.87] | 0.79 [0.72, 0.86] | 0.42 [0.11, 0.67] | 0.82 [0.75, 0.90] | 0.95 [0.90, 0.99] | $0.00638 | replay |
| e3-stuffed | agent | 0.82 [0.78, 0.87] | 0.83 [0.76, 0.89] | 0.40 [0.11, 0.63] | 0.84 [0.77, 0.92] | 0.93 [0.87, 0.97] | $0.00114 | replay |
| e4-planner | agent | 0.79 [0.75, 0.83] | 0.79 [0.74, 0.85] | 0.18 [0.00, 0.40] | 0.86 [0.80, 0.93] | 0.97 [0.93, 1.00] | $0.00357 | replay |
| e5-agent-27b | agent | 0.90 [0.86, 0.94] | 0.90 [0.85, 0.95] | 0.45 [0.15, 0.70] | 0.91 [0.84, 0.96] | 1.00 [1.00, 1.00] | $0.02433 | replay |

Gold labels (adjudicated issues only), dev split (n = 97). Cells are point estimates with 95% bootstrap intervals (1,000 issue resamples). Dataset hash: 23ee2ef6f25b. Runs: `20260930-233640-agent-1f32af`, `20260929-100338-e1-classifier-aabfa4`, `20260929-102356-e1-llm-single-shot-f80f1d`, `20260929-134512-e1-llm-single-shot-thinking-075806`, `20261001-003800-e1-llm-single-shot-thinking-floor-05e243`, `20260929-100332-e1-majority-260ca4`, `20260930-235712-e2-skills-auto-70827e`, `20260930-234546-e2-skills-generic-c174ab`, `20260930-234546-e2-skills-none-2230f7`, `20260930-235712-e2-skills-repo-bf6187`, `20261001-000322-e3-stuffed-c7868d`, `20261001-000322-e4-planner-31a518`, `20261001-001157-e5-agent-27b-7da3e4`.

"replay": the run re-used every model answer from the cache (a post-processing change), so its latency measures the replay; the live run's latency applies.
