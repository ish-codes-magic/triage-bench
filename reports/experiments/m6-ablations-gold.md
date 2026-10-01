# M6 ablations, dev (n = 100), vs the reference agent (gold labels)

| comparison (B - A) | t1_micro_f1 | t1_type_micro_f1 | t1_area_micro_f1 | t2_link_f1 | t3_accuracy | t3_top3_accuracy |
|---|---|---|---|---|---|---|
| E2: no skill | -0.014 [-0.055, +0.025] | -0.039 [-0.113, +0.028] | -0.000 [-0.057, +0.052] | +0.078 [-0.204, +0.389] | +0.010 [-0.052, +0.073] | -0.031 [-0.072, +0.000] |
| E2: generic skill (first call) | -0.018 [-0.065, +0.026] | -0.027 [-0.109, +0.061] | +0.009 [-0.034, +0.054] | +0.067 [-0.226, +0.330] | -0.010 [-0.063, +0.043] | +0.000 [+0.000, +0.000] |
| E2: CPython skill (first call) | -0.005 [-0.049, +0.040] | +0.012 [-0.062, +0.091] | -0.017 [-0.072, +0.039] | +0.135 [-0.156, +0.422] | -0.021 [-0.093, +0.053] | **-0.042 [-0.084, -0.010]** |
| E2: auto skill (first call) | -0.012 [-0.069, +0.040] | -0.008 [-0.099, +0.069] | +0.021 [-0.042, +0.084] | -0.152 [-0.476, +0.243] | -0.010 [-0.074, +0.052] | -0.021 [-0.062, +0.021] |
| E2: CPython skill vs no skill | +0.008 [-0.030, +0.049] | +0.052 [-0.031, +0.138] | -0.016 [-0.059, +0.027] | +0.057 [-0.304, +0.371] | -0.031 [-0.083, +0.021] | -0.010 [-0.043, +0.021] |
| E2: auto vs CPython skill | -0.006 [-0.062, +0.042] | -0.021 [-0.096, +0.046] | +0.037 [-0.037, +0.106] | -0.288 [-0.568, +0.000] | +0.010 [-0.052, +0.073] | +0.021 [-0.031, +0.072] |
| E3: top-8 similar issues stuffed, no MCP tools | -0.009 [-0.059, +0.037] | -0.017 [-0.104, +0.071] | +0.018 [-0.040, +0.072] | +0.114 [-0.175, +0.400] | +0.000 [-0.073, +0.073] | **-0.062 [-0.115, -0.021]** |
| E4: planner + subagents | -0.042 [-0.081, +0.001] | +0.002 [-0.074, +0.078] | -0.013 [-0.071, +0.042] | -0.104 [-0.286, +0.012] | +0.021 [-0.052, +0.103] | -0.021 [-0.062, +0.021] |
| E5: Qwen3.5-27B | **+0.070 [+0.031, +0.110]** | **+0.095 [+0.029, +0.166]** | **+0.092 [+0.035, +0.153]** | +0.169 [+0.000, +0.403] | +0.062 [-0.000, +0.127] | +0.010 [+0.000, +0.032] |
| Agent vs single-shot LLM (both with the floor) | **+0.075 [+0.027, +0.127]** | +0.029 [-0.050, +0.111] | **+0.118 [+0.038, +0.200]** | +0.286 [+0.000, +0.522] | +0.083 [-0.021, +0.188] | **+0.042 [+0.010, +0.083]** |
| Agent vs TF-IDF classifier | **+0.114 [+0.061, +0.169]** | **+0.090 [+0.011, +0.174]** | **+0.104 [+0.027, +0.185]** | +0.175 [-0.211, +0.476] | **+0.125 [+0.031, +0.232]** | +0.010 [-0.021, +0.042] |

Gold labels. Paired bootstrap over the issues both runs answered (1,000 resamples); **bold** = the 95% interval excludes 0. Reference: `20260930-233640-agent-1f32af`.

## Failure categories

| run | failing issues | code-location confusion | type-label error | search process failure | duplicate retrieval error | correct evidence ignored | topic/OS over-labeling |
|---|---|---|---|---|---|---|---|
| reference (`1f32af`) | 56 | 23 | 20 | 17 | 15 | 12 | 8 |
| E2: no skill (`2230f7`) | 57 | 24 | 23 | 18 | 14 | 13 | 5 |
| E2: generic skill (first call) (`c174ab`) | 54 | 25 | 21 | 7 | 11 | 13 | 4 |
| E2: CPython skill (first call) (`bf6187`) | 51 | 26 | 16 | 10 | 11 | 4 | 5 |
| E2: auto skill (first call) (`70827e`) | 53 | 22 | 19 | 16 | 13 | 8 | 7 |
| E3: top-8 similar issues stuffed, no MCP tools (`c7868d`) | 56 | 20 | 19 | 31 | 12 | 0 | 9 |
| E4: planner + subagents (`31a518`) | 65 | 27 | 16 | 2 | 18 | 15 | 16 |
| E5: Qwen3.5-27B (`7da3e4`) | 40 | 14 | 8 | 6 | 12 | 5 | 0 |

Failure categories from the LLM tagger against the adjudicated labels (docs/FAILURE_TAXONOMY.md; categories with tagger kappa < 0.6 are unvalidated).
