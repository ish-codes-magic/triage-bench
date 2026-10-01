# M6 iterations, dev (n = 100) (gold labels)

| comparison (B - A) | t1_micro_f1 | t1_macro_f1 | t1_type_micro_f1 | t1_area_micro_f1 | t2_link_f1 | t3_accuracy | t3_top3_accuracy |
|---|---|---|---|---|---|---|---|
| 6: tools name each file's component (kept) | +0.023 [-0.019, +0.062] | -0.002 [-0.043, +0.059] | -0.018 [-0.083, +0.042] | **+0.060 [+0.015, +0.114]** | -0.169 [-0.409, +0.000] | +0.042 [-0.021, +0.105] | **+0.042 [+0.010, +0.083]** |
| 7: one type label + central/incidental basis (reverted) | -0.031 [-0.071, +0.015] | -0.027 [-0.087, +0.038] | -0.029 [-0.107, +0.043] | -0.050 [-0.108, +0.005] | +0.095 [-0.167, +0.400] | -0.010 [-0.063, +0.042] | -0.010 [-0.032, +0.000] |
| 8: drop topic/OS labels under 0.95 confidence (kept) | **+0.056 [+0.037, +0.077]** | **+0.148 [+0.077, +0.211]** | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |

Gold labels. Paired bootstrap over the issues both runs answered (1,000 resamples); **bold** = the 95% interval excludes 0. Reference: `20260930-000255-agent-cf734a`.

## Failure categories

| run | failing issues | topic/OS over-labeling | code-location confusion | type-label error | search process failure | correct evidence ignored | duplicate retrieval error |
|---|---|---|---|---|---|---|---|
| reference (`cf734a`) | 72 | 42 | 31 | 20 | 13 | 14 | 13 |
| 6: tools name each file's component (kept) (`deb407`) | 69 | 42 | 23 | 21 | 13 | 11 | 15 |
| 7: one type label + central/incidental basis (reverted) (`f93e7d`) | 75 | 46 | 28 | 20 | 15 | 20 | 13 |
| 8: drop topic/OS labels under 0.95 confidence (kept) (`1f32af`) | 56 | 8 | 23 | 20 | 17 | 12 | 15 |

Failure categories from the LLM tagger against the adjudicated labels (docs/FAILURE_TAXONOMY.md; categories with tagger kappa < 0.6 are unvalidated).
