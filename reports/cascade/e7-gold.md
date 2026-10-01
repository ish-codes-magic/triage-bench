# E7: cascade, stuffed agent -> full agent, dev (gold labels)

Cheap tier `20261001-000322-e3-stuffed-c7868d`; full agent `20260930-233640-agent-1f32af`; n = 97 issues. τ is the cheapest threshold whose t1_micro_f1, t3_accuracy stay within 0.0 of the full agent's on dev.

| system | τ | escalated | t1_micro_f1 | t3_accuracy | cost / 1,000 issues |
|---|---|---|---|---|---|
| cheap tier alone | | 0% | 0.822 | 0.844 | $1.14 |
| full agent alone | | 0% | 0.831 | 0.844 | $6.84 |
| self-confidence | 0.700 | 4% | 0.839 | 0.854 | $1.38 |
| self-confidence, cross-fitted (τ 0.70, 0.00) | | 2% | 0.825 | 0.833 | $1.19 |
| agrees with LLM (logprobs) | 0.412 | 44% | 0.852 | 0.854 | $4.20 |
| agrees with LLM (logprobs), cross-fitted (τ 0.41, 0.00) | | 16% | 0.831 | 0.833 | $2.31 |
| agrees with LLM (verbalized) | 0.950 | 37% | 0.845 | 0.844 | $3.62 |
| agrees with LLM (verbalized), cross-fitted (τ 0.95, 0.00) | | 13% | 0.830 | 0.823 | $1.98 |
| agrees with classifier | 0.288 | 56% | 0.840 | 0.844 | $4.76 |
| agrees with classifier, cross-fitted (τ 0.29, 0.00) | | 25% | 0.821 | 0.833 | $2.69 |

Cascade at the chosen τ minus the full agent (paired bootstrap, 1,000 resamples):

| gate | metric | Δ [95% CI] |
|---|---|---|
| self-confidence | t1_micro_f1 | +0.008 [-0.035, +0.048] |
| self-confidence | t3_accuracy | +0.010 [-0.052, +0.074] |
| agrees with LLM (logprobs) | t1_micro_f1 | +0.021 [-0.006, +0.049] |
| agrees with LLM (logprobs) | t3_accuracy | +0.010 [-0.021, +0.052] |
| agrees with LLM (verbalized) | t1_micro_f1 | +0.014 [-0.014, +0.044] |
| agrees with LLM (verbalized) | t3_accuracy | +0.000 [-0.042, +0.042] |
| agrees with classifier | t1_micro_f1 | +0.009 [-0.010, +0.031] |
| agrees with classifier | t3_accuracy | +0.000 [-0.031, +0.031] |

![cascade curve](../figures/e7-gold-cascade.png)

Cross-fitted rows route each issue by the τ chosen on the other half of dev, so they estimate what the chosen τ does on unseen issues.
