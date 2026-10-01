### Regression gate: PASS

Candidate `20261001-005238-gate-agent-87abb1` vs baseline `20260930-233640-agent-1f32af` on 50 shared issues. Deltas are candidate - baseline with 95% paired-bootstrap intervals.

| metric | baseline | candidate | delta [95% CI] | rule | verdict |
|---|---|---|---|---|---|
| coverage | 1.000 | 1.000 | +0.000 | min 100% | pass |
| t1_micro_f1 | 0.848 | 0.848 | +0.000 [+0.000, +0.000] | max drop 0.05 | pass |
| t3_accuracy | 0.840 | 0.840 | +0.000 [+0.000, +0.000] | max drop 0.08 | pass |
| t1_type_micro_f1 | 0.848 | 0.848 | +0.000 [+0.000, +0.000] |  |  |
| t1_area_micro_f1 | 0.825 | 0.825 | +0.000 [+0.000, +0.000] |  |  |
| t3_top3_accuracy | 0.980 | 0.980 | +0.000 [+0.000, +0.000] |  |  |
| t2_link_f1 | 0.000 | 0.000 | +0.000 [+0.000, +0.000] |  |  |
| cost_per_issue_usd | $0.00778 | $0.00778 | +0.00000 | max rise 30% | pass |
| error_rate | 0.000 | 0.000 | +0.000 | max 6% | pass |

| failure category | baseline | candidate | delta |
|---|---|---|---|
| code-location confusion | 12 | 12 | +0 |
| type-label error | 9 | 9 | +0 |
| search process failure | 8 | 8 | +0 |
| correct evidence ignored | 7 | 7 | +0 |
| duplicate retrieval error | 5 | 5 | +0 |
| topic/OS over-labeling | 4 | 4 | +0 |
| needs-info over-flagging | 2 | 2 | +0 |
| ground-truth noise | 1 | 1 | +0 |
