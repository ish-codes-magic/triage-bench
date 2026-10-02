# T5: triage comments of the final systems, judged (dev)

| system | comments | correctness | actionability | tone (not validated) | no comment | judge cost |
|---|---|---|---|---|---|---|
| e3-stuffed | 100 | 3.10 [2.90, 3.29] | 1.42 [1.26, 1.59] | 3.71 [3.58, 3.82] | 2 | $0.04 |
| agent | 100 | 2.86 [2.64, 3.06] | 1.36 [1.21, 1.53] | 3.74 [3.63, 3.84] | 0 | $0.04 |
| e1-llm-single-shot-thinking-floor | 100 | 3.22 [3.06, 3.38] | 1.90 [1.74, 2.08] | 3.71 [3.60, 3.82] | 0 | $0.04 |

Mean rubric score (1-4, higher is better) with a 95% bootstrap interval over issues. Judge prompt v2, rubric v1. An issue with no comment scores 1 on every criterion. Runs: `20261002-115926-e3-stuffed-dde819`, `20261002-115445-agent-5f73a1`, `20261001-192053-e1-llm-single-shot-thinking-floor-27a296`.
