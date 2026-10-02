# M8: A second repository, and the test set, once

**What M8 built:**
- A second repository (`astral-sh/uv`) that needs only a profile and a skill.
- A way to evaluate the held-out test split **once**, with that "once" enforced by code:
  - a frozen *session* file committed before any test issue is scored;
  - a test pack and an approval-protected CI workflow that runs it;
  - an analysis plan, also committed first.
- A leak audit that works on finished runs.
- The final results on both repositories: `reports/test-eval/RESULTS.md`.

**Why it matters:**
- Every number before M8 was measured on the split the system was tuned on. Dev numbers are optimistic by construction, and only a split nobody looked at can say by how much.
- "We only ran the test set once" is a claim. This milestone turns it into something a stranger can check in git.

```
freeze (local)                      evaluate (CI)                          analyse (local)
configs + hash(src, skills,   ──►   test-eval.yml, owner approves    ──►   import records + audit log
configs) + dataset hash             refuses: changed code, unknown         score against gold
= session-1.yaml, committed         config, second run, third session      planned comparisons only
analysis plan, committed            uploads runs + audit log               leak audit of the traces
```

---

## 1. Concepts, and where they live

| Concept | What it is | Where |
|---|---|---|
| **Held-out test set** | A split used for one final measurement, never for a decision. | `data/splits.py`; rules in AGENTS.md §7.4 |
| **Frozen session** | A committed file that pins the configs, a hash of the code, skills and configs, and the dataset hash. | `eval/test_session.py`: `freeze`, `TestSession` |
| **Authorization** | A test run is refused unless its config is in the session, nothing changed since the freeze, it covers the whole split, and it hasn't run before. | `eval/test_session.py`: `authorize`; `eval/runner.py`: `run_eval(session=...)` |
| **Code hash** | One hash over every file under `src/triagelab`, `skills` and `configs`: line endings normalised, files in an order that is the same on every platform. | `eval/test_session.py`: `code_hash` |
| **Deep fingerprint** | A routed config's fingerprint also covers the configs it is built from. | `eval/test_session.py`: `deep_fingerprint` |
| **Audit log** | One line per start and completion of a test run, committed with the results. | `eval/test_session.py`: `record`, `audit` |
| **Test pack** | The dataset *with* the test period, published only after the freeze, unpacked only by the test workflow. | `data/evalpack.py`: `build_pack(include_test=True)`, `extract_pack(allow_test=True)` |
| **Pre-registration** | Writing down the comparisons and how they will be read before seeing results. | `reports/test-eval/ANALYSIS_PLAN.md` |
| **Transfer** | Running the same harness on a new repository with only data-like artefacts swapped. | `configs/repos/astral-sh__uv.yaml`, `skills/triage-uv/`, `configs/experiments/uv/` |
| **Repo wording in the profile** | Sentences about one repository's labels belong to its profile, not to shared prompt code. | `data/profile.py`: `PromptWording`; `prompting.py`: `vocabulary` |
| **Label provenance** | Who applied a label (author, maintainer, bot), which decides whether it is evidence of triage. | `data/ground_truth.py`: `human_triaged`; `data/DATASET_CARD.md` |
| **Context audit** | Checking, from a run's traces, that every past issue the model saw was visible at the time. | `eval/context_audit.py`: `audit_run`; `triagelab runs audit` |
| **Zero-failure bound** | What a perfect score on n items supports: a failure rate below 1 − 0.05^(1/n), about 3/n. | `eval/bootstrap.py`: `zero_failure_bound` |

## 2. What we verified before coding

- **GitHub Actions dispatch:** `workflow_dispatch` only starts a workflow file that exists on the default branch, even when you dispatch it against another ref. The workflow reached `main` through its own small PR (#8) and then ran against the M8 branch.
- **Environments:** a job with `environment: eval` waits for a required reviewer; the secret is only available after approval. Concurrency at workflow level queues a second run behind the first.
- **uv's labels:** the same label-provenance scan as for CPython, before collecting anything. 188 of 261 labels in the window were applied by the issue's author through an issue form; 26–32% of issues were triaged by a maintainer (ADR-0045).

## 3. Results (test split, adjudicated labels)

Full write-up: [`reports/test-eval/RESULTS.md`](../../reports/test-eval/RESULTS.md). The short version:

| | CPython: routed | CPython: full agent | uv: routed | uv: full agent |
|---|---|---|---|---|
| T1 labels, micro-F1 | 0.88 [0.83, 0.92] | 0.80 [0.72, 0.87] | 0.70 [0.60, 0.79] | 0.75 [0.65, 0.85] |
| T3 component | 0.73 [0.60, 0.84] | 0.81 [0.69, 0.92] | 0.56 [0.40, 0.71] | 0.68 [0.53, 0.82] |
| Cost per 1,000 | $1.36 | $6.50 | $1.84 | $10.15 |

- **H3** holds for the type label on CPython (routed − agent: +0.122 [+0.040, +0.212], at 21% of the cost). It does not hold for the component, and the routed system is slower, not faster.
- **H2** is not supported: on CPython the full agent is worse on labels than the stuffed agent (−0.076 [−0.144, −0.013]) at 5.4 times the cost.
- **H4:** the harness transfers; the choice of system does not. On uv the routed system is no better than one plain model call.
- **Dev optimism showed up in exactly one place:** the component decision that was chosen on dev (0.84 on dev, 0.73 on test, below the dev interval).

## 4. Common pitfalls (each one happened here)

- **A hash that depends on the machine.** `sorted()` on `Path` objects is case-insensitive on Windows and case-sensitive on Linux. The session was frozen on one and refused on the other. It failed safe, but only a test that runs on both platforms catches it before the run is requested.
- **Testing the function but not the command.** `test-session freeze` had two `--config` options and could not run at all; the unit tests called the function underneath. One test through the CLI would have caught it.
- **Repository rules hiding in shared code.** "Area labels have no prefix" was true for CPython and false for uv. A transfer experiment is partly a test of how much of repository #1 leaked into the harness.
- **Comparing unlike things.** "Runaway reasoning: 9% on uv vs 0.3% on CPython" compared two different systems. Like for like, the rate is 13–14% on both. Check that both sides of a comparison differ in one thing only.
- **A perfect score.** Treat it as a suspected leak first. Here it was an easier sample, but only an audit of the actual runs could say so. And a bootstrap interval of [1.00, 1.00] is not evidence of certainty.
- **Forgetting who labelled.** On uv, most "type" labels are the reporter's own form choice. A system can look accurate by agreeing with the reporter, and still fail on the issues a maintainer had to correct.
- **Re-doing a freeze quietly.** Session 1 had to be frozen twice. What makes that defensible is that nothing had been scored, the diff is one function, and all of it is written down (ADR-0046, "Correction").

## 5. How an interviewer might probe this

- *"How do I know you didn't tune on the test set?"* Show the session file's commit, the analysis plan's commit, and the CI run that came after both. Then show what the tool refuses.
- *"Your test numbers are better than dev on labels. Suspicious?"* Yes, which is why there is an audit. Explain the easier sample (no refactor or security issues) and what the score is against maintainers' labels.
- *"What does n = 50 let you claim?"* Differences of about 0.10 and up. Walk through one bold and one inconclusive row of the comparison table.
- *"Why did the component routing get worse on test?"* It was the one decision selected on dev, from a tie (0.84 vs 0.84). Selecting among near-equal options on a small dev set picks up noise; that is the winner's curse.
- *"Did the system transfer?"* Separate the mechanics (yes, after one fix) from the conclusions (no: a different system wins on uv).
- *"Why is the cheap system slower?"* Its base agent reasons until the output cap on 14% of its calls. Cost and latency are different budgets.

## 6. Try it yourself (optional)

1. **Break the freeze on purpose.** Freeze a session on fixture data (see `tests/test_test_session.py`), change one character in a skill file, and run the config. Read the refusal, then find the line in `authorize` that produced it.
2. **Reproduce the platform bug.** In `code_hash`, replace the sort key with plain `sorted(files)` and run `pytest tests/test_test_session.py`. One test fails on Windows and passes on Linux. Why does that make it dangerous?
3. **Audit a dev run.** `uv run triagelab runs audit runs/<a dev agent run>`. Then edit a copy of its `traces.jsonl` so that one pasted issue carries an extra label, and run the audit function on it.
4. **Derive the rule of three.** Solve (1 − p)^n = 0.05 for p, expand with ln(1 − p) ≈ −p, and compare with `zero_failure_bound(50)`.

## 7. Self-check questions

1. Why does the session pin a hash of the code and skills, and not only the config fingerprints?
2. The test pack is public. Why is that acceptable, and what would make it unacceptable?
3. The routed system scored 1.00 on the type label with a bootstrap interval of [1.00, 1.00]. What may you claim?
4. On uv the LLM systems reach 0.77 type F1 against gold but 0.21–0.29 against maintainer-applied labels. Give the explanation the data supports.
5. Comparison 2 on CPython reads −0.083 [−0.184, +0.000] for the component. What do you conclude?

### Answers

1. Prompts, post-processing and skills live in code and files, not in the config. A fingerprint alone would let someone change a prompt after seeing test results and still "run the same config".
2. Because every decision was frozen and committed first, so nothing can be tuned on it unnoticed. It would be unacceptable before the freeze, or if a later change to the system were evaluated on the same issues and reported as a fresh test result.
3. That on issues like these the error rate is below about 6% with 95% confidence (accuracy above 0.94), that the sample was easier than dev, and that against maintainers' own labels the score is 0.91 [0.80, 0.98]. Not that the system is perfect.
4. Maintainers label few uv issues, and mostly to re-classify a report as a question. The systems almost never predict `question`, so they match gold on 31–32 of the 34 untriaged issues and on 5–7 of the 16 triaged ones. The high overall score is agreement with the reporter's own framing. With n = 16 it is a pattern, not a rate.
5. By the plan's rule it is inconclusive, because the interval reaches 0. It is still the result to worry about: the point estimate is 4 of 48 issues lost, the same sign appears on uv, and the test value is below the dev interval.
