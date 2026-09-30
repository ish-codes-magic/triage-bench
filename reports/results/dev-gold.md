# Results: dev split (gold labels)

| experiment | system | T1 micro-F1 | T1 area F1 | T2 link F1 | T3 acc | T3 top-3 | T4 F1 | $/issue | p50 latency |
|---|---|---|---|---|---|---|---|---|---|
| agent | agent | 0.75 [0.71, 0.80] | 0.75 [0.68, 0.82] | 0.45 [0.14, 0.70] | 0.80 [0.72, 0.88] | 0.95 [0.91, 0.99] | n/a | $0.00658 | 99.0s |
| e1-classifier | classifier | 0.72 [0.67, 0.77] | 0.70 [0.63, 0.78] | 0.11 [0.00, 0.36] | 0.72 [0.62, 0.81] | 0.98 [0.95, 1.00] | n/a | $0.00000 | 0.1s |
| e1-llm-single-shot | llm_single_shot | 0.60 [0.56, 0.65] | 0.59 [0.52, 0.67] | 0.00 [0.00, 0.00] | 0.73 [0.64, 0.81] | 0.94 [0.89, 0.98] | n/a | $0.00015 | 16.6s |
| e1-llm-single-shot-thinking | llm_single_shot | 0.70 [0.65, 0.74] | 0.69 [0.62, 0.76] | 0.00 [0.00, 0.00] | 0.76 [0.67, 0.84] | 0.95 [0.91, 0.99] | n/a | $0.00026 | 22.8s |
| e1-majority | majority | 0.38 [0.32, 0.44] | 0.37 [0.28, 0.46] | 0.00 [0.00, 0.00] | 0.22 [0.14, 0.31] | 0.79 [0.71, 0.87] | n/a | $0.00000 | 0.0s |

Gold labels (adjudicated issues only), dev split (n = 97). Cells are point estimates with 95% bootstrap intervals (1,000 issue resamples). Dataset hash: 23ee2ef6f25b. Runs: `20260930-000255-agent-cf734a`, `20260929-100338-e1-classifier-aabfa4`, `20260929-102356-e1-llm-single-shot-f80f1d`, `20260929-134512-e1-llm-single-shot-thinking-075806`, `20260929-100332-e1-majority-260ca4`.
