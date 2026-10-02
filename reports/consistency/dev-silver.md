# Consistency on dev: three runs of each final config (silver labels)

| system | decision | k | issues | accuracy per run | accuracy | pass^k | ever right | unanimous |
|---|---|---|---|---|---|---|---|---|
| routed system | type label | 3 | 71 | 0.76, 0.76, 0.76 | 0.76 [0.66, 0.85] | 0.76 [0.66, 0.85] | 0.76 [0.66, 0.85] | 1.00 [1.00, 1.00] |
| routed system | all labels (exact set) | 3 | 71 | 0.44, 0.41, 0.46 | 0.44 [0.33, 0.54] | 0.32 [0.21, 0.44] | 0.52 [0.41, 0.63] | 0.65 [0.52, 0.76] |
| routed system | component | 3 | 54 | 0.81, 0.81, 0.81 | 0.81 [0.70, 0.91] | 0.81 [0.70, 0.91] | 0.81 [0.70, 0.91] | 1.00 [1.00, 1.00] |
| routed system | duplicate link | 3 | 100 | 0.88, 0.83, 0.87 | 0.86 [0.80, 0.92] | 0.81 [0.73, 0.88] | 0.90 [0.84, 0.96] | 0.91 [0.85, 0.96] |
| stuffed agent | type label | 3 | 71 | 0.73, 0.75, 0.75 | 0.74 [0.65, 0.83] | 0.69 [0.59, 0.79] | 0.79 [0.69, 0.87] | 0.83 [0.75, 0.92] |
| stuffed agent | all labels (exact set) | 3 | 71 | 0.41, 0.42, 0.45 | 0.43 [0.32, 0.53] | 0.31 [0.20, 0.42] | 0.54 [0.42, 0.65] | 0.61 [0.48, 0.72] |
| stuffed agent | component | 3 | 54 | 0.80, 0.78, 0.76 | 0.78 [0.68, 0.88] | 0.69 [0.56, 0.80] | 0.83 [0.72, 0.93] | 0.81 [0.70, 0.91] |
| stuffed agent | duplicate link | 3 | 100 | 0.88, 0.83, 0.87 | 0.86 [0.80, 0.92] | 0.81 [0.73, 0.88] | 0.90 [0.84, 0.96] | 0.91 [0.85, 0.96] |
| full agent | type label | 3 | 71 | 0.75, 0.80, 0.73 | 0.76 [0.66, 0.85] | 0.68 [0.56, 0.79] | 0.85 [0.75, 0.93] | 0.80 [0.70, 0.89] |
| full agent | all labels (exact set) | 3 | 71 | 0.45, 0.49, 0.42 | 0.46 [0.35, 0.56] | 0.34 [0.23, 0.45] | 0.58 [0.46, 0.69] | 0.55 [0.44, 0.66] |
| full agent | component | 3 | 54 | 0.78, 0.80, 0.76 | 0.78 [0.68, 0.88] | 0.72 [0.61, 0.83] | 0.81 [0.72, 0.91] | 0.87 [0.78, 0.96] |
| full agent | duplicate link | 3 | 100 | 0.85, 0.86, 0.88 | 0.86 [0.80, 0.93] | 0.83 [0.76, 0.90] | 0.90 [0.84, 0.95] | 0.93 [0.87, 0.98] |

Silver labels. Each system was run k times on the same issues with the same config; only the model calls were repeated. Cells are point estimates with 95% bootstrap intervals over issues (1,000 resamples). Runs: routed system: `20261002-111057-routed-bb4345`, `20261002-111255-routed-bb4345`, `20261002-113110-routed-bb4345`; stuffed agent: `20261002-115926-e3-stuffed-dde819`, `20261002-115055-e3-stuffed-dde819`, `20261002-115127-e3-stuffed-dde819`; full agent: `20261002-115445-agent-5f73a1`, `20261002-111255-agent-5f73a1`, `20261002-113110-agent-5f73a1`.
