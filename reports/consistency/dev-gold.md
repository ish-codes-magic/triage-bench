# Consistency on dev: three runs of each final config (gold labels)

| system | decision | k | issues | accuracy per run | accuracy | pass^k | ever right | unanimous |
|---|---|---|---|---|---|---|---|---|
| routed system | type label | 3 | 97 | 0.87, 0.88, 0.87 | 0.87 [0.80, 0.93] | 0.87 [0.79, 0.93] | 0.88 [0.80, 0.94] | 0.99 [0.97, 1.00] |
| routed system | all labels (exact set) | 3 | 97 | 0.59, 0.52, 0.56 | 0.55 [0.46, 0.64] | 0.43 [0.34, 0.53] | 0.67 [0.58, 0.76] | 0.63 [0.54, 0.72] |
| routed system | component | 3 | 96 | 0.84, 0.84, 0.84 | 0.84 [0.77, 0.92] | 0.84 [0.77, 0.92] | 0.84 [0.77, 0.92] | 1.00 [1.00, 1.00] |
| routed system | duplicate link | 3 | 97 | 0.88, 0.84, 0.88 | 0.86 [0.80, 0.92] | 0.81 [0.73, 0.89] | 0.90 [0.84, 0.95] | 0.92 [0.86, 0.97] |
| stuffed agent | type label | 3 | 97 | 0.79, 0.80, 0.82 | 0.81 [0.74, 0.88] | 0.73 [0.64, 0.82] | 0.89 [0.82, 0.95] | 0.80 [0.72, 0.88] |
| stuffed agent | all labels (exact set) | 3 | 97 | 0.55, 0.51, 0.56 | 0.54 [0.45, 0.63] | 0.40 [0.31, 0.49] | 0.67 [0.58, 0.76] | 0.58 [0.47, 0.67] |
| stuffed agent | component | 3 | 96 | 0.84, 0.83, 0.82 | 0.83 [0.77, 0.89] | 0.73 [0.64, 0.81] | 0.91 [0.85, 0.96] | 0.81 [0.73, 0.90] |
| stuffed agent | duplicate link | 3 | 97 | 0.88, 0.84, 0.88 | 0.86 [0.80, 0.92] | 0.81 [0.73, 0.89] | 0.90 [0.84, 0.95] | 0.92 [0.86, 0.97] |
| full agent | type label | 3 | 97 | 0.78, 0.78, 0.73 | 0.77 [0.69, 0.84] | 0.67 [0.57, 0.76] | 0.87 [0.79, 0.93] | 0.79 [0.71, 0.87] |
| full agent | all labels (exact set) | 3 | 97 | 0.56, 0.56, 0.47 | 0.53 [0.45, 0.61] | 0.36 [0.27, 0.45] | 0.70 [0.62, 0.79] | 0.56 [0.45, 0.66] |
| full agent | component | 3 | 96 | 0.84, 0.82, 0.81 | 0.83 [0.76, 0.89] | 0.77 [0.69, 0.84] | 0.89 [0.82, 0.95] | 0.88 [0.80, 0.94] |
| full agent | duplicate link | 3 | 97 | 0.85, 0.87, 0.88 | 0.86 [0.79, 0.92] | 0.84 [0.76, 0.91] | 0.90 [0.84, 0.95] | 0.94 [0.89, 0.98] |

Gold labels. Each system was run k times on the same issues with the same config; only the model calls were repeated. Cells are point estimates with 95% bootstrap intervals over issues (1,000 resamples). Runs: routed system: `20261002-111057-routed-bb4345`, `20261002-111255-routed-bb4345`, `20261002-113110-routed-bb4345`; stuffed agent: `20261002-115926-e3-stuffed-dde819`, `20261002-115055-e3-stuffed-dde819`, `20261002-115127-e3-stuffed-dde819`; full agent: `20261002-115445-agent-5f73a1`, `20261002-111255-agent-5f73a1`, `20261002-113110-agent-5f73a1`.
