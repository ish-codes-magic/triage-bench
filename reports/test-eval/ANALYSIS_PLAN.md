# Test-set analysis plan (session 1)

Written on 2026-10-02, after both sessions were frozen (`682f46a`) and dispatched, and **before any test result existed**. It fixes what will be computed and how it will be read, so the analysis can't be shaped by the numbers. Anything done beyond this plan is labelled "exploratory" in the report.

## What is scored

- **Runs:** the five configs of each session, exactly as produced by `test-eval.yml`. An issue that ends as a fallback or an error is scored as a wrong answer, never dropped.
- **Labels:** the headline uses the adjudicated ("gold") labels of the 50 test issues per repository (annotator `claude-opus-5-5`, ADR-0035; labelled after the freeze). Silver numbers are reported next to them, with Cohen's κ between silver and gold per task.
- **Metrics:** T1 micro-F1 (all labels, type only, area only), T2 link F1, T3 accuracy and top-3 accuracy, cost per issue, p50 latency, fallback rate.
- **Uncertainty:** 95% bootstrap intervals over issues for every number, and a paired bootstrap for every comparison.

## Comparisons (B − A, per repository)

| | A | B | Question |
|---|---|---|---|
| 1 | full agent | routed system | Does the cheap system keep the agent's quality? (H3, E7) |
| 2 | stuffed agent | routed system | What do the two typed decisions add? |
| 3 | TF-IDF classifier | routed system | Does the system beat the cheap trained baseline? (E1) |
| 4 | single-shot LLM | routed system | Does it beat one plain model call? (E1) |
| 5 | stuffed agent | full agent | Tools vs. stuffing on unseen issues (H2, E3) |

A difference is called an improvement or a regression only if its 95% interval excludes 0. With n = 50 most intervals will be wide: an interval that includes 0 is reported as **inconclusive**, not as "no difference" and not as support.

## How each hypothesis is read

- **H3 (routine decisions, cheaply):** supported on test if comparison 1 shows no regression on T1 type and T3, and the routed system costs less per issue. "No regression" with a wide interval is stated as such, with the interval.
- **H4 (transfer by swapping the skill and profile):** three separate answers, none of them a single pass/fail.
  1. *Did the harness run unchanged?* Already known: no. One piece of CPython wording had to move into the profile (ADR-0047). Reported as a correction to the claim.
  2. *Does the order of systems on CPython test repeat on uv test?* Descriptive.
  3. *Does the routed system beat the uv-trained classifier and the single-shot LLM on T1 and T3?* Comparisons 3 and 4 on uv, read by the rule above.

  Absolute levels are **not** compared across repositories: the taxonomies, base rates and label provenance differ.
- **Dev vs. test (CPython):** the dev numbers of the same configs are shown next to the test numbers. A test number inside the dev interval is "as expected"; a drop outside it is reported as optimism from iterating on dev.

## uv caveats, fixed in advance

- **Label provenance:** most uv kind labels come from the form the reporter picked, so silver type labels are weak. Type-label F1 is also reported on the test issues whose labels a maintainer applied. That subset is small (roughly a quarter to a third of 50), so it's descriptive only.
- **T2 and T4:** the adjudicated uv test set has 3 duplicates and 6 needs-info issues; CPython has 6 and 0. Metrics on so few positives are reported with their intervals and not interpreted. T4 stays out of the headline (ADR-0036).
- **Runaway reasoning:** the share of model calls that hit the output limit is reported for both repositories (it was about 9% on uv train issues and 0.3% on CPython dev).

## What would justify session 2

Only a run that could not complete (infrastructure, provider outage), or a bug that makes a run's predictions meaningless independent of their score. An unfavourable result is not a reason. If session 2 is ever opened, the reason is written into its `note` and both sessions are reported.
