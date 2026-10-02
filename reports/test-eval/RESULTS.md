# Test-set results (M8, session 1)

The one-time evaluation of the final configs on the held-out test split: 50 issues of `python/cpython` and 50 of `astral-sh/uv` (the transfer repository, E8). It follows [`ANALYSIS_PLAN.md`](ANALYSIS_PLAN.md), which was committed before any result existed. Anything beyond that plan is marked **exploratory**.

- **Runs:** `test-eval.yml`, at commit `425937b`, from the frozen session files in this folder. Each config ran once; the audit logs are next to the session files.
- **Labels:** adjudicated ("gold") labels by `claude-opus-5-5`, made after the freeze (ADR-0035). They are a careful model's labels, not a human's.
- **Regenerate:** `triagelab results --split test --labels gold [--name uv -p configs/repos/astral-sh__uv.yaml]` and `triagelab deltas reports/experiments/m8-test-{cpython,uv}.yaml`.
- **Cost of the evaluation:** $1.02 ($0.41 CPython, $0.61 uv).

## 1. Headline

| | CPython: routed | CPython: full agent | uv: routed | uv: full agent |
|---|---|---|---|---|
| T1 labels, micro-F1 | 0.88 [0.83, 0.92] | 0.80 [0.72, 0.87] | 0.70 [0.60, 0.79] | 0.75 [0.65, 0.85] |
| T1 type label | 1.00 (50 of 50) | 0.88 [0.79, 0.96] | 0.78 [0.66, 0.88] | 0.77 [0.65, 0.88] |
| T3 component, accuracy | 0.73 [0.60, 0.84] | 0.81 [0.69, 0.92] | 0.56 [0.40, 0.71] | 0.68 [0.53, 0.82] |
| T3 top-3 | 0.92 [0.83, 0.98] | 0.92 [0.83, 0.98] | 0.90 [0.80, 0.98] | 0.93 [0.84, 1.00] |
| Fallbacks (scored as wrong) | 0 | 2 | 2 | 0 |
| Cost per 1,000 issues | $1.36 | $6.50 | $1.84 | $10.15 |
| p50 latency | 170 s | 107 s | 202 s | 148 s |

Full tables with all five systems: [`reports/results/test-gold.md`](../results/test-gold.md) and [`uv-test-gold.md`](../results/uv-test-gold.md); silver versions next to them.

**In one paragraph:** on CPython the cheap routed system holds up on labels and costs about a fifth of the full agent, but its component routing is worse than on dev and it is slower, not faster. On uv the harness runs with only a profile and a skill swapped, yet the ranking of systems does not carry over: the full agent leads, the routed system is not better than one plain model call, and every LLM system fails on the issues a maintainer actually had to re-label.

## 2. Planned comparisons (paired bootstrap, gold labels, B − A)

Bold = the 95% interval excludes 0. An interval that includes 0 is **inconclusive**, not "no difference".

### python/cpython

| comparison | T1 micro-F1 | T1 type | T3 accuracy |
|---|---|---|---|
| 1. routed − full agent | **+0.080 [+0.019, +0.148]** | **+0.122 [+0.040, +0.212]** | −0.083 [−0.196, +0.022] |
| 2. routed − stuffed agent | +0.004 [+0.000, +0.014] | +0.010 [+0.000, +0.031] | −0.083 [−0.184, +0.000] |
| 3. routed − TF-IDF classifier | **+0.135 [+0.085, +0.190]** | **+0.175 [+0.098, +0.271]** | +0.021 [−0.083, +0.128] |
| 4. routed − single-shot LLM | **+0.149 [+0.072, +0.235]** | **+0.140 [+0.060, +0.240]** | +0.062 [−0.041, +0.170] |
| 5. full agent − stuffed agent | **−0.076 [−0.144, −0.013]** | **−0.112 [−0.206, −0.030]** | +0.000 [−0.083, +0.082] |

### astral-sh/uv

| comparison | T1 micro-F1 | T1 type | T3 accuracy |
|---|---|---|---|
| 1. routed − full agent | −0.057 [−0.138, +0.024] | +0.012 [−0.040, +0.078] | −0.122 [−0.278, +0.030] |
| 2. routed − stuffed agent | +0.020 [−0.025, +0.070] | +0.025 [−0.037, +0.089] | −0.024 [−0.167, +0.128] |
| 3. routed − TF-IDF classifier | **+0.318 [+0.144, +0.489]** | **+0.355 [+0.170, +0.538]** | −0.073 [−0.267, +0.111] |
| 4. routed − single-shot LLM | +0.025 [−0.045, +0.102] | +0.053 [−0.008, +0.127] | −0.122 [−0.250, +0.000] |
| 5. full agent − stuffed agent | +0.077 [−0.004, +0.151] | +0.013 [−0.061, +0.089] | +0.098 [−0.025, +0.243] |

All metrics, and the silver versions: `reports/experiments/m8-test-*-{gold,silver}.md`.

## 3. The hypotheses, read by the plan's rules

### H3: routine decisions, cheaply (comparison 1)

- **Type label: supported on CPython.** The routed system is better than the full agent (+0.122, interval excludes 0) at 21% of the cost. On uv there is no detectable difference (+0.012 [−0.040, +0.078]).
- **Component: not supported.** The point estimates are negative on both repositories (−0.083 and −0.122) and the intervals include 0, so by the plan's rule this is inconclusive. It still matters: on dev the same backend equalled the agent (0.84), and on CPython test the routed system's 0.73 is below its own dev interval [0.77, 0.91]. Comparison 2 shows where it comes from: the typed component backend changed the stuffed agent's own answer on 7 of the 48 scored CPython issues, fixing 1 and breaking 5 (35 correct instead of 39). On uv it changed 13 of 41, fixing 4 and breaking 5.
- **Latency: not supported.** H3 said "a fraction of the cost and latency". Cost: yes. Latency: the routed system was slower than the full agent on both repositories (p50 170 s vs 107 s, and 202 s vs 148 s). Its base, the stuffed agent, runs into the output limit on 14% of its calls (section 5). One run each on a shared provider, so treat the size of the gap as rough.

### H2: tools vs. stuffing (comparison 5)

- **CPython: the full agent is worse on labels** than the stuffed agent (−0.076, interval excludes 0), at 5.4 times the cost. On the type label the gap has two causes: the agent called 5 of 8 crash reports plain bugs, and 2 of its issues were fallbacks. The stuffed agent got all 8 crashes right.
- **uv: inconclusive, leaning the other way** (+0.077 on labels, +0.098 on components).
- H2 is not supported on either repository.

### H4: transfer by swapping the skill and the profile

1. **Did the harness run unchanged?** No. One piece of CPython wording had to move from the shared prompt into the profile (ADR-0047). After that, the same five configs ran on uv with a new profile and skill, and all completed.
2. **Does the order of systems repeat?** No.

   | | best → worst, T1 labels | best → worst, T3 component |
   |---|---|---|
   | CPython | routed 0.88, stuffed 0.87, agent 0.80, classifier 0.74, single-shot 0.73 | agent 0.81, stuffed 0.81, routed 0.73, classifier 0.71, single-shot 0.67 |
   | uv | agent 0.75, routed 0.70, stuffed 0.68, single-shot 0.67, classifier 0.38 | agent 0.68, single-shot 0.68, classifier 0.63, stuffed 0.59, routed 0.56 |

3. **Does the routed system beat the baselines on uv?**
   - The uv-trained classifier: yes on labels (+0.318, interval excludes 0); inconclusive on components (−0.073).
   - One plain model call: no. Inconclusive on labels (+0.025), and on components the point estimate is −0.122 with an interval that just reaches 0.

**Reading:** the harness transfers mechanically, and LLM systems clearly beat a classifier trained on uv's sparse labels. The *choice of system* made on CPython does not transfer: what was the best cheap configuration there is no better than a single model call on uv.

## 4. Where the systems fail on uv (planned caveat, with an exploratory breakdown)

uv's maintainers label few issues, and when they do it is mostly to say that a report is a `question`.

- **Planned:** type-label F1 against maintainer-applied labels only (16 of 50 issues): 0.21–0.29 for the LLM systems, 0.43 for the classifier, all with very wide intervals.
- **Exploratory:** split by whether a maintainer triaged the issue, and scored against gold:

  | system | type correct, not triaged (34) | type correct, maintainer-triaged (16) |
  |---|---|---|
  | routed | 32 | 7 |
  | full agent | 31 | 7 |
  | single-shot LLM | 31 | 5 |
  | TF-IDF classifier | 10 | 6 |

- Gold has 8 questions among the 50 issues; the LLM systems predict `question` 2 or 3 times and call the rest bugs.
- So the 0.77 type F1 mostly reflects agreeing with the form the reporter picked. On the issues where triage changed something, the systems are right less than half the time. n = 16: a pattern to test on more data, not a measured rate.

## 5. Checks on results that looked too good, or too bad

### The 1.00 on CPython type labels

The routed system's type label matches gold on all 50 test issues (dev: 0.87). That is unusual enough to audit before reporting.

- **Not a leak.** `triagelab runs audit` re-derives, from each run's traces, what the model was allowed to see. Across the six test runs that use retrieval, 6,478 past issues reached the model: none was the issue being triaged, none was newer than it, and none showed labels from after it (7 had their labels cut off by truncation and were not checked). Report: [`context-audit.md`](context-audit.md). No test issue's text names a type label.
- **An easier sample.** The test gold types are only bug (32), feature (10) and crash (8). Dev also had refactor and security issues, which caused about half of this backend's dev errors. No LLM system, the single-shot baseline included, confuses bug with feature on any of the 42 such test issues; their only misses there are 3 issues that got no type label at all.
- **How to read it:** the bootstrap interval of a perfect score is [1.00, 1.00], which says nothing. With 50 of 50 correct, the true accuracy on issues like these is above 0.94 with 95% confidence (1 − 0.05^(1/50)), not 1.00. Against maintainer-applied labels the same predictions score 0.91 [0.80, 0.98] on the 30 issues that have them.
- **Label bias:** blind and final gold labels agree on 49 of 50 type labels, so on this split gold is essentially a careful text-only reading, which is also what the model does. ADR-0035 recorded this threat; here it is visible.

### Dev vs. test on CPython (gold)

| | dev (n = 97) | test (n = 50) | |
|---|---|---|---|
| routed, T1 labels | 0.85 [0.80, 0.89] | 0.88 | as expected |
| routed, T1 type | 0.87 [0.79, 0.93] | 1.00 | above the dev interval (see above) |
| routed, T3 component | 0.84 [0.77, 0.91] | 0.73 | **below the dev interval** |
| full agent, T1 labels | 0.83 [0.78, 0.88] | 0.80 | as expected |
| full agent, T3 component | 0.84 [0.77, 0.91] | 0.81 | as expected |
| stuffed agent, T1 labels | 0.82 [0.78, 0.87] | 0.87 | as expected (upper edge) |
| stuffed agent, T3 component | 0.84 [0.77, 0.92] | 0.81 | as expected |

The one number that fell outside its dev interval is the one decision that was *chosen* on dev: routing the component to the typed backend.

### Output-limit ("runaway reasoning") rates, like for like

| | CPython dev | CPython test | uv test |
|---|---|---|---|
| stuffed agent: calls that hit the 4,000-token output limit | 12.9% (27 of 209) | 14.4% (15 of 104) | 14.4% (22 of 153) |
| full agent | 0.3% (3 of 881) | 1.4% (6 of 431) | 1.0% (5 of 498) |

The plan expected a uv-specific problem (9% vs 0.3%). That compared the stuffed agent on uv with the full agent on CPython. Like for like there is no transfer effect: it is a property of the stuffed configuration on both repositories (ADR-0047, "Correction").

### Label noise on the test splits (silver vs. gold)

| | CPython | uv |
|---|---|---|
| T1 type label, Cohen's κ (n) | 0.79 (30) | 0.66 (16) |
| T3 component, κ (n) | 1.00 (22) | 1.00 (17) |
| T2 is a duplicate, κ (n) | 1.00 (50) | 1.00 (50) |
| T4 needs info, κ (n) | 0.00 (50) | 1.00 (50) |

T2 and T4 have too few positives to interpret (6 and 0 on CPython; 3 and 6 on uv), as the plan said. Details: `reports/gold/test.md` and `reports/gold/uv/test.md`.

## 6. Limits of these numbers

- **n = 50 per repository.** Most intervals are ±0.10 or wider; several comparisons are inconclusive for that reason alone.
- **Gold labels come from a model** (Claude), which may favour answers shaped like an LLM's and flatter the LLM systems against the classifier.
- **One run per config**, at temperature 0 but on a shared provider; consistency across repeated runs (pass^k) has not been measured.
- **Latency** was measured once, in CI, with the runs one after another.
- **Session 1 was re-frozen once** before anything was scored, because of a bug in the session tooling (ADR-0046, "Correction"). No test result influenced any config, prompt or threshold: the frozen trees are identical to the first freeze except for that one function.
