# Results: dev split

| experiment | system | T1 micro-F1 | T1 area F1 | T2 link F1 | T3 acc | T3 top-3 | T4 F1 | $/issue | p50 latency |
|---|---|---|---|---|---|---|---|---|---|
| agent | agent | 0.73 [0.67, 0.78] | 0.72 [0.62, 0.81] | 0.43 [0.13, 0.67] | 0.81 [0.70, 0.91] | 0.93 [0.84, 0.98] | 0.08 [0.00, 0.25] | $0.00645 | 99.2s |
| e1-classifier | classifier | 0.71 [0.64, 0.77] | 0.65 [0.56, 0.74] | 0.11 [0.00, 0.32] | 0.65 [0.52, 0.77] | 0.94 [0.87, 1.00] | 0.09 [0.00, 0.26] | $0.00000 | 0.1s |
| e1-llm-single-shot | llm_single_shot | 0.59 [0.54, 0.64] | 0.57 [0.48, 0.67] | 0.00 [0.00, 0.00] | 0.69 [0.56, 0.80] | 0.89 [0.79, 0.97] | 0.20 [0.05, 0.36] | $0.00015 | 16.7s |
| e1-llm-single-shot-thinking | llm_single_shot | 0.69 [0.63, 0.74] | 0.65 [0.57, 0.74] | 0.00 [0.00, 0.00] | 0.76 [0.64, 0.87] | 0.93 [0.84, 0.98] | 0.20 [0.05, 0.37] | $0.00026 | 22.8s |
| e1-majority | majority | 0.40 [0.32, 0.49] | 0.37 [0.26, 0.49] | 0.00 [0.00, 0.00] | 0.26 [0.15, 0.38] | 0.76 [0.64, 0.88] | 0.00 [0.00, 0.00] | $0.00000 | 0.0s |

Silver labels, dev split (n = 100). Cells are point estimates with 95% bootstrap intervals (1,000 issue resamples). Dataset hash: 23ee2ef6f25b. Runs: `20260930-000255-agent-cf734a`, `20260929-100338-e1-classifier-aabfa4`, `20260929-102356-e1-llm-single-shot-f80f1d`, `20260929-134512-e1-llm-single-shot-thinking-075806`, `20260929-100332-e1-majority-260ca4`.
