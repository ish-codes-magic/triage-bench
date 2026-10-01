### Regression gate: FAIL

Candidate `20260929-134512-e1-llm-single-shot-thinking-075806` vs baseline `20260930-233640-agent-1f32af` on 50 shared issues. Deltas are candidate - baseline with 95% paired-bootstrap intervals.

| metric | baseline | candidate | delta [95% CI] | rule | verdict |
|---|---|---|---|---|---|
| coverage | 1.000 | 1.000 | +0.000 | min 100% | pass |
| t1_micro_f1 | 0.848 | 0.698 | -0.151 [-0.214, -0.086] | max drop 0.05 | **FAIL** |
| t3_accuracy | 0.840 | 0.740 | -0.100 [-0.220, +0.020] | max drop 0.08 | **FAIL** |
| t1_type_micro_f1 | 0.848 | 0.780 | -0.068 [-0.168, +0.020] |  |  |
| t1_area_micro_f1 | 0.825 | 0.714 | -0.110 [-0.223, -0.021] |  |  |
| t3_top3_accuracy | 0.980 | 0.940 | -0.040 [-0.100, +0.000] |  |  |
| t2_link_f1 | 0.000 | 0.000 | +0.000 [+0.000, +0.000] |  |  |
| cost_per_issue_usd | $0.00778 | $0.00027 | -0.00752 | max rise 30% | pass |
| error_rate | 0.000 | 0.000 | +0.000 | max 6% | pass |
