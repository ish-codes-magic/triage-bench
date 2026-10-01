# E7: cascade, stuffed agent -> full agent, dev (silver labels)

Cheap tier `20261001-000322-e3-stuffed-c7868d`; full agent `20260930-233640-agent-1f32af`; n = 100 issues. τ is the cheapest threshold whose t1_micro_f1, t3_accuracy stay within 0.0 of the full agent's on dev.

| system | τ | escalated | t1_micro_f1 | t3_accuracy | cost / 1,000 issues |
|---|---|---|---|---|---|
| cheap tier alone | | 0% | 0.792 | 0.796 | $1.14 |
| full agent alone | | 0% | 0.800 | 0.778 | $6.73 |
| self-confidence | 0.990 | 89% | 0.800 | 0.778 | $7.36 |
| self-confidence, cross-fitted (τ 0.00, 0.99) | | 54% | 0.789 | 0.796 | $4.83 |
| agrees with LLM (logprobs) | 0.412 | 45% | 0.801 | 0.778 | $4.18 |
| agrees with LLM (logprobs), cross-fitted (τ 0.00, 0.93) | | 41% | 0.791 | 0.796 | $3.99 |
| agrees with LLM (verbalized) | 0.990 | 78% | 0.800 | 0.778 | $6.51 |
| agrees with LLM (verbalized), cross-fitted (τ 0.00, 0.99) | | 44% | 0.786 | 0.796 | $4.12 |
| agrees with classifier | 0.287 | 55% | 0.811 | 0.796 | $4.62 |
| agrees with classifier, cross-fitted (τ 0.00, 0.48) | | 48% | 0.801 | 0.815 | $4.28 |

Cascade at the chosen τ minus the full agent (paired bootstrap, 1,000 resamples):

| gate | metric | Δ [95% CI] |
|---|---|---|
| self-confidence | t1_micro_f1 | +0.000 [+0.000, +0.000] |
| self-confidence | t3_accuracy | +0.000 [+0.000, +0.000] |
| agrees with LLM (logprobs) | t1_micro_f1 | +0.001 [-0.031, +0.033] |
| agrees with LLM (logprobs) | t3_accuracy | +0.000 [+0.000, +0.000] |
| agrees with LLM (verbalized) | t1_micro_f1 | +0.000 [-0.012, +0.012] |
| agrees with LLM (verbalized) | t3_accuracy | +0.000 [+0.000, +0.000] |
| agrees with classifier | t1_micro_f1 | +0.011 [-0.012, +0.037] |
| agrees with classifier | t3_accuracy | +0.019 [+0.000, +0.059] |

![cascade curve](../figures/e7-silver-cascade.png)

Cross-fitted rows route each issue by the τ chosen on the other half of dev, so they estimate what the chosen τ does on unseen issues.

## Decision level (H3): the backend decides when confident, the agent otherwise

| question | system | τ | escalated | accuracy | cost / 1,000 issues |
|---|---|---|---|---|---|
| type | agent alone | | 100% | 0.833 | $6.81 |
| type | LLM (logprobs) alone |  | 0% | 0.869 | $0.16 |
| type | LLM (logprobs) -> agent | 0.412 | 0% | 0.869 | $0.16 |
| type | LLM (logprobs) -> agent, cross-fitted (τ 0.41, 0.47) |  | 1% | 0.869 | $0.17 |
| type | LLM (verbalized) alone |  | 0% | 0.869 | $0.17 |
| type | LLM (verbalized) -> agent | 0.950 | 0% | 0.869 | $0.17 |
| type | LLM (verbalized) -> agent, cross-fitted (τ 0.95, 0.99) |  | 25% | 0.845 | $1.81 |
| type | classifier alone |  | 0% | 0.833 | $0.00 |
| type | classifier -> agent | 0.402 | 0% | 0.833 | $0.00 |
| type | classifier -> agent, cross-fitted (τ 0.43, 0.57) |  | 12% | 0.857 | $0.94 |
| component | agent alone | | 100% | 0.778 | $7.10 |
| component | LLM (logprobs) alone |  | 0% | 0.685 | $0.12 |
| component | LLM (logprobs) -> agent | 0.675 | 15% | 0.778 | $1.35 |
| component | LLM (logprobs) -> agent, cross-fitted (τ 0.76, 0.68) |  | 17% | 0.796 | $1.48 |
| component | LLM (verbalized) alone |  | 0% | 0.815 | $0.13 |
| component | LLM (verbalized) -> agent | 0.950 | 0% | 0.815 | $0.13 |
| component | LLM (verbalized) -> agent, cross-fitted (τ 0.95, 0.95) |  | 0% | 0.815 | $0.13 |
| component | classifier alone |  | 0% | 0.574 | $0.00 |
| component | classifier -> agent | 0.423 | 44% | 0.778 | $2.89 |
| component | classifier -> agent, cross-fitted (τ 0.32, 0.54) |  | 46% | 0.685 | $3.43 |

Accuracy of the decision cascade at the chosen τ minus the agent's (paired bootstrap):

| question | backend | Δ accuracy [95% CI] |
|---|---|---|
| type | LLM (logprobs) | +0.036 [-0.071, +0.131] |
| type | LLM (verbalized) | +0.036 [-0.060, +0.131] |
| type | classifier | +0.000 [-0.095, +0.095] |
| component | LLM (logprobs) | +0.000 [-0.111, +0.111] |
| component | LLM (verbalized) | +0.037 [-0.056, +0.130] |
| component | classifier | +0.000 [-0.093, +0.093] |
