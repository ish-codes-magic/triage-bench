# M6: Iterations, ablations, and a regression gate for an LLM system

**What M6 built:**
- **Taxonomy-driven iterations.** Each is a change, a paired-bootstrap delta, and a failure-category delta (`docs/ITERATIONS.md`).
- **The E2–E5 ablations as config files:**
  - skills;
  - tools vs. stuffing;
  - planner + subagents;
  - model size.
- **A real-API regression gate** (`eval.yml`). It's a CI check that runs the agent for real, compares it with a blessed baseline, and blocks a PR that makes things worse.

**Why it matters:**
- Up to M5 we could *measure* the agent. M6 is where measurement starts *steering* it: every change has to earn its place with a delta and a confidence interval, and the gate keeps later changes from quietly undoing the gains.
- The ablations turn the pitch's hypotheses (H1–H3) into numbers, including the negative ones.

```
failure taxonomy (M5) ─► pick the biggest category ─► change (schema / mechanism) ─► dev run
        ▲                                                                              │
        └── failures tag (LLM tagger) ◄── paired bootstrap vs. previous reference ◄────┘

PR + label run-eval ─► eval.yml (env approval) ─► eval pack ─► 50-issue subset run ($1 cap)
                    ─► gate check vs reports/gate/baseline ─► PR comment + pass/fail
```

---

## 1. Concepts, and where they live

| Concept | What to take away | Code |
|---|---|---|
| **Taxonomy-driven iteration** | Pick the biggest failure category, change one thing aimed at it, and measure both the headline delta *and* whether that category shrank. A metric can hold still while a category moves. | `docs/ITERATIONS.md`, `eval/failure_tagger.py` |
| **Schema over instructions** | For a small model, a *required field* changes behaviour; a sentence in the prompt doesn't. Iteration 3 (`component_top3` required) worked, and iteration 4 (skill forced into context) didn't. Iteration 7 applies it to labels: a required `type_label`, and a `basis` per label that the harness filters on. | `harness/agent.py`: `AgentAnswer`, `LabelGuess` |
| **Do deterministic work in the tool** | Mapping a path to a component is a lookup, not a judgement, so the tool does it (iteration 6), and the model gets the answer instead of a chance to fumble it. | `mcp_server/server.py`: `search_code`, `RepoIntel.component_name` |
| **Planner + workers + synthesizer** | A fixed pipeline of narrow roles is easier to evaluate than a free-form orchestrator. The synthesizer has no retrieval tools, so a failure is either bad findings or bad synthesis, and the trace shows which. | `harness/planner.py`: `run_team`, `Crew`, `Totals` |
| **One loop, many roles** | Workers reuse the same hand-written loop with a different final-answer tool (`submit_findings`), so budgets, validation and tracing come for free. | `harness/loop.py`: `run_loop(submit=...)` |
| **Provider capabilities are config** | Some routes refuse a named `tool_choice`. Forcing then means offering *only* that tool, plus one line of instruction. The flag lives in `LLMConfig`, not in the request, so existing cache keys don't change. | `config.py`: `named_tool_choice`; `loop.py` |
| **Cross-process file lock** | On Windows, append mode isn't atomic across processes, and two parallel runs corrupted the spend ledger. The fix holds an OS lock around a single binary write. | `filelock.py`: `exclusive`; `ledger.py` |
| **Regression gate** | Thresholds on point estimates, with CIs printed for context. A drop that is significant but inside its threshold is a warning, and a candidate with missing issues fails. The baseline is committed, so "compared with what?" is reviewable in git. | `eval/gate.py`: `check`, `bless`, `render` |
| **Fixed subset by stable hash** | The n items with the smallest content hash: reproducible, independent of order, and changed by at most one item when the pool grows. | `gate.py`: `pick_subset` |
| **Eval pack** | CI can't collect the dataset, so it downloads a checksummed pack. Test-period rows are removed *at packing time*, so no workflow can reach them. That's policy as code, not policy as convention. | `data/evalpack.py` |
| **Cost as a gated resource** | Each gate run has a per-run hard cap, at most one run a week unless forced, owner approval through a GitHub Environment, and no cancelling of paid runs. | `.github/workflows/eval.yml` |

## 2. What we verified before coding (§14, 2026-09-30)

- **OpenRouter endpoints for Qwen3.5-27B** (`/api/v1/models/qwen/qwen3.5-27b/endpoints`):
  - six providers; Alibaba's quantization is "unknown", and Novita serves bf16;
  - one-call probes showed that a named `tool_choice` and `required` both return 404 "No endpoints found that support the provided 'tool_choice' value" on Alibaba and Novita;
  - only `auto` (unset) works;
  - the 9B's DeepInfra route accepts named choices (ADR-0039).
- **GitHub Actions:**
  - `actions/cache` latest is v6.1.0 (`55cc834…`), pinned by SHA;
  - `gh pr comment --edit-last --create-if-none` exists in gh 2.92, for the sticky comment;
  - `gh release download --pattern --dir` and `gh run list --workflow --created --json` exist;
  - `actionlint` passes on `eval.yml` and `ci.yml`.
- **Windows file locking:**
  - `msvcrt.locking(fd, LK_LOCK, 1)` locks a byte range and retries for about 10 s before raising;
  - locking byte 0 of a separate `.lock` file serialises writers without touching the data file.

## 3. Results

All on dev, paired against the reference agent, scored on the adjudicated labels (n = 97). Silver results are alongside in the reports. Regenerate with `triagelab deltas reports/experiments/m6-ablations.yaml` and `.../m6-iterations.yaml`.

**Iterations** ([log](../ITERATIONS.md)):

| # | change | labels micro-F1 Δ | category Δ | decision |
|---|---|---|---|---|
| 6 | tools return each file's component | +0.023 (area **+0.060**) | code-location confusion 31 → 23 | kept |
| 7 | required type label + central/incidental basis | −0.031 | failing issues 69 → 75 | reverted |
| 8 | drop topic/OS labels under 0.95 confidence | **+0.056 [+0.037, +0.077]** | topic/OS over-labeling 42 → 8 | kept |

**Ablations on the final harness:**

| arm | labels Δ vs reference | what it says |
|---|---|---|
| E2: no skill / generic / CPython / auto | −0.014 … −0.005, none significant | H1 not supported at 9B |
| E3: top-8 similar issues stuffed, no tools | −0.009 [−0.059, +0.037] at 1/6 the cost | H2 not supported: retrieval matters, tool use doesn't |
| E4: planner + subagents | −0.042 [−0.081, +0.001] at half the cost | multi-agent didn't pay |
| E5: Qwen3.5-27B | **+0.070 [+0.031, +0.110]** at 3.6× the cost | size helps on gold, not on silver (+0.010) |

**Gate:**
- Dry run against itself: PASS, with zero deltas.
- Dry run against the single-shot baseline: FAIL (labels −0.151, components −0.100), exit 1.

## 4. Common pitfalls

- **Comparing across harness versions.** A tool-output change (iteration 6) changes every later request. E5 is paired with a 9B run *on the same harness*, not with M5's reference.
- **Treating a provider failure as a model result.** The first E5 run "failed" 64% of issues because of an API capability, not the model. Infra errors are retried and excluded; they are never scored as wrong answers.
- **A gate that passes on nothing.** A candidate that answered 0 of the baseline's issues had no deltas to fail on, and passed. It took a coverage rule to close that.
- **Content that looks like a comment.** Issue refs contain `#`, so a subset file parser that strips everything after `#` deletes every ref. Comments now start only at the beginning of a line or after whitespace.
- **Staging leaks.** A `git rm` staged for one commit rides along with the next `git commit` that runs after `git add` of other files. Check `git diff --cached --name-only` before every commit.
- **Test data in "reserve" splits.** The eval pack first excluded only `test`; the `test_reserve` pool holds test-period issues too.
- **Shared capacity isn't your capacity.** The 9B route's uptime figures looked normal while OpenRouter's *shared* DeepInfra pool answered most calls with 429. The owner's own provider key (BYOK) fixed it without changing model, route or price (ADR-0041).
- **Replays measure the replay.** Re-running a config whose model answers are all cached is free and exact, but its latency is the replay's. The results table now prints "replay" instead of a misleading number.
- **A post-processing win must be offered to the baselines too.** The confidence floor lifted the agent by +0.056, and the single-shot baseline by +0.06. The fair agent-vs-baseline gap is +0.075, not +0.13.
- **An LLM tagger has its own noise.** Iteration 8 changed no trace, yet some category counts moved by ±4. Read category deltas smaller than that as noise.
- **Tune on dev, then check the tuning.** The floor was picked by looking at dev. Cross-fitting (pick on one half, score on the other) gave the same threshold and the same score, so the choice didn't overfit.

## 5. How an interviewer might probe this

- "Your gate has 50 issues. How do you know a failure isn't noise?" Talk through thresholds vs. CIs, the WARN state, and an A/A run to measure run-to-run noise.
- "Why not run the gate on every PR?" Cost ($0.35 × PRs against a $150 budget), secrets exposure, and flakiness. Cassettes cover every PR for free, and the real-API gate is opt-in.
- "Multi-agent didn't help (or did). Why?" Compare failure categories: did thrashing fall? Did synthesis ignore findings?
- "How do you stop CI from touching the test set?" The pack has no test rows, and unpacking refuses a pack that claims any. A subset can't name issues from another split. The test-eval workflow is separate and audited.
- "What changes when you swap the model provider?" Precision, parameter support, and rate-limit pools. All of these are pinned and recorded, and a capability gap is handled in config.

## 6. Self-check questions

1. Why does the gate fail on a point-estimate drop rather than on a significant drop?
2. Iteration 6 changed a tool's output. Which runs can you still compare with the M5 reference, and which not?
3. What exactly does `named_tool_choice: false` change in the request, and what stays the same?
4. Why is the synthesizer in E4 given no retrieval tools?
5. How does `pick_subset` guarantee that adding one issue to the pool changes the subset by at most one?

---

**Answers**

1. With n=50, a real 5-point drop in micro-F1 often has a CI that crosses zero, so a significance rule would almost never fire. The threshold captures *practical* significance; the printed CI and the WARN state carry the statistical view.
2. Runs on the same tools version: E5 (27B) and the iteration-6 9B reference share tools v2, so they pair. M5's reference (`cf734a`) used tools v1, so it pairs only with the iteration-6 run *as an iteration*, where the tool change is the treatment.
3. On a forced call, the request's `tools` shrinks to the forced tool alone, `tool_choice` is left unset, and a one-line user message names the limit. Non-forced calls are byte-identical to the default, and the flag isn't part of the request, so cache keys don't change.
4. So that its only evidence is the workers' findings. The comparison then isolates "does role separation help", and a failure can be attributed to retrieval (findings) or to reasoning (synthesis).
5. It ranks refs by a hash of the ref alone and takes the n smallest. A new ref either lands in the top n and pushes exactly one ref out, or it doesn't, in which case nothing changes.
