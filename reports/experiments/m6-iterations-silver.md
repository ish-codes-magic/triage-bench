# M6 iterations, dev (n = 100) (silver labels)

| comparison (B - A) | t1_micro_f1 | t1_macro_f1 | t1_type_micro_f1 | t1_area_micro_f1 | t2_link_f1 | t3_accuracy | t3_top3_accuracy |
|---|---|---|---|---|---|---|---|
| 6: tools name each file's component (kept) | +0.015 [-0.024, +0.054] | -0.004 [-0.045, +0.046] | -0.027 [-0.089, +0.037] | +0.052 [-0.010, +0.121] | -0.149 [-0.374, +0.015] | -0.037 [-0.108, +0.034] | +0.019 [+0.000, +0.065] |
| 7: one type label + central/incidental basis (reverted) | -0.025 [-0.074, +0.020] | -0.027 [-0.083, +0.041] | -0.006 [-0.089, +0.071] | -0.034 [-0.105, +0.026] | +0.095 [-0.155, +0.378] | -0.019 [-0.096, +0.068] | -0.019 [-0.061, +0.000] |
| 8: drop topic/OS labels under 0.95 confidence (kept) | **+0.057 [+0.030, +0.083]** | **+0.075 [+0.032, +0.166]** | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |

Silver labels. Paired bootstrap over the issues both runs answered (1,000 resamples); **bold** = the 95% interval excludes 0. Reference: `20260930-000255-agent-cf734a`.
