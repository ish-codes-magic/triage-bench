# M9: Making the results checkable by a stranger

**What M9 built:**
- `triagelab reproduce`: the headline tables rebuilt from public inputs in three commands, and checked in CI on a fresh runner.
- A consistency study (pass^k) on dev, and per-system scores for the triage comments (T5).
- A live cascade, and a demo GIF drawn from its traces.
- A static results site assembled from the committed reports.
- The technical report, a blog draft, READMEs for the MCP server and the skills.
- `release.yml` and `pages.yml`, both opt-in for anything outward-facing.

**Why it matters:**
- A result nobody else can regenerate is a claim. The work of this milestone is turning claims into things with a command next to them.
- Two measurements were still missing from the plan (consistency and T5). Both changed the story a little, which is the argument for doing them last instead of never.

```
public pack (sha256 pinned) ─┐
committed predictions ───────┼─► triagelab reproduce ─► tables == committed tables?  (CI, every PR)
committed labels ────────────┘
committed reports ─► triagelab site build ─► ./site ─► pages.yml (publish: opt-in)
stored traces ─► triagelab demo ─► text + GIF
tag v* ─► release.yml ─► wheel + image + provenance ─► PyPI / GHCR (each opt-in)
```

---

## 1. Concepts, and where they live

| Concept | What it is | Where |
|---|---|---|
| **Reproducibility of scoring** | Re-deriving the reported numbers from fixed inputs, without re-running the model. | `eval/reproduce.py`: `reproduce`, `ensure_dataset`, `restore_runs` |
| **Pinned artefact** | A download that is only used if its SHA-256 matches a value in git. | `reports/test-eval/reproduce.yaml`; `eval/reproduce.py`: `ensure_dataset` |
| **Golden-file check** | Comparing regenerated output with a committed file, byte for byte. | `eval/reproduce.py`: `Outcome.matches`; the `reproduce` job in `ci.yml` |
| **Consistency (pass^k)** | The share of issues a system gets right in all k runs. | `eval/consistency.py`: `pass_k`, `accuracy`, `ever_right`, `unanimous` |
| **Sample index** | A number in the cache key that makes a repeat run call the model again. | `llm_client.py`: `LLMRequest.sample`, `LLMClient(sample=...)`; `eval --sample` |
| **Live cascade** | Routing one issue at a time by a threshold chosen offline. | `decisions/live_cascade.py`: `CascadeTriager`, `Routing` |
| **Offline/live equivalence** | The live system must route exactly as the offline analysis assumed. | `decisions/cascade.py`: `self_signal` (shared); `tests/test_live_cascade.py` |
| **Figures from data** | A demo drawn from traces instead of recorded from a screen. | `demo.py`: `storyboard`, `render_gif` |
| **LLM judge applied to systems** | Scoring every comment of a run with a judge whose agreement is known. | `eval/judge.py`: `judge_run`, `render_system_scores`, `UNVALIDATED` |
| **Static site assembly** | Pages built from existing Markdown, with links and images rewritten. | `site.py`: `build_site`, `_Linker` |
| **Build provenance** | A signed statement of which workflow built an artefact, from which commit. | `release.yml`: `attest-build-provenance` |
| **Trusted publishing** | PyPI accepts an upload because it can verify the workflow (OIDC), with no stored token. | `release.yml`: the `pypi` job |
| **Opt-in publishing** | Outward-facing steps gated by a repository variable the owner sets. | `release.yml`, `pages.yml`: `vars.*_ENABLED` |

## 2. What we verified before writing the workflows

- **Action versions and SHAs** were read from each action's latest release through the GitHub API on 2026-10-02 (`configure-pages` v6.0.0, `upload-pages-artifact` v5.0.0, `deploy-pages` v5.0.1, `attest-build-provenance` v4.2.2, `gh-action-pypi-publish` v1.14.2, the Docker actions), and pinned by commit.
- **`upload-pages-artifact` inputs** (`path`, `retention-days`) were read from its `action.yml`. It skips hidden files by default; Pages deployed from an artifact does not run Jekyll, so that is fine.
- **Release assets of a public repository** download without authentication from `/releases/download/<tag>/<file>`: confirmed from a clean clone.
- **The names `triagelab` and `repo-intel`** were free on PyPI on that date.
- **Not verified locally:** the Docker image (no daemon on this machine). The pull-request job in `release.yml` builds and starts it instead; it passed.

## 3. Results added in this milestone

**Consistency** (dev, three runs of each final config, `reports/consistency/dev-gold.md`):

| decision | system | accuracy | pass^3 | unanimous |
|---|---|---|---|---|
| type label | routed (typed backend) | 0.87 | 0.87 | 0.99 |
| type label | full agent | 0.77 | 0.67 | 0.79 |
| component | routed (typed backend) | 0.84 | 0.84 | 1.00 |
| component | full agent | 0.83 | 0.77 | 0.88 |

**T5** (dev, `reports/judge/dev-systems.md`): correctness 2.86–3.22 of 4, actionability 1.36–1.90. One plain model call writes better comments than the full agent.

**Live cascade:** identical to the offline recombination on all 100 dev issues; 6 escalate.

## 4. Common pitfalls (each one happened here)

- **Reproducing the wrong thing.** "Reproduce with cached responses" suggests replaying model calls. The test runs' calls were made in CI and never cached locally, and re-making them would be a second look at the test set. Say precisely what is reproduced: the scoring.
- **A table that isn't deterministic.** The golden-file check only works because the bootstrap is seeded and the output has no timestamps. Check that first (regenerate twice and compare) before building a gate on it.
- **A repeat run that replaces the result.** A newer run of the same config would have taken the original's place in the results table. Repeats are marked and filtered.
- **Changing cache keys by accident.** Adding the sample index could have invalidated every cached response. A $0 replay of an old run is the test that it didn't.
- **Two components writing one file.** The cascade's two agents would have shared a trace file and a server log. Each tier gets its own folder.
- **A demo that only shows the good path.** The chosen issue shows a tier running out of tokens and an agent forced to answer. It was picked because escalation changed the outcome, not because it looked clean.
- **Shell quoting eating a file.** Multi-line text with escapes, passed through a heredoc, was mangled several times. Write files with a file tool; keep the shell for commands.
- **A missing measurement hiding in plain sight.** T5 had a calibrated judge and no per-system score. The gap only showed when the report needed a number for every task.
- **Forgetting an earlier decision.** An exercise stub was added although the owner had decided against stubs. Decisions that live outside the repository's instructions get lost, so they need writing down where the next session will read them.

## 5. How an interviewer might probe this

- *"What exactly do your three commands reproduce?"* The scoring of recorded predictions against committed labels on a public dataset. Not the model's behaviour. Say why: one-time evaluation.
- *"Accuracy is 0.77. How often is it right?"* In all of three runs: 0.67. Explain pass^k, and why a typed call with thinking off is at 0.99 agreement.
- *"How do you know the live cascade matches your offline analysis?"* They share the signal function, a test pins the boundary and the fallback case, and a dev run was compared issue by issue.
- *"Why is your demo trustworthy?"* It is generated from the run's traces by a command, and it includes the failures.
- *"How would you publish this safely?"* Provenance attestations, trusted publishing with no stored token, least-privilege permissions per job, and an explicit switch for each destination.
- *"Why not MkDocs?"* Six pages, already in Markdown, generated by commands. The only hard part is link rewriting, which is one small class and is tested.

## 6. Try it yourself (optional)

1. **Break reproducibility.** Change one digit in `reports/results/test-gold.md` and run `uv run triagelab reproduce`. Then find the CI job that would have caught it.
2. **Tamper with the pin.** In a fresh clone (so your own `data/` folder is untouched), change one character of a `pack_sha256` in `reports/test-eval/reproduce.yaml` and run `uv run triagelab reproduce`. Read `ensure_dataset` to see why nothing was unpacked.
3. **Compute pass^k by hand.** For four issues with correctness rows `TTT`, `TTF`, `FTF`, `FFF`, work out accuracy, pass^3 and "ever right", then check `tests/test_consistency.py`.
4. **Move the threshold.** Copy `configs/experiments/cascade.yaml`, set `tau: 0.95`, and run it on dev (it is free from the cache). How many issues escalate, and does accuracy change?
5. **Render another issue.** `uv run triagelab demo runs/<cascade run> "<an issue that did not escalate>"` and compare the two stories.

## 7. Self-check questions

1. Why does `reproduce` compare whole files instead of checking that each metric is "close enough"?
2. pass^k can only go down as k grows. What does that imply about reporting it at k = 3?
3. The routed system's type label is unanimous on 99% of issues and the full agent's on 79%. Give two reasons from how each is produced.
4. `release.yml` requests `id-token: write` in three jobs. What is it for in each?
5. The site has no content of its own apart from one page. Why is that a feature?

### Answers

1. Because a tolerance hides real changes. The scoring is deterministic (seeded bootstrap, no timestamps), so any difference means the code, the labels or the predictions changed, and someone should look at it.
2. That 0.67 is an upper bound on what a user would see over more runs. The number is only meaningful with its k, and a larger k would be more honest and cost more.
3. The typed backend makes one call with thinking off and reads the answer from the first token's distribution, so there is almost nothing to vary. The agent takes several steps, each with sampled reasoning and its own choice of tool calls, and differences compound.
4. In `package` and `image`, to sign the build provenance attestation. In `pypi`, to prove the workflow's identity to PyPI for trusted publishing. None of them stores a secret.
5. It cannot drift: every table and figure on it is a file generated by a command, and a broken link fails the build. Nothing is typed twice.
