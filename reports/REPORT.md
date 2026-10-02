# triagelab: technical report

An eval-driven GitHub issue-triage system, and what measuring it showed. This report covers the whole project: the problem, the data, the methods, experiments E1 to E8, calibration, consistency, failure analysis, cost, and the limits of every claim. Each number comes from a recorded run and names the file that regenerates it.

## 1. Summary

**The question** was never "can an LLM agent triage issues?" but "when is each part worth its cost?". Five hypotheses were written down before any code.

| | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | Repository-specific skills beat generic instructions. | **Not supported** with a 9B model. | E2: repository skill vs. no skill, +0.008 [−0.030, +0.049] label micro-F1. |
| H2 | Retrieving context through tools beats pasting it into the prompt. | **Not supported.** | E3: a tie on dev at one sixth of the cost; on the CPython test set the tool-using agent is worse on labels, −0.076 [−0.144, −0.013]. |
| H3 | A typed decision with escalation matches the agent on routine decisions, cheaper and faster. | **Partly.** | Type label: yes, at about 2% of the cost. Component: yes on dev, no on test. Latency: no. |
| H4 | The harness transfers to a new repository by swapping the skill. | **The mechanics do; the conclusions do not.** | E8: on `astral-sh/uv` a different system wins, and the cheap system is no better than one model call. |
| H5 | Reported confidences are well calibrated. | **Depends on their source.** | E6: token log-probabilities ECE 0.095; stated confidence is 0.98 for almost every answer. |

**Headline result** (held-out test set, 50 issues per repository, evaluated once, adjudicated labels):

| | CPython: routed | CPython: full agent | uv: routed | uv: full agent |
|---|---|---|---|---|
| Labels (T1), micro-F1 | 0.88 [0.83, 0.92] | 0.80 [0.72, 0.87] | 0.70 [0.60, 0.79] | 0.75 [0.65, 0.85] |
| Component (T3), accuracy | 0.73 [0.60, 0.84] | 0.81 [0.69, 0.92] | 0.56 [0.40, 0.71] | 0.68 [0.53, 0.82] |
| Cost per 1,000 issues | $1.36 | $6.50 | $1.84 | $10.15 |

The whole project cost $14.58 in model calls, of a $150 budget.

## 2. The problem

**Input:** an issue exactly as it was opened: title, body, author association, creation time, repository. Nothing from afterwards.

**Output:** a validated `TriageResult` covering five tasks.

| Task | Reference | Metric |
|---|---|---|
| T1 labels (type, area, topic/OS) | labels applied by people, restricted to a taxonomy | micro-F1, also per group |
| T2 duplicates | duplicate closures that name the original | link F1; Recall@k and MRR for retrieval |
| T3 component | files changed by the fixing pull request | accuracy, top-3 accuracy |
| T4 needs-info | a "needs information" style label | F1 (see section 3: not valid on CPython) |
| T5 triage comment | none; an LLM judge calibrated against a rater | rubric score, judge agreement |

The evaluation is offline and frozen: dataset snapshots, a local index, cached model responses. Every run records its config, code version, dataset hash and cost.

## 3. Data and labels

### Construction (`data/DATASET_CARD.md`)

- **`python/cpython`:** 5,476 issues from 2025-05-19 to 2026-08-18, split by time into train 4,152, dev 100 and test 50, with reserve pools. Dev and test are stratified so rare cases are present, and sampling weights allow natural-rate estimates.
- **`astral-sh/uv`** (transfer): 2,826 issues, split 2,543 / 100 / 50. Its dev split was never evaluated.
- **The evaluation window starts after the judge model's stated training cutoff**, and the agent model was released before it, so neither can have seen the issues.

### Leakage

- 94.7% of CPython issue bodies were edited after creation, and 70% now name the pull request that fixed them (a bot appends a "Linked PRs" section). Every snapshot is rebuilt from GitHub's edit history as of the creation second; none contains the bot's section.
- The retrieval index answers "as of" a time: only earlier issues exist, with the labels and state they had then. The guard is in the server, not the prompt. Even BM25's statistics use only documents that existed at query time.
- Three layers check this: unit tests with a mutation test (its own CI check), a real MCP client test, and, since M8, an audit of finished runs from their traces (`triagelab runs audit`). On the six test runs that use retrieval, 6,478 past issues reached the model and none was from the future.

### Label noise (`reports/gold/`)

Derived ("silver") labels were adjudicated on all dev and test issues in two passes: blind from the issue text, then with the evidence. **The annotator was a model** (Claude Opus 5.5), at the owner's request; every record says so (ADR-0035).

| Silver vs. adjudicated, Cohen's κ | CPython dev (97) | CPython test (50) | uv test (50) |
|---|---|---|---|
| Type label | 0.72 | 0.79 | 0.66 |
| Component | 0.90 | 1.00 | 1.00 |
| Is a duplicate | 1.00 | 1.00 | 1.00 |
| Needs info | **0.00** | **0.00** | 1.00 |

- **T4 is not valid on CPython.** The `pending` label means "awaiting a decision", not "information missing": silver flags 15 dev issues, adjudication none. T4 was removed from the headline (ADR-0036).
- **Cleaner labels changed conclusions.** On silver the agent showed no gain over TF-IDF on type labels; on adjudicated labels it leads by +0.11 [+0.03, +0.19].
- **Who labelled matters more than how many labels there are.** `huggingface/transformers` looked fully labelled, but 3% of its recent issues had a label applied by a triager; the rest came from issue forms. That is why CPython is the primary repository (ADR-0011), and why uv's results carry a caveat (section 8).

## 4. Methods

- **Model access:** our own client over LiteLLM, with structured output, a content-addressed disk cache, cost accounting from a reviewed price table, and a budget check that runs before every call.
- **Models:** Qwen3.5-9B (agent and decision calls), Qwen3.5-27B (size comparison), GPT-6 Luna (judge and failure tagger; a different family). Provider and numeric precision are pinned per route.
- **Baselines:** majority class; TF-IDF with logistic regression; one LLM call without tools.
- **Retrieval:** our BM25, a local embedding model (arctic-embed-s), and reciprocal rank fusion.
- **`repo-intel` MCP server:** five read-only tools (similar issues, one issue, code search on a frozen checkout, code owners, components), built with the official SDK.
- **Agent harness:** written by hand. A loop with native tool calling, a validated final-answer tool, per-issue budgets with forced answers, context compaction, a repeat guard, and JSONL plus OpenTelemetry traces.
- **Agent Skills:** the open format, with progressive disclosure implemented by us: names and descriptions first, the body on `load_skill`, reference files on demand.
- **Decision layer:** a protocol for single typed questions. Backends: an LLM with stated confidence, an LLM with confidence from first-token log-probabilities, and an embedding classifier. Jev was not available (`jev_access: no`); it would be one more backend.
- **Cascade:** a confidence threshold τ chosen on dev only, with 2-fold cross-fitting; evaluated offline by recombining stored runs, and implemented live (`system.kind: cascade`).
- **Statistics:** 95% bootstrap intervals over issues for every metric, and a paired bootstrap for every comparison. A difference is called real only if its interval excludes 0.

## 5. Experiments

Unless stated otherwise: CPython dev split, adjudicated labels (n = 97), `reports/experiments/` and `reports/results/`.

### E1: do cheap baselines already solve it?

| system (silver labels) | labels micro-F1 | component accuracy |
|---|---|---|
| majority class | 0.40 [0.32, 0.49] | 0.26 |
| TF-IDF + logistic regression | 0.71 [0.64, 0.77] | 0.65 |
| one LLM call | 0.59 [0.54, 0.64] | 0.69 |
| one LLM call, thinking on | 0.69 [0.63, 0.74] | 0.76 |

A 9B model answering directly is worse than TF-IDF at labelling (−0.12 [−0.19, −0.06]). Letting it reason first closes the gap. The bar for everything after this is a free classifier.

### Retrieval on its own (M3, `reports/retrieval/`)

On 152 reachable duplicates, each searched as of its creation time: BM25 MRR 0.47, dense 0.62, hybrid 0.61. Dense beats BM25 by +0.14 MRR [+0.08, +0.21]; fusion adds nothing over dense. A quarter of originals predate the index, so Recall@10 over all duplicates tops out at 0.57.

### E2: do skills help? (H1)

No skill variant differs from no skill on any metric: generic, hand-written, or generated automatically. Left to itself the 9B model loads a skill on 1–2% of issues; forcing the first call to `load_skill` did not help either. The 27B model loads it unprompted on 72% of issues.

### E3: tools vs. stuffing (H2)

Pasting the 8 most similar earlier issues into the prompt matches the tool-using agent on every dev metric (labels −0.009 [−0.059, +0.037]) at one sixth of the cost. The agent's lead over a single call comes from seeing labelled neighbours, not from multi-step tool use.

### E4: is multi-agent worth it?

A planner with two specialised subagents and a synthesizer halves the cost and slightly hurts labels (−0.042 [−0.081, +0.001]) and duplicate finding. Not worth it here.

### E5: model size

The 27B model on the identical harness is the only arm that beats the reference: labels +0.070 [+0.031, +0.110], at 3.6 times the cost. On silver labels the gain is +0.010 and not significant; labels adjudicated by an LLM may favour a stronger model.

### E6: decision backends (H3, H5, `reports/calibration/`)

| type label | accuracy | mean confidence | ECE | $ per 1,000 |
|---|---|---|---|---|
| LLM, confidence from log-probabilities | 0.87 [0.79, 0.93] | 0.87 | 0.095 | $0.15 |
| LLM, stated confidence | 0.81 [0.73, 0.89] | 0.98 | 0.162 | $0.16 |
| embedding classifier | 0.75 [0.67, 0.84] | 0.73 | 0.131 | $0 |
| full agent | 0.79 [0.71, 0.88] | 0.89 | 0.103 | $6.73 |

One call matches or beats the agent on both routine decisions (component: 0.84 for both) at about 2% of the cost.

### E7: cascade (`reports/cascade/`)

- **Issue level:** the stuffed agent as the cheap tier, its own confidence as the gate. τ = 0.70 escalates 4% of issues and matches the full agent at $1.38 per 1,000 against $6.84. Cross-fitted, 2% escalate: the cheap tier is already close, so there is little to escalate.
- **Live:** the implemented cascade reproduces the offline recombination exactly on dev (the same 6 of 100 issues escalate under the final configs, and all 100 answers are identical).

### E8 and the test set (`reports/test-eval/RESULTS.md`)

The final configs were frozen in git (configs, a hash of the code and skills, the dataset), an analysis plan was committed, and each config ran once in an approval-protected CI workflow.

- **CPython:** the routed system beats the full agent on labels (+0.080 [+0.019, +0.148]) and both baselines, at 21% of the agent's cost. Its component accuracy is 0.73 against the agent's 0.81; the difference is inconclusive (−0.083 [−0.196, +0.022]) but it is below the dev interval.
- **uv:** all five configs ran with only a profile and a skill swapped, after one fix. The full agent leads; the routed system beats the uv-trained classifier on labels (+0.318 [+0.144, +0.489]) but not a single model call (+0.025 [−0.045, +0.102]).

## 6. Calibration (H5)

- **Stated confidence is uninformative.** The model says about 0.98 whether it is right or wrong.
- **Log-probabilities are the best LLM signal:** calibrated (ECE 0.095) and discriminating (lowest area under the risk–coverage curve).
- **Short issues break every source on the type decision** (ECE 0.27–0.44, n = 9): a slice to watch, not an estimate.
- Reliability diagrams and risk–coverage curves: `reports/figures/e6-*`.

## 7. Consistency (`reports/consistency/dev-gold.md`)

Each final config was run three times on dev; only the model calls were repeated.

| decision | system | accuracy | right in all 3 runs | same answer in all 3 |
|---|---|---|---|---|
| type label | routed (typed backend) | 0.87 | 0.87 | 0.99 |
| type label | stuffed agent | 0.81 | 0.73 | 0.80 |
| type label | full agent | 0.77 | 0.67 | 0.79 |
| component | routed (typed backend) | 0.84 | 0.84 | 1.00 |
| component | full agent | 0.83 | 0.77 | 0.88 |
| all labels, exact set | full agent | 0.53 | 0.36 | 0.56 |

A one-token decision with thinking off is repeatable; an agent is not. Accuracy from a single run overstates what a user can rely on by 6 to 17 points.

## 8. Where the systems fail

### Failure taxonomy (`docs/FAILURE_TAXONOMY.md`)

Sixty agent failures were open-coded and merged into ten categories; a failure can have more than one. An LLM tagger reproduces six of them at κ ≥ 0.6; the other four are marked unvalidated. The seven largest:

| category | failures (of 60) |
|---|---|
| topic/OS labels added for a mere mention | 28 |
| code-location confusion (the symptom's location, not the fix's) | 24 |
| type-label error (mostly crash vs. bug) | 17 |
| repository guidance unused | 16 |
| correct evidence ignored | 10 |
| duplicate retrieval error | 9 |
| ground-truth noise | 9 |

Most failures are label judgement, not retrieval. The rules that would prevent them are in the skill the model does not read.

### On uv: the issues that needed triage

Maintainers there mostly step in to re-label a report as a `question`. The LLM systems predict `question` 2 or 3 times in 50 (the reference has 8). They get the type right on 31–32 of the 34 issues nobody re-labelled, and on 5–7 of the 16 a maintainer triaged. A high overall score can come from agreeing with the reporter. (n = 16: a pattern, not a rate.)

### Triage comments (T5, `reports/judge/`)

The judge agrees with the rater moderately on correctness (quadratic-weighted κ 0.57) and actionability (0.50), and not on tone (0.17), so tone is not reported. On dev:

| system | correctness (1–4) | actionability (1–4) |
|---|---|---|
| one LLM call | 3.22 [3.06, 3.38] | 1.90 [1.74, 2.08] |
| stuffed agent (also the routed system's comment) | 3.10 [2.90, 3.29] | 1.42 [1.26, 1.59] |
| full agent | 2.86 [2.64, 3.06] | 1.36 [1.21, 1.53] |

Comments are mostly correct and rarely actionable, and more machinery does not improve them. The judge scores actionability about half a point lower than the rater did, so the level is conservative; the ordering is the finding.

## 9. The iteration story (`docs/ITERATIONS.md`)

Eight iterations, each one change, a paired delta and a decision.

| # | change | effect | kept |
|---|---|---|---|
| 1 | list label strings exactly as they must be written | area F1 +0.475 | yes |
| 2 | let the 9B model think before answering | labels +0.10 [+0.06, +0.14] | yes |
| 3 | a required top-3 component field in the schema | top-3 +0.15, top-1 +0.07 | yes |
| 4 | force the skill into context | nothing measurable | reverted |
| 5 | a mechanical repeat guard on tool calls | cost −9% at equal accuracy | yes |
| 6 | tools return the component that owns each file | area labels +0.060 | yes |
| 7 | a stricter answer schema | worse | reverted |
| 8 | drop topic/OS labels below 0.95 confidence | labels +0.056 [+0.037, +0.077] | yes |

The pattern across them: with a small model, changing what the harness computes and filters works; telling the model how to behave does not.

A regression gate (`eval.yml`) now protects the result: a fixed 50-issue subset, the real API behind an approval, a blessed baseline, and failure when a headline metric, the cost or the fallback rate moves beyond a threshold.

## 10. Cost

| | per 1,000 issues | note |
|---|---|---|
| embedding or TF-IDF classifier | $0 | local CPU |
| one typed LLM decision | $0.15 | thinking off |
| one LLM call, thinking on | $0.28 | |
| stuffed agent | $1.20 | 14% of its calls hit the output limit |
| routed system | $1.36 | stuffed agent + two typed decisions |
| full agent | $6.50 | about 8 tool calls per issue |
| full agent, 27B | $24.30 | dev |

- **Total spend: $14.58** (9B: $10.13; 27B: $3.83; judge and tagger: $0.61), including every failed and repeated run.
- **Cheaper was not faster.** The routed system's p50 latency on test was 170 s against the agent's 107 s, because its base agent often reasons until the output cap.
- Prices are list prices from a reviewed table, not the provider's invoice.

## 11. Limitations and threats to validity

- **Sample size.** Dev has 100 issues and each test set 50. Most intervals are ±0.10 or wider, and several comparisons are inconclusive for that reason alone.
- **The reference labels come from a model.** They may favour answers shaped like an LLM's, flattering LLM systems against the classifier and stronger models against weaker ones. A human spot-check was recommended and not done.
- **The perfect type score on CPython test** (50 of 50) is an easier sample, not a leak; it supports "above 0.94", and against maintainers' labels the score is 0.91 [0.80, 0.98].
- **Dev optimism.** One decision chosen on dev (routing the component to a typed backend) did not hold on test.
- **One small model family.** H1 in particular may not hold for a model that actually reads skills.
- **T4 is unmeasured on CPython**, and T2 has 3 to 12 positives per split.
- **Latency** was measured once per system, on shared providers.
- **Session 1 of the test evaluation was frozen twice**, because the code hash depended on the platform; nothing had been scored (ADR-0046).
- **One comparison was wrong and was withdrawn:** "runaway reasoning on uv" compared two different systems (ADR-0047).
- **Code search uses one frozen checkout**, taken before the evaluation window; it does not move with the issue's date.

## 12. Reproducing

```bash
git clone https://github.com/ish-codes-magic/triage-bench && cd triage-bench
uv sync
uv run triagelab reproduce
```

This downloads the two public test packs, checks their pinned SHA-256, re-scores the committed predictions against the committed labels, and compares the tables with the committed ones byte for byte. No API key is needed. It reproduces the scoring, not the model calls: those were made once, in CI, under a frozen session.

Everything else is one command per artefact: `triagelab results`, `deltas`, `calibration`, `cascade`, `consistency`, `runs audit`, `demo`, `site build`. Decisions are in `docs/DECISIONS.md` (53 records), and the per-milestone notes in `docs/learning/`.
