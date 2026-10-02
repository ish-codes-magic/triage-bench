# Architecture Decision Records

Lightweight ADRs: **Context → Decision → Consequences**. Once a decision is logged, it stays unless a *measured* problem forces a change. A superseded ADR is marked, not deleted.

| ADR | Decision | Milestone |
|-----|----------|-----------|
| [0001](#adr-0001-python-tooling-with-uv-ruff-and-pyright-strict) | Python tooling with uv, ruff and pyright strict | M0 |
| [0002](#adr-0002-typed-layered-yaml-configuration) | Typed, layered YAML configuration | M0 |
| [0003](#adr-0003-litellm-behind-our-own-client) | LiteLLM behind our own client | M0 |
| [0004](#adr-0004-sampling-parameters-are-optional-determinism-is-measured) | Sampling parameters are optional; determinism is measured | M0 |
| [0005](#adr-0005-our-own-price-table-and-a-worst-case-budget-check) | Our own price table and a worst-case budget check | M0 |
| [0006](#adr-0006-content-addressed-json-response-cache) | Content-addressed JSON response cache | M0 |
| [0007](#adr-0007-your-turn-exercises-xfail-only-on-notimplementederror) | YOUR TURN exercises xfail only on NotImplementedError | M0 |
| [0008](#adr-0008-ci-pre-commit-in-ci-sha-pinned-actions-two-oses) | CI: pre-commit in CI, SHA-pinned actions, two OSes | M0 |
| [0009](#adr-0009-run-registry-one-immutable-folder-per-run) | Run registry: one immutable folder per run | M0 |
| [0010](#adr-0010-small-open-weight-models-via-openrouter-pinned-per-role) | Small open-weight models via OpenRouter, pinned per role | M0 |
| [0011](#adr-0011-primary-repo-is-pythoncpython-chosen-by-label-provenance) | Primary repo is python/cpython, chosen by label provenance | M1 |
| [0012](#adr-0012-reconstruct-creation-time-text-and-refuse-when-unprovable) | Reconstruct creation-time text, and refuse when unprovable | M1 |
| [0013](#adr-0013-silver-ground-truth-rules-with-provenance) | Silver ground-truth rules, with provenance | M1 |
| [0014](#adr-0014-time-splits-with-stratified-weighted-small-samples) | Time splits with stratified, weighted small samples | M1 |
| [0015](#adr-0015-metric-definitions-subsets-and-bootstrap) | Metric definitions, subsets and bootstrap | M2 |
| [0016](#adr-0016-e1-baselines-and-tf-idf-before-embeddings) | E1 baselines, and TF-IDF before embeddings | M2 |
| [0017](#adr-0017-a-concurrent-resumable-budget-safe-eval-runner) | A concurrent, resumable, budget-safe eval runner | M2 |
| [0018](#adr-0018-branch-protection-and-evals-in-ci) | Branch protection and evals in CI | M2 |
| [0019](#adr-0019-time-aware-retrieval-including-its-statistics) | Time-aware retrieval, including its statistics | M3 |
| [0020](#adr-0020-arctic-embed-s-on-fastembed-with-a-resumable-embedding-store) | arctic-embed-s on fastembed, with a resumable embedding store | M3 |
| [0021](#adr-0021-the-repo-intel-mcp-server) | The repo-intel MCP server | M3 |
| [0022](#adr-0022-frozen-checkout-literal-code-search-and-index-only-history) | Frozen checkout, literal code search, and index-only history | M3 |

---

## ADR-0001: Python tooling with uv, ruff and pyright strict

**Context.**
- The project must be reproducible by a stranger ("3 commands") and typed well enough to be a hiring signal.
- AGENTS.md asks for versions to be pinned.

**Decision.**
- **Dependency management:** uv manages Python 3.12 and the dependencies.
  - Exact versions are pinned in the committed `uv.lock`, not in `pyproject.toml`, which declares lower bounds.
  - CI installs with `uv sync --locked`, which fails if the lock is stale.
- **Linting and formatting:** ruff does both.
- **Type checking:** pyright runs `strict` on `src/` and `standard` on `tests/`.
- **Hooks:** pre-commit calls every tool through `uv run`, so hook versions come from the same lockfile.

**Consequences.**
- Every version has one source of truth. `pyproject.toml` stays installable as a library, which matters later when `repo-intel` is published.
- The trade-off: exact pins live in the lockfile, so reading `pyproject.toml` alone doesn't tell you the installed version.

## ADR-0002: Typed, layered YAML configuration

**Context.**
- Every experiment (E1–E9) must be a config file, and a mistyped key must never silently invalidate an ablation.

**Decision.**
- **Validation:** pydantic models with `extra="forbid"` and `frozen=True` validate the YAML.
- **Layering:** an experiment declares `extends: ../base.yaml` and overrides only what differs, using a recursive `deep_merge` in which dicts merge and everything else replaces.
- **Fingerprint:** the resolved config is fingerprinted with a SHA-256 of its canonical JSON. Paths serialize as POSIX, so the fingerprint is the same on every OS.

**Alternatives.**
- **Hydra / OmegaConf:** powerful, but interpolation and CLI overrides make it hard to see where a value came from.
- **Plain dicts:** no validation at all.

**Consequences.**
- A typo is a load-time error.
- Each experiment file reads as a diff against the baseline.
- Every run records exactly which config produced it.

## ADR-0003: LiteLLM behind our own client

**Context.**
- We need several providers: E5 compares model sizes, and E6 needs a model that returns logprobs, which not every provider offers.
- We also need caching, retries, cost accounting and budgets that we can see and test.

**Decision.**
- **Transport:** LiteLLM is the transport, but only inside one adapter module.
- **The seam:** the rest of the code talks to the `CompletionBackend` protocol in `llm_client.py`.
- **What we keep:** caching, retries, cost and budgets belong to us. LiteLLM's own retries are turned off, and its cost figure is logged only as a cross-check.

**Alternatives.**
- **Provider SDKs directly:** the best fidelity, but one adapter per provider.
- **An agent framework:** ruled out by AGENTS.md, because it hides the loop.

**Pinned behaviour** (verified against litellm 1.103.0 on 2026-09-29):
- `LITELLM_LOCAL_MODEL_COST_MAP=True` and `LITELLM_LOCAL_ANTHROPIC_BETA_HEADERS=True`.
  - By default LiteLLM downloads its model/capability map at import time, so its behaviour could change from one day to the next without a code change.
  - With these set, behaviour is tied to the locked version instead.
- `num_retries=0`. Otherwise the OpenAI path retries twice on its own and hides those retries from our traces.
- `drop_params=False`, so an unsupported parameter raises instead of silently disappearing. `seed` raises for `anthropic/` and `gemini/`.
- `max_tokens` is always sent. If it's omitted, LiteLLM fills in the model's maximum output.

**Consequences.**
- Tests use a fake backend, so they need no network and cost nothing.
- Swapping LiteLLM out touches one file.
- **Known gap to resolve when models are chosen (end of M0/M4):**
  - LiteLLM's *bundled* map lacks `claude-opus-5-5` and `claude-sonnet-5-5`.
  - For Anthropic, LiteLLM uses native structured output only when the map says the model supports it. Otherwise it falls back to a forced tool call, which these models reject with a 400.
  - If we pick an Anthropic 5.x model, register its capabilities explicitly with `litellm.register_model` and test that path.

## ADR-0004: Sampling parameters are optional; determinism is measured

**Context.**
- AGENTS.md §10 asks for temperature 0 and recorded seeds "where the provider supports it".
- As of 2026-09-29, Claude 5.x models reject any temperature except 1.0, OpenAI marks `seed` deprecated and drops temperature on reasoning models, and Gemini 3 recommends leaving temperature at 1.0 (`docs/learning/M0-foundations.md`).

**Decision.**
- `temperature` and `seed` default to `null`, meaning "don't send it". They're set only for models that accept them.
- Determinism is not assumed. It is measured through the k-run consistency study (§12.3).

**Consequences.**
- The configs work on current models.
- Run-to-run variance is a reported number, not a hidden assumption.
- The response cache makes re-runs replay identical outputs, which is what makes CI cassettes possible.

## ADR-0005: Our own price table and a worst-case budget check

**Context.**
- Budgets ($150 total, $5 per run) must be a hard stop.
- LiteLLM's price map is fetched remotely and changes without review.

**Decision.**
- **Price table:** `configs/prices.yaml` is committed, and every entry cites its source URL and verification date. A model with no entry is refused.
- **Before every call:** `BudgetGuard.check` compares the worst case, `prompt_tokens × input_rate + max_tokens × output_rate`, with the remaining budget. That is a true ceiling because output can't exceed `max_tokens`.
- **After every call:** the exact cost is charged, and appended to `runs/spend_ledger.jsonl`, which carries the all-time total.

- **Prompt tokens are bounded, not counted:**
  - The estimate is `UTF-8 bytes + 16 per message + 1,000 overhead`.
  - Byte-level tokenizers never emit more than one token per byte, so this can only over-count (by about 3–4x for English).
  - It needs no tokenizer. That matters because `litellm.token_counter` fails offline on Windows in 1.103.0, whose bundled tiktoken files have CRLF line endings.

**Consequences.**
- One call can never overshoot a cap, because every part of the worst case is an upper bound.
- Costs are reproducible and reviewable.
- **Known simplifications:** Anthropic cache-write premiums and long-context surcharges (>200K/272K tokens) aren't modelled, because triage prompts are far below those thresholds.

## ADR-0006: Content-addressed JSON response cache

**Context.**
- AGENTS.md requires model calls to be cached. We also want CI to replay recorded responses for free.

**Decision.**
- **Storage:** one JSON file per response at `.cache/llm/<k[:2]>/<k>.json`.
- **Key:** `k` is the SHA-256 of the *semantic* request: model, messages, max_tokens, sampling params, response schema, a `sample` index, and a format version.
  - Timeouts and retry settings are excluded, because they don't change the answer.
  - The `sample` index lets the k-run consistency study get k distinct entries.
- **Writes:** each write goes to a temp file first, then `os.replace` moves it into place.

**Alternatives.**
- **SQLite or `diskcache`:** they work, but a binary store can't be diffed or committed as a cassette.

**Consequences.**
- Entries can be inspected by hand, a crash can't leave a half-written entry, and the same files double as CI cassettes.
- A cache hit costs $0 and records what it saved.

## ADR-0007: YOUR TURN exercises xfail only on NotImplementedError

**Context.**
- Each milestone leaves 1–2 stubs, each with a failing test, for the owner to implement. CI must still be green.

**Decision.**
- Tests marked `@pytest.mark.your_turn` are turned, in `tests/conftest.py`, into `xfail(raises=NotImplementedError, strict=False)`.

**Consequences.**
- **While the stub is untouched,** the tests xfail and CI stays green.
- **A wrong implementation** (e.g. an `AssertionError`) fails CI.
- **A correct one** shows as XPASS, and the marker is then removed.
- To see the raw failures: `uv run pytest -m your_turn --runxfail`.

## ADR-0008: CI: pre-commit in CI, SHA-pinned actions, two OSes

**Context.**
- CI/CD is a showcase for this project (§12.8, §15.1). Local and CI checks must never disagree.

**Decision.**
- **Lint job:** runs `pre-commit run --all-files`, the same hooks as a local commit, including `actionlint` on the workflows.
- **Test job:** a matrix of Ubuntu and Windows, because the project is developed on Windows.
- **Setup:** a shared composite action, `setup-env`, installs a pinned uv and runs `uv sync --locked`.
- **Hardening:**
  - actions pinned by commit SHA
  - `permissions: contents: read`
  - `persist-credentials: false`
  - PR runs cancelled when superseded
  - job timeouts
  - Dependabot for both `github-actions` and `uv`

**Consequences.**
- CI has no drift from local checks and no supply-chain surprises from moving tags.
- Dependabot PRs keep the SHAs current.
- Windows adds about a minute of CI time.

## ADR-0009: Run registry: one immutable folder per run

**Context.**
- A result that can't be traced to its code, config and model versions is an anecdote.

**Decision.**
- **Layout:** each run gets `runs/<YYYYMMDD-HHMMSS>-<name>-<fingerprint6>/` with the resolved `config.yaml`, `git_sha`, a `manifest.json` (versions, command, fingerprint) and `cost.json`.
- **Uncommitted code:** is flagged with a `-dirty` SHA suffix.
- **Immutability:** a run folder is never overwritten.

**Consequences.**
- Runs sort by time and are self-describing.
- `triagelab compare` (M2+) can diff any two runs.
- A run made on uncommitted code is visibly marked.

## ADR-0010: Small open-weight models via OpenRouter, pinned per role

**Context.**
- The owner wants **small models**, and has one API key: OpenRouter.
- The leakage rule (§7) requires the data to start after the training cutoff of *every* model evaluated. DeepSeek and Qwen publish **no** training cutoffs.
- OpenRouter load-balances each model across providers that serve it at different precisions (fp4/fp8/bf16) and with different parameter support. For example, only 2 of 6 providers for Qwen3.5-9B return logprobs.

**Decision.**
- **Access:** every model goes through OpenRouter, via LiteLLM's `openrouter/` prefix and `OPENROUTER_API_KEY`.
- **Lineup** (prices in $ per 1M tokens, input/output, verified 2026-09-29):

  | Role | Model @ route | $ in/out | Why |
  |---|---|---|---|
  | agent_model | `qwen/qwen3.5-9b` @ `deepinfra/bf16` | 0.10 / 0.15 | Small, open weights (Apache-2.0); tools + JSON schema at full precision |
  | LLM decision backend (E6) | `qwen/qwen3.5-9b` @ `parasail/bf16` | 0.10 / 0.25 | Same model; this provider returns logprobs (no tools, and decisions don't need them) |
  | judge_model | `openai/gpt-6-luna` @ `openai` | 0.10 / 0.50 | A different family from the agent (limits self-preference), with a **stated** cutoff |
  | small_model slot → E5 comparison | `qwen/qwen3.5-27b` @ `alibaba` | 0.195 / 1.56 | Qwen3.5-4B isn't on OpenRouter, so E5 asks "does 3× bigger help?" within one family (confirmed 2026-09-29) |

- **Cutoff rule for undisclosed cutoffs:**
  - A model can't have trained on data from after its release, so the public release (or OpenRouter listing) date serves as a conservative upper bound.
  - This **excludes** all current DeepSeek models (V4.1-Flash 2026-09-10, V4-Pro 2026-08-13) and the Qwen 3.7/3.8 hosted models. Each would leave only weeks of data.
  - Luna's stated cutoff (2026-05-18) is the binding constraint, so dev/test issues start on or after **2026-05-19**.
- **Pinning:**
  - Every route is sent with OpenRouter's `provider: {only: [...], quantizations: [...], allow_fallbacks: false, require_parameters: true}`.
  - The route is part of the **cache key**, because a different provider or precision can answer differently.
  - It is also part of the **price key**, because providers charge differently.

**Consequences.**
- "The model" is an exact, reproducible artifact per run (weights × precision × provider).
- The trade-off: if a pinned provider is down, calls fail instead of silently degrading (the route uptimes shown were ~99%).
- One key, tiny costs, and more room for full-dev ablations and k-run consistency studies.
- Small models will likely trip the output-validation retries more often. That becomes a measured failure category, not a hidden one.
- Alibaba doesn't disclose the precision for the 27B route.

## ADR-0011: Primary repo is python/cpython, chosen by label provenance

**Context.**
- AGENTS.md suggested `huggingface/transformers`, and a first scan looked fine: every repo showed 100% of issues labelled.
- Counting *who applied each label* told a different story. In the eval window, transformers had human triage labels on **3%** of issues (12 of 365); the rest were issue-template labels the author picked. It also had **0** needs-info labels and 2 duplicates. T1 and T4 would have had no real ground truth.

**Decision.**
- **Primary: `python/cpython`.** In a sample of 400 window issues:
  - 70% had human-applied labels;
  - there was a clean type/area/topic taxonomy;
  - 45 issues were closed as duplicates;
  - 69 had the `pending` (needs-info) label;
  - fixing PRs were linkable through the `gh-<issue>:` title convention.
- **Transfer: `astral-sh/uv`, tentatively.** It supports all four tasks (a `needs-mre` label, 14 duplicates, area labels) in a very different codebase (Rust, packaging). It gets the same provenance check before M8.
- **Selection method:** candidate repos are chosen by the label-provenance analysis, not by label counts.

**Consequences.**
- All four tasks have ground truth on the primary.
- CPython-specific rules (the `pending` label, PR-title links, the directory→component map) live in `configs/repos/python__cpython.yaml`, not in code.
- 95% of CPython bodies are edited after creation. That made reconstruction mandatory (ADR-0012).

## ADR-0012: Reconstruct creation-time text, and refuse when unprovable

**Context.**
- The API returns the *current* title and body.
- On CPython, a bot appends a "Linked PRs" section naming the fix to almost every issue. Reporters also edit their bodies ("EDIT: duplicate of #…").
- Using the current text would leak the answer into the agent's input.

**Decision.**
- **Title:** the earliest `RenamedTitleEvent.previousTitle`.
- **Body:** the oldest `userContentEdits` revision.
  - It must be timestamped at creation, within 60 s.
  - If an issue was edited and that can't be proven, it is **excluded** (`creation_text_unrecoverable`), not guessed.
- **Past issues in the M3 index** always show their creation-time body. Labels and state are replayed strictly before `as_of`.
- **Tests:** leakage tests (their own CI job, "Leakage guard") pin the snapshot's seven fields. They also assert that changing *any* post-creation field of a `RawIssue` leaves the snapshot unchanged, and adding a `RawIssue` field fails a test until it's classified.

**Consequences.**
- The agent sees what a triager saw at the moment the issue was opened.
- **Known limitation:** `author_association` is reported as of collection, not creation (someone may have become a contributor since). The API offers no history, so this is documented in the dataset card.

## ADR-0013: Silver ground-truth rules, with provenance

**Context.**
- Derived labels are noisy. To analyse that noise (silver vs. gold κ, M5), every label must record where it came from.

**Decision** (implemented in `data/ground_truth.py`, restated in the dataset card):
- **T1 (labels):**
  - taxonomy labels present at collection;
  - each tagged `author` (issue form or self-labelled), `triager`, `bot` or `unknown`;
  - plus `human_triaged`, true if a non-author human added or removed a triage label.
- **T2 (duplicates):** evidence is used in this order:
  1. closed with the duplicate reason;
  2. otherwise, the latest still-active "marked as duplicate" event;
  3. otherwise, a "Duplicate of #N" comment from a triage role.

  The original must have a smaller issue number, which means it was created earlier.
- **T3 (component):**
  - comes from the fixing PRs: merged into `main`, and either GitHub-linked or titled `gh-<issue>:`. Backports are excluded.
  - Files map to components using the maintainers' own area-label descriptions.
  - Primary components decide the vote. Tests and docs only decide when a fix touches nothing else, since nearly every fix ships a test.
  - Ties are skipped.
- **T4 (needs-info):** a human applied `pending` at any point.

**Consequences.**
- Every rule has hand-built test cases.
- Label noise can be broken down by source.
- Untriaged issues aren't mistaken for "no label applies".

## ADR-0014: Time splits with stratified, weighted small samples

**Context.**
- The owner chose **100 dev / 50 test** issues, so they can be hand-labelled as gold.
- At natural rates, 50 issues would contain about one duplicate.

**Decision.**
- **Time windows:**
  - train: 2025-05-19 → 2026-05-18, which may predate model cutoffs (approved);
  - dev: 2026-05-19 → 2026-07-18;
  - test: 2026-07-19 → 2026-08-18, ending 6 weeks before collection so labels could settle.
- **Sampling:** within each window, first meet per-task positive minimums, then fill uniformly (seeded).
- **Weights:** each sampled issue stores its post-stratification weight `N_h / n_h`. Weighted metrics estimate natural-rate performance, and both views get reported.
- **Reserves:** unsampled window issues become `dev_reserve` / `test_reserve`. Silver-only trends may use `dev_reserve`; `test_reserve` is never used for tuning.

**Consequences.**
- Every task has positives in both samples.
- Confidence intervals will be wide at n = 50, and they'll be reported honestly.
- The build is deterministic, and its dataset hash is recorded by every run.

## ADR-0015: Metric definitions, subsets and bootstrap

**Context.**
- Samples are small (dev 100, test 50) and stratified.
- Silver labels are incomplete: an untriaged issue has no labels, and an issue fixed without a merged PR has no component.

**Decision.**
- **Metrics are hand-written and registered in one place** (`eval/score.py:METRICS`). Point estimates, bootstrap intervals and paired comparisons all call the same functions.
- **Subsets are part of each metric's definition:**
  - T1 is scored on `human_triaged` issues only;
  - T3 is scored where a gold component exists;
  - T2 and T4 are scored on every issue.
- **T2 scoring:**
  - a duplicate counts only if the *right original* is named (a wrong original counts as both an FP and an FN);
  - `t2_detect_f1` is the looser "was it flagged at all";
  - Recall@k and MRR exist for M3 retrieval.
- **Intervals:**
  - 95% percentile bootstrap over issues, 1,000 resamples, seeded;
  - resamples where a metric is undefined (no positives drawn) are dropped and counted, not scored 0;
  - comparisons use a paired bootstrap on the same resampled issues, and a change is only "significant" if its interval excludes 0.
- **Weighted estimates:** every metric also reports a sampling-weighted natural-rate estimate.

**Consequences.**
- `eval` and `compare` can't disagree about what a metric means.
- Wide intervals are reported honestly instead of hidden.
- Silver T1 numbers carry the known template-label effect: type labels applied by issue forms are partly predictable from the form's headings. That's why type and area F1 are reported separately.

## ADR-0016: E1 baselines, and TF-IDF before embeddings

**Context.**
- E1 asks whether cheap methods already solve the tasks.
- The local embedding model (§0) isn't chosen yet, and M3's dense retrieval needs one anyway.

**Decision.**
- **Majority:** the most frequent type and area label, component and needs-info class, taken from train.
- **Classifier:**
  - TF-IDF (1–2-grams, sublinear TF, fitted on train only) with balanced logistic regression: one-vs-rest labels (≥ 10 triaged examples), multiclass component, binary needs-info;
  - duplicates by TF-IDF nearest neighbour among issues created *strictly before* the query, with the threshold tuned on train;
  - `sklearn` has no stubs, so only this module relaxes pyright's unknown-type reports.
- **Single-shot LLM:**
  - one strict-JSON call with generic instructions and the label/component vocabulary, and the issue delimited as untrusted data;
  - one repair attempt on invalid output, then an empty, recorded fallback;
  - out-of-taxonomy labels are dropped into `rejected_labels`;
  - temperature 0 where the route supports it.
  - It cannot see other issues, so it never predicts duplicates.

**Consequences.**
- The classifier is a strong, honest floor for T1/T3.
- Embeddings arrive in M3, where their effect can be measured against this TF-IDF baseline instead of assumed.

## ADR-0017: A concurrent, resumable, budget-safe eval runner

**Context.**
- LLM calls are slow (15–60 s here), so runs must be parallel.
- Parallelism breaks naive budget checks.
- Providers rate-limit.
- Test-set hygiene must not depend on discipline.

**Decision.**
- **Concurrency:** a thread pool with a configurable worker count (4 for the OpenRouter Qwen route after 429s at 8).
- **Budget reservation:** `BudgetGuard.reserve(worst_case)` before each call, then `settle`/`release`, all under a lock.
- **Resumable:** predictions are appended per issue as they complete, and `--resume` continues a run.
- **Infrastructure failures:** exceptions raised by a system are marked `infra:`, get one single-worker retry pass, and are never scored as answers.
- **Budget stop:** stops cleanly and leaves the run unscored.
- **Test-set guard:** `--split test` needs `--allow-test`, is capped at two evaluations, and every one is logged to `runs/test_evaluations.jsonl`.

**Consequences.**
- Parallel runs can't overshoot a cap.
- An outage can't masquerade as model failure.
- The "test evaluated at most twice" rule is enforced by code.

## ADR-0018: Branch protection and evals in CI

**Context.** The owner asked for branch protection. §15.1 asks for baseline evals in CI from M2.

**Decision.**
- **Protection on `main`:**
  - requires `Lint & types`, `Tests (ubuntu-latest)`, `Tests (windows-latest)` and `Leakage guard`, bound to the GitHub Actions app (id 15368) so another app can't spoof them;
  - branch must be up to date;
  - no force-push or deletion.
  - `enforce_admins` stays off, so the owner's direct pushes keep working while PRs (e.g. Dependabot) must pass.
- **"Eval smoke (fixtures)" job:**
  - builds a synthetic dataset with the real pipeline;
  - runs the majority and classifier baselines through `triagelab eval`;
  - posts the results table to the job summary.
  - A pytest version asserts the classifier beats majority's whole interval.

**Consequences.**
- Every push shows an eval, not just tests.
- **Trade-off:** admin pushes bypass the required checks ("Bypassed rule violations"). Making them binding would mean a PR-per-milestone workflow, which is proposed to the owner.

## ADR-0019: Time-aware retrieval, including its statistics

**Context.**
- §7.2 says the index used for issue X may contain only issues created before X.
- Filtering *results* by date isn't enough. A standard BM25 computes IDF and average document length over every indexed document, so future issues still shape how past issues rank.

**Decision.**
- **Corpus:** holds each issue's creation-time title/body (reconstructed as for snapshots) plus the timestamped events needed to replay labels, renames and state. Nothing else from after creation is stored.
- **Query paths:** `visible(as_of)` and `get(as_of)` are the only ones, and both refuse issues created at or after `as_of`.
- **Our own BM25:**
  - documents stored oldest-first, with per-term posting lists;
  - document frequencies, collection size and average length come from the visible prefix only;
  - Lucene-style non-negative IDF.
  - A test asserts that adding future documents never changes past scores. This replaced the `rank-bm25` dependency.
- **Dense search:** a prefix of the corpus-ordered embedding rows, so it is time-safe by construction.
- **Fusion:** reciprocal rank fusion (k = 60), written by hand. It uses ranks, not scores, so BM25 and cosine need no calibration.

**Consequences.**
- Leakage-by-statistics is impossible rather than negligible.
- The corpus is also a leakage boundary, so its tests run under `pytest -m leakage`.

## ADR-0020: arctic-embed-s on fastembed, with a resumable embedding store

**Context.**
- `embedding_model` (§0) needed a small, local, permissive model.
- This laptop has about 1.5 GB of free RAM, and background jobs get stopped under memory pressure.

**Decision.**
- **Model:** `snowflake/snowflake-arctic-embed-s` (33M parameters, 384 dimensions, Apache-2.0, April 2024), run via fastembed on ONNX Runtime with the CPU memory arena disabled. That's about 320 MB of RAM and no PyTorch. Owner's choice among three researched options.
- **Store:** vectors are keyed by issue number in resumable chunks.
- **Query prefix:** the model's query prefix is configurable, and both settings are measured.

**Consequences.**
- A ~30-minute embedding job survives interruption.
- Adding older history doesn't invalidate existing vectors.
- The ultra-light alternative (model2vec `potion-retrieval-32M`) remains a possible ablation.

## ADR-0021: The repo-intel MCP server

**Context.** §8: five read-only tools, with `as_of` enforced by the server, versioned tool descriptions, and bounded output.

**Decision.**
- **SDK:** MCP Python SDK v2 (`MCPServer`). Every tool is annotated `read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False`, and returns structured (pydantic) output.
- **`as_of` is enforced in three places:**
  1. the corpus refuses later issues;
  2. an optional server-side ceiling rejects any `as_of` after the moment being triaged;
  3. in M4 the harness will *inject* `as_of` into tool calls, so a model can never choose a later time.
- **Tool descriptions and parameter descriptions** are treated as prompts, versioned by `TOOLS_VERSION`.
- **Output bounds:** bodies are truncated to 6,000 characters and snippets to 300, each with a truncation marker. Code search caps both hits per file and total hits.
- **Tests, in three layers:**
  1. unit (corpus, BM25, code search, CODEOWNERS);
  2. an in-process MCP `Client` against the real server;
  3. a manual MCP Inspector check.

**Consequences.**
- The server is usable standalone (`python -m triagelab.mcp_server`) and publishable in M9.
- The model sees no write capability anywhere.

## ADR-0022: Frozen checkout, literal code search, and index-only history

**Context.**
- Code search must not show fixes made after the issues being triaged.
- Half of all duplicate originals (93 of 202) predate the collected dataset window.

**Decision.**
- **Frozen checkout:** the source tree at the last `main` commit before `eval_start` (CPython `398d7e1`, 2026-05-18 23:55 UTC), extracted with tarfile's `data` filter.
  - It's an approximation: an August issue sees May's code. Documented in the dataset card.
- **Code search:**
  - literal and case-insensitive, because model-written regexes are fragile;
  - uses ripgrep when installed, with a pure-Python fallback (about 1–5 s on the 140 MB tree);
  - CODEOWNERS parsed per GitHub's documented rules.
- **Index-only history:** `windows.index_start` (CPython: 2024-01-01) adds retrieval-only history in a separate raw file. It never enters a split, so the dataset and its hash are unchanged.

**Consequences.**
- More duplicates become findable without touching the evaluation data.
- Originals from before 2024 (about 50 of 202) remain unreachable, and that's reported as a coverage limit.

## ADR-0023: Hybrid search stays the default; no query prefix

**Context.**
- `reports/retrieval/python__cpython.md` covers 202 duplicate queries from train/dev only, 152 of them reachable.
- Paired bootstrap on reachable queries:
  - dense beats BM25 (MRR +0.144 [+0.079, +0.212]);
  - hybrid beats BM25 (MRR +0.143 [+0.102, +0.189]);
  - hybrid vs. dense shows no evidence of a difference (−0.002 [−0.046, +0.042]).
- arctic-embed-s's query prefix changed no metric beyond noise (`python__cpython-query-prefix.md`).

**Decision.**
- **Default mode:** `search_similar_issues` keeps **hybrid** (RRF of BM25 and dense).
  - It ties dense on full-issue queries.
  - Its gain over BM25 has a tighter interval, so it loses to BM25 on fewer individual queries.
  - The agent will send short, identifier-heavy queries (function names, error strings), where exact term matching should matter more than it does for whole-issue queries.
- **Query prefix:** off (the default). The task is symmetric (issue vs. issue), not the question-vs-passage setting the prefix was trained for.

**Consequences.**
- One default for the server, the M4 harness and E3.
- Hybrid-vs-dense is **re-measured on agent-written queries** from M4 traces; if dense wins there, the default changes with a new ADR.
- The hybrid-vs-dense tie is reported as a (mild) negative result: fusion didn't add accuracy here.

## ADR-0024: Native tool calling, with the final answer as a tool

**Context.**
- The agent needs tools (MCP, skills) and a validated final `TriageResult` (§10).
- The pinned route (`deepinfra/bf16`) lists `tools` and `tool_choice` but not `parallel_tool_calls`, and our `require_parameters: true` makes OpenRouter refuse a route for any unlisted parameter. (Parasail, the M7 decision route, has no tool support at all.)

**Decision.**
- **Protocol:** native OpenAI-style tool calls through our client (`LLMRequest.tools`, `tool_choice`), never `parallel_tool_calls`.
- **Final answer:** a `submit_triage` tool whose parameters are the answer's JSON schema, with `$ref`s inlined and titles dropped. A validation error is that tool's result, and the model gets up to 2 retries.
- **Forced answer:** near any budget the next call is made with `tool_choice=submit_triage`.
- **Reasoning:** traced, but not sent back on later turns. OpenRouter recommends preserving it in tool loops but names no Qwen requirement, and dropping it keeps prompts smaller.
- **Cache compatibility:** empty tool fields are omitted from serialization, so every tool-free request keeps its old cache key. A test pins one.

**Consequences.**
- Rejected: a JSON "action" protocol via `response_format` (needless when native tools exist), and ReAct text parsing (fragile).
- E1's cached answers stay valid.

## ADR-0025: A synchronous MCP client over an anyio blocking portal

**Context.** The runner is threaded and synchronous. The MCP Python SDK 2.2.0 is async-only and ships no sync wrapper.

**Decision.**
- **Bridge:** `McpSession` owns one event loop (an anyio `BlockingPortal`) and one MCP `Client` session. Worker threads submit `call_tool` to it, and the session multiplexes requests.
- **Transports:**
  - evaluation launches `repo-intel` as a real **stdio subprocess**, with stderr going to `runs/<id>/mcp_server.log`;
  - tests use the in-memory transport.

**Consequences.**
- The agent crosses a real protocol boundary, as a third-party client would.
- One server process serves every thread.
- Rejected: making the harness async, which would spread `async` through the runner, the triagers and the LLM client.

## ADR-0026: Skills loaded by hand; skill tools are local

**Context.**
- §9: progressive disclosure, implemented ourselves.
- The Agent Skills spec (checked 2026-09-30, last changed 2026-08-04) and its client guide describe the catalog, activation and resource levels.

**Decision.**
- **Three levels:**
  1. the `<available_skills>` catalog (names and descriptions) in the system prompt;
  2. `load_skill(name)`, which returns the body plus a list of files, not their contents;
  3. `read_skill_file(name, path)`, confined to the skill folder.
- **Validation:** parsing is lenient at runtime (per the client guide), and a test holds our own skills to the strict spec.
- **Placement:** skill tools are local, not MCP. Skills instruct this agent; they aren't repository data.
- **Compaction:** skill content is never elided.

**Consequences.**
- Whether a small model *chooses* to load a skill becomes measurable: the skill load rate in `runs stats`.
- The first runs show that it doesn't (0 of 3), which H1/E2 must account for.

## ADR-0027: Per-issue budgets force an answer and count original cost

**Context.** §10 needs max steps, tool calls, tokens and cost per issue, with a graceful fallback.

**Decision.**
- **Soft limit:** the step before a limit (or any exhausted limit) forces `submit_triage`.
- **Hard stop:** at `max_steps` the loop ends with no answer, and the reason is recorded as `budget:<limit>`.
- **Cost basis:** budgets count cached responses at their *original* cost and tokens. Counting cache hits as free would trip a limit at a different step during replay, change every later request, and break the cassettes.

**Consequences.**
- A slow issue still yields a flagged answer rather than an empty one.
- Replays make exactly the decisions the recorded run made.

## ADR-0028: Deterministic context compaction

**Context.** §10 asks for summaries of older turns near the context limit.

**Decision.**
- **Truncation:** every tool result is truncated when it is produced.
- **Elision:** above `context_limit_tokens` (estimated at 4 characters per token), the oldest tool results become a one-line stub naming the call, so the model can repeat it.
- **Never elided:** the system prompt, the issue, skill content, and the last two results.
- **Logging:** every compaction is traced with its before and after sizes.

**Consequences.** No extra model call, no new failure mode, and replays stay deterministic. An LLM-written summary was rejected on cost and reproducibility.

## ADR-0029: JSONL traces as the source of truth; Phoenix as the viewer

**Context.**
- §5/§10 ask for OpenTelemetry to a self-hostable viewer (Langfuse or Arize Phoenix) plus local JSONL.
- The laptop has 15.8 GB of RAM with about 1.7 GB free.
- Langfuse self-hosting needs six containers (web, worker, Postgres, ClickHouse, Redis, MinIO), with documented minimums adding up to about 25 GiB.
- Phoenix is one Python process on SQLite, with OTLP at `:6006/v1/traces`.

**Decision.**
- **JSONL:** `runs/<id>/traces.jsonl` records every model call, tool call, compaction, validation error and final answer.
- **OpenTelemetry (optional, `tracing.otlp_endpoint`):**
  - an AGENT span per issue, with LLM and TOOL child spans recorded with their measured timings;
  - OpenInference attribute names;
  - a private tracer provider per run.
- **Viewer:** Phoenix, run on demand with `uvx`. It isn't a project dependency.

**Consequences.** Traces work offline and in CI (as artifacts). The viewer is a convenience, never a requirement.

## ADR-0030: Cassettes are the response cache, replayed read-only

**Context.** §12.8 wants a 10-issue agent smoke eval on every PR that is deterministic and free.

**Decision.**
- **Recording:** recorded responses live in `tests/cassettes/agent-smoke/`, written by the ordinary content-addressed cache (ADR-0006).
- **Replay:** `cache.replay_only` swaps in a backend that raises `CassetteMissError` on any miss. It isn't retried, and it stops the run.
- **Setup:**
  - the smoke config extends the real agent config;
  - repo-intel runs as a stdio subprocess over a synthetic BM25 corpus;
  - re-recording takes two documented commands and about 5 cents, and it charges the real spend ledger.
- **Byte-identical requests across OSes:**
  - the cache writes LF on every OS;
  - skills are read with universal newlines;
  - pre-commit leaves cassette files untouched.

**Consequences.**
- Any change to a prompt, skill, tool output or agent setting fails CI until the cassettes are re-recorded, on purpose.
- No API key ever reaches PR workflows.

## ADR-0031: Gold labels are collected blind, then adjudicated with evidence

**Context.** §7.5 asks for hand labels (gold) and silver-vs-gold κ. The obvious interface shows the silver labels and asks the person to confirm or fix them. That anchors the person on silver and inflates the very agreement we want to measure.

**Decision.**
- **Two passes per issue** in the labeling app (`triagelab label`):
  1. **Blind:** labels, component and needs-info, from the issue as it was opened. No GitHub link and no labels are shown; the body is plain text.
  2. **Final:** the evidence is revealed (labels with who applied them, fixing PRs and their files, the duplicate closure), and the person sets the gold, starting from their *own* blind answer.
- **Storage:** both passes, plus the blind-pass time, go to `data/gold/<repo>.jsonl`, which is committed. The latest line per issue wins.

**Consequences.**
- One labeling session yields three results:
  - gold labels for the headline numbers;
  - a **human baseline** (the blind pass scored like any system: `results --labels gold`);
  - a measure of how much evidence moves a careful reader (blind vs. final κ in `gold-report`).
- Duplicates are adjudicated, not discovered: a person can't search the tracker blind.

**Correction (2026-09-30).**
- The "human baseline" consequence was wrong.
- When the same annotator adjudicates the gold starting from their own blind answer, the blind pass is anchored on itself. It scored 0.96 against its own gold, which is not comparable to any system.
- The blind-vs-final agreement *does* measure how much the evidence moves the annotator, and `gold-report` reports it.
- As a benchmark row, the blind pass is now off by default (`results --with-blind-pass`). It's only meaningful from an annotator independent of the one who adjudicated the gold.

## ADR-0032: The T5 judge: GPT-6 Luna, reason-then-score, calibrated once per version

**Context.** §12.4: a 3–4 criterion rubric scored 1–4, the owner's ratings split into judge-dev and judge-test, agreement reported as QWK, and bias checks.

**Decision.**
- **Rubric:** `configs/judge/rubric.yaml` (draft v1: correctness, actionability, tone). The level descriptions are shown verbatim to both the human and the judge.
- **Judge:** GPT-6 Luna via OpenRouter, a different family from the agent (ADR-0010), with no temperature (its endpoint rejects one). It gives structured output: per criterion, reasoning, then a score.
- **Ratings:**
  - 100 dev issues, each with *one* comment: the system is chosen at random between the M4 agent and single-shot, and hidden from the rater.
  - The set is frozen in `data/gold/judge_items.jsonl`.
  - A stable hash puts each item in judge-dev or judge-test.
- **Bias checks on judge-dev:**
  - verbosity: append polite filler to each comment;
  - position: reverse the criterion order.

  Both report the mean score shift.
- **Hygiene:** `JudgeTestGuard` refuses a second judge-test measurement for the same judge prompt and rubric versions.

**Consequences.** The judge can be tuned freely on judge-dev and reported honestly on judge-test. Any rubric or prompt change is a new version and needs a new measurement.

## ADR-0033: Failure taxonomy from open coding, then a validated LLM tagger

**Context.** §12.6: open coding on about 50 failures, consolidation to 6–10 categories, and an LLM tagger validated against the person.

**Decision.**
- **Failures** are computed per issue and task against silver or gold (`eval/failures.py`), with a readable difference ("missing: stdlib; extra: docs").
- **Open coding:** the review page shows the failure, the issue and the agent's trace. The person tags free-form codes; the §12.6 seed codes are offered, and new codes can be created.
- **Taxonomy:** `configs/failures/taxonomy.yaml` maps categories to the open codes they absorb. It is v0 until the owner's coding is consolidated.
- **Tagger:** the LLM tagger (same model as the judge) picks categories from the failure plus a compact trace. `failures validate` reports per-category κ, exact-set agreement and Jaccard against the person's mapped codes.
- **Reports:** `failures tag` writes `<run>/failures.parquet`, and `runs stats` prints the category counts.

**Consequences.** Category counts in reports carry a measured agreement number, not blind trust in an LLM.

## ADR-0034: The labeling app is Streamlit, configured by environment, tested with AppTest

**Context.** §5 names a minimal Streamlit app. Streamlit's test harness (AppTest) doesn't set `sys.argv`.

**Decision.**
- **Dependencies:** Streamlit 1.64 in a `labeling` dependency group, installed by default so CI tests it. Skip it with `--no-group labeling`.
- **Configuration:** the app reads `TRIAGELAB_*` environment variables, and `triagelab label` sets them. Usage statistics are turned off.
- **Structure:** logic lives in plain modules (`labeling/gold.py`, `ratings.py`, `failure_tags.py`), and each page is a thin view over them.
- **Tests:** AppTest drives each page end to end: blind then final gold, a rating, a failure tag on a replayed agent run.

**Consequences.** The UI is covered by CI without a browser, and every label-handling rule is unit-tested outside Streamlit.

## ADR-0035: The owner delegated labeling to a model annotator (Claude), recorded as such

**Context.**
- §7.5 planned hand labels ("gold") by the owner.
- On 2026-09-30 the owner asked the coding agent (Claude Opus 5.5) to do the labeling instead: gold labels, comment ratings and failure tags.

**Decision.**
- **Provenance:** every record carries `annotator: claude-opus-5-5`. Reports call these **Claude-adjudicated labels**, never "human gold".
- **What changes in meaning:**
  - the blind-pass baseline row is a strong-LLM baseline, not a human one;
  - judge calibration measures agreement between two model families (GPT-6 Luna vs. Claude), not human validity;
  - silver-vs-gold κ measures disagreement between maintainer-derived labels and a careful model reviewer.
- **Process:** unchanged and enforced by tooling (`triagelab annotate`, ADR-0031):
  - blind batches contain only creation-time text;
  - evidence is exported only after the blind answers are stored;
  - rating batches use opaque ids, with no system names.

  Labeling runs in isolated subagents that write answers to files.
- **Test-split hygiene:** test issues are labeled only at M8, after all prompt, skill and threshold decisions are frozen, by isolated subagents whose content never enters the main development context. The annotator is also the developer, and reading test issues now could leak into later decisions.

**Consequences.**
- M5's numbers are available now, honestly labeled.
- A human spot-check of about 20 issues would put a number on the reliability of the model labels. It's recommended, but optional.
- A threat to validity is recorded: labels from an LLM may favour LLM-shaped answers, which could flatter the LLM systems relative to TF-IDF.

## ADR-0036: T4 (needs-info) leaves the headline metrics

**Context.**
- T4's silver label is "a human applied `pending`" (§7.3).
- Adjudicating the 97 usable dev issues flagged **none** as needing information, where silver flagged 15 (κ = 0.00). `pending` in CPython means "awaiting a maintainer decision" or "closing unless someone objects".
- With zero adjudicated positives, T4 F1 is undefined on gold, and on silver it measures agreement with a process label.

**Decision.**
- T4 is still predicted and scored in every scorecard, but it's out of the headline results table and the README.
- Silver T4 numbers are described as "predicts `pending`".
- A valid needs-info task needs a different derivation. One option is maintainer comments that ask the reporter for information, before any reply. That's future work, re-checked with the same adjudication.

**Consequences.** No headline claim rests on a label that doesn't mean what its name says. The T4 infrastructure (metrics, the `needs_info` field) stays for the re-derivation and for the transfer repo, whose needs-info label may be valid.

## ADR-0037: The spend ledger is appended under a cross-process file lock

**Context.**
- M6 ran two evaluations in parallel for the first time.
- Both processes appended to `runs/spend_ledger.jsonl`. On Windows, append mode is not atomic across processes, so two appends overlapped: one line lost its start, and one entry (about $0.005) was lost from the record.
- The ledger feeds `BudgetGuard`'s total, so a corrupt line stopped every later run (`SpendLedger.entries()` refuses to guess).
- A stress test of the old code (4 processes × 200 appends) lost 21–38% of lines.

**Decision.**
- `ledger.record` writes each entry as one binary write, while holding an exclusive lock on `<ledger>.lock` (`triagelab/filelock.py`: `msvcrt.locking` on Windows, `fcntl.flock` elsewhere).
- No new dependency: `filelock` or `portalocker` would do the same thing in about 30 lines we can read.
- The damaged ledger was repaired by hand:
  - the broken fragment was removed;
  - the lost entry was replaced with a conservative `ledger-repair` adjustment, rounded up.

**Consequences.**
- Parallel runs are safe. `tests/test_ledger_concurrency.py` runs 4 writer processes and checks that no entry is lost.
- The budget total stays an upper bound on real spend.
- A crashed process can't leave the lock held: OS locks are released when the file handle closes.

## ADR-0038: E4's multi-agent arm is a planner, two narrow workers and a synthesizer

**Context.**
- §13 E4 asks whether a planner plus subagents is worth it over the single agent.
- M5's taxonomy blamed most agent failures on two behaviours:
  - thrashing: repeated or overlapping searches;
  - ignoring evidence: the right component or duplicate was in a tool result, but the answer didn't use it.

  Narrow roles are the usual multi-agent answer to both.
- Options considered:
  - an LLM orchestrator that spawns subagents freely, as a tool call;
  - a fixed pipeline;
  - a planner that chooses from fixed specialists.

**Decision.**
- **Plan:** one structured call (`Plan`) decides whether to send a *duplicate scout* (`search_similar_issues`, `get_issue`) and a *code locator* (`search_code`, `get_codeowners`, with the component map in its prompt), and gives each some search hints.
- **Workers:** each worker runs the same hand-written loop with its own findings schema (`submit_findings`) and budget (6 steps, 4 tool calls, $0.01).
- **Synthesize:** the synthesizer runs the reference agent's loop, prompt and skills. It has **no retrieval tools**, and it gets the findings as a delimited note, marked as evidence rather than instructions.
- **If the plan doesn't parse:** both workers are sent, without hints.
- Free spawning was rejected: with a 9B model it adds a failure mode (bad delegation) without isolating the question.
- The two arms differ only in how retrieval is organised. Model, skill, vocabulary and answer schema are shared (`architecture: single | planner`).

**Consequences.**
- E4 measures one change: the same retrieval split into roles.
- Cost is counted over every role, so the comparison is fair on cost.
- The trace marks each role with a `role` event. Step numbers restart per role.
- The synthesizer can't check a worker's claim. If E4 loses, the traces show whether the loss came from bad findings or from bad synthesis.

## ADR-0039: E5 runs the 27B on Novita bf16, with "soft" forcing of the final answer

**Context.**
- E5's first run (27B on Alibaba) failed on 64 of 100 dev issues. OpenRouter answered 404: "No endpoints found that support the provided 'tool_choice' value".
- The harness forces the final `submit_triage` call with a named `tool_choice` when a budget runs out.
- Probes (one call each, 2026-09-30) showed the 27B refuses both a named `tool_choice` and `required` on Alibaba and on Novita. Only an unset (`auto`) `tool_choice` works. The 9B's DeepInfra route accepts named choices.

**Decision.**
- **Route:** E5 uses Novita at **bf16**, the same precision as the 9B arm. Alibaba doesn't disclose its precision, so this is a better-controlled size comparison.
- **New capability flag:** `llm.named_tool_choice` (default true).
  - When it's false, a forced call offers **only** the forced tool, with `tool_choice` unset. The first time, the loop adds one line: "The <limit> limit is reached. Call submit_triage now".
  - The flag lives in `LLMConfig`, not in the request, so existing cache keys and cassettes are unchanged.
- **Also fixed:** `tool_choice: required` was being sent as a function name; it now passes through as-is.
- **Matching:** E5 is paired with a 9B reference run on the same harness (tools v2).

**Consequences.**
- The two E5 arms force the final answer differently: hard for 9B, soft for 27B. The count of `no_answer` after a forced call is reported, so the difference is visible.
- The partial Alibaba run (`20260930-114257-e5-agent-27b-3eca81`) is discarded as an infrastructure failure, not a result.
- §0's `small_model` route changes to `novita/bf16`.

## ADR-0040: The real-API regression gate: fixed subset, blessed baseline, point-estimate thresholds

**Context.**
- §12.8 asks for a regression gate on real model calls:
  - a fixed 50-issue dev subset;
  - a paired-bootstrap delta table posted on the PR;
  - failure if a headline metric drops beyond a threshold;
  - a cost cap and the owner's approval.
- The dataset is gitignored and takes hours to collect, so a CI runner doesn't have it.
- Each gate run costs about $0.35 of a $150 project budget.

**Decision.**
- **Subset:** `configs/gate/dev-subset.txt` holds the 50 adjudicated, usable dev issues with the smallest stable hash (`triagelab gate subset`).
  - It's order-independent and reproducible.
  - `eval.subset` refuses any ref outside the requested split.
- **Baseline:** `triagelab gate bless <run>` copies a run's subset predictions, records and failure tags (not its traces) to `reports/gate/baseline/`, which is committed. The owner re-blesses after a merge that changes the reference agent. Comparing against a committed baseline halves the cost of each gate run and makes "what are we comparing against" reviewable in git.
- **Rules** (`configs/gate/gate.yaml`, scored on gold labels):
  - FAIL when T1 micro-F1 falls by more than 0.05 or T3 accuracy by more than 0.08 (4 issues);
  - FAIL when cost per issue rises by more than 30%;
  - FAIL when more than 6% of answers are fallbacks;
  - FAIL when the candidate misses any baseline issue. Without this rule, a crashed run passed with nothing to compare; the rule was added after exactly that happened in a local dry run.
  - A significant drop that stays inside its threshold is a WARN.
  - T2 is report-only: the subset has 2 duplicates.
- **Why thresholds apply to point estimates, not CIs:** on 50 issues a real 5-point drop is rarely significant, so a CI-based gate would almost never fire. The CI is printed next to every delta for the reviewer.
- **Data:** an **eval pack** (`triagelab gate pack`, about 29 MB) holds:
  - the dataset tables with every test-period row removed (the test sample and its reserve);
  - the retrieval index, cut at the start of the test period;
  - a SHA-256 manifest.

  The source checkout is re-downloaded at the frozen commit, and the gold labels are in git.
- **Correction, before the first publish (2026-10-01):**
  - The first pack cut the tables but shipped the *whole* retrieval corpus. That's every issue up to `eval_end`, test-period issues included, each with its label history, which amounts to the test labels, in a public repository.
  - The pack (version 2) now also drops every corpus document and embedding created on or after `test_start`. That loses nothing: the gate triages dev issues, and `as_of` never shows a later issue.
  - `gate unpack` re-checks both cuts against the repository's own profile instead of trusting the manifest, and refuses unknown index files.
- **Workflow (`eval.yml`):**
  - Triggers: the `run-eval` PR label, or a manual dispatch.
  - The `eval` environment requires owner approval and holds the API key. Fork PRs are excluded, and `pull_request_target` is never used.
  - At most one gate every 6 days unless forced; the run is capped at $1.
  - Concurrency never cancels a paid run.
  - The table goes to the job summary and a sticky PR comment, and the run folder is uploaded for 14 days.

**Consequences.**
- The gate needs three one-time actions from the owner, all outward-facing:
  1. publish the eval pack as the `evalpack-v1` release asset;
  2. create the `eval` environment with themselves as required reviewer;
  3. add the `OPENROUTER_API_KEY` secret to it.
- The thresholds are a first guess from the iteration 3–5 pairs. An A/A run (baseline configuration against itself, uncached) would measure run-to-run noise directly, and they should be revisited once one exists.

## ADR-0041: The 9B route runs on the owner's DeepInfra key (BYOK)

**Context.**
- From about 11:47 UTC on 2026-09-30, OpenRouter's *shared* DeepInfra pool for Qwen3.5-9B answered most calls with 429 `engine_overloaded` (`limit_source: upstream_provider_shared_pool`).
- The pool got about 1–10 calls a minute through, and the iteration-6 run had 79 of 89 issues failing. The endpoint's uptime figures still looked normal, because they don't count these 429s.
- The alternatives each had a cost:
  - moving to an fp8 host changes the model;
  - Parasail bf16 has no tool calling;
  - making the 27B the agent changes §0.

**Decision.**
- The owner added a DeepInfra key to OpenRouter (BYOK). Nothing in the requests changes: same model, same `deepinfra/bf16` route, same prices. The generation record of a probe call shows `is_byok: true`.
- DeepInfra bills the owner directly, and OpenRouter charges nothing on top within its monthly allowance.
- The spend ledger still prices every call from `configs/prices.yaml`, so the $150 guard covers these calls too.
- DeepInfra allows 200 concurrent requests per model, so agent runs go from concurrency 4 (chosen because of shared-pool 429s) to 8. Concurrency changes no request and no cache key.

**Consequences.**
- M4–M6 stay on one model, precision and host.
- When the key is rate-limited, OpenRouter falls back to the shared pool (the default), and those calls can still 429. The runner retries them as infrastructure failures, never scores them.

## ADR-0042: Decision backends for E6: an LLM with two confidence sources, and a classifier

**Context.**
- §11 asks for typed decisions answered by Jev, an LLM and a classifier, compared on accuracy, calibration, cost and latency (E6).
- The owner has no Jev access (`jev_access: no`, 2026-10-01).
- The decisions must have reference answers on dev to be measurable.

**Decision.**
- **Questions:** two single-choice decisions:
  - the issue's **type label** (5 options; training and scoring only where the labels name exactly one type);
  - its **component** (the profile's map, with prefixes in the question).
- **State:** every backend gets the same text, the `<issue>` block the agent sees.
- **Backends** (`decisions/`):
  - **LLM, verbalized:** a JSON reply restricted to the options (enum schema), plus a stated probability.
  - **LLM, logprobs:** the options are lettered and the reply is one letter. The confidence is the first-token probability mass on each option's letter, with variants pooled and the result renormalised over the options.
  - Thinking is **off** for both LLM arms, so the answer is the first token and the two arms differ only in where the confidence comes from.
  - **Classifier:** logistic regression (one head per question) on arctic-embed-s vectors of the same issue text, trained on the silver train split, with embeddings cached on disk.
- **No TypeSafe adapter:** without Jev access it would only add a dependency that hides the confidence computation §1.3 asks us to write.
- **Route:** both LLM arms run Qwen3.5-9B on **Venice fp8**.
  - Logprobs need a provider that serves them: only Parasail (bf16) and Venice (fp8) do.
  - Parasail's shared OpenRouter pool answered 90% of calls with 429 on 2026-10-01.
  - On a probe, Venice's first-token distribution matched Parasail's to within about 0.1 nats per option.
  - These backends are separate systems from the bf16 agent, and the precision is recorded.

**Consequences.**
- E6 compares like with like: same model, route, prompt state and thinking setting for the two LLM arms.
- The answer format still differs (an option name vs a letter), and that alone moved component accuracy (silver 0.82 vs 0.69). The comparison has to report accuracy as well as calibration.
- A future Jev backend only implements `DecisionBackend`.

## ADR-0043: The cascade is evaluated offline, at two granularities, with cross-fitted thresholds

**Context.**
- §11 asks for a cascade: accept a cheap answer when its confidence is at least τ, otherwise escalate to the full agent.
- τ is picked on dev, and the result is reported as a curve of accuracy vs. share escalated vs. cost.
- The owner chose the stuffed agent (E3) as the cheap tier, on 2026-10-01.
- E6 showed that some single decisions are answered better by a one-call backend than by the agent.

**Decision.**
- **Offline and exact.** Every tier's answers are stored predictions, so a cascade at any τ is a recombination of runs (`decisions/cascade.py`): no model calls, no sampling noise between the tiers.
- **Issue level (E7):** the stuffed agent triages every issue, and the issue escalates to the full agent when the gate is unsure.
  - **Self gate:** the cheap tier's own min(type-label, component) confidence.
  - **Agreement gate:** a decision backend's min confidence when its type *and* component agree with the cheap tier, otherwise 0. A backend's confidence describes its own answer, so disagreement is the escalation signal.
- **Decision level (H3):** a backend answers a single question, and the agent's answer is used when the backend's confidence is below τ.
- **Choosing τ:** the cheapest τ whose metrics stay at the full agent's level on dev (tolerance 0, ties to the larger τ). It's reported both as chosen on all of dev and **2-fold cross-fitted** (each half routed by the τ chosen on the other half); the cross-fitted row is the honest estimate.
- **A live cascade triager is deferred to M9.** It's needed for the demo, not for the measurement. Running two MCP-backed agents at once doubles memory on the development machine.

**Consequences.**
- Every cascade number is reproducible from the run registry (`triagelab cascade reports/cascade/e7.yaml`).
- The decision-level result (a $0.15-per-1,000 call matching the agent on type and component) is the strongest evidence for H3. Whether to *deploy* decisions that way, with the agent kept for labels, duplicates and the comment, is a design question for M8/M9.

## ADR-0044: Code search uses the built-in scanner; ripgrep is opt-in

**Context.**
- ADR-0019's code search used ripgrep "when installed", with a pure-Python fallback.
- The development machine has no ripgrep, so every recorded run, including the regression gate's baseline, used the fallback.
- The two differ in more than speed: ripgrep skips hidden files and anything matched by `.gitignore`.
- A CI runner with `rg` on its PATH would therefore have searched differently from the baseline it's compared with. This was found while preparing the gate's first CI run.

**Decision.**
- `CodeSearcher` uses the built-in scanner unless `use_ripgrep=True` is passed explicitly. An installed `rg` is never picked up on its own.
- Evaluation always uses the scanner (1–5 s per query on the 140 MB tree, which is acceptable).

**Consequences.**
- Tool results are the same on every machine, so a CI candidate and a local baseline differ only by what the PR changed (and model sampling).
- General rule recorded for the project: an evaluation's behaviour must not depend on which optional tools happen to be installed.

## ADR-0045: The transfer repo is astral-sh/uv, with a label-provenance caveat

**Context.**
- ADR-0011 chose uv tentatively and required the same label-provenance scan before M8.
- The scan (2026-10-01, 281 eval-window issues):
  - **T1:** 188 of 261 taxonomy labels were applied by the issue's author (uv's issue forms attach `bug`, `enhancement` or `question`); 72 by triagers. A maintainer triaged 26–32% of issues (CPython: 70%). `area:*` labels are sparse.
  - The form doesn't fully decide the type: `bug` and `enhancement` share one form, and on train 277 form-filed issues were relabelled `question` by maintainers.
  - **T2:** 85 structured duplicate closures. **T3:** fixing PRs link natively (about 20% of issues). **T4:** `needs-mre` (5%) is a real needs-information label, which CPython's `pending` wasn't (ADR-0036).
- The owner decided to keep uv, with the caveats recorded (2026-10-01).

**Decision.**
- **Profile** (`configs/repos/astral-sh__uv.yaml`): written from the label list and the directory layout at the freeze commit only.
  - type = bug, enhancement, question, documentation;
  - family = `area:*`;
  - 11 components by functional group of crates.
- **Windows:** the same as the primary repo.
- **uv's dev split** is built but never evaluated or tuned on. Transfer means swapping the profile and the skill, and nothing else (E8, H4).
- **Reporting:**
  - headline transfer numbers use the adjudicated test labels;
  - type labels are also reported on the maintainer-triaged subset;
  - the provenance numbers go in the dataset card.

**Consequences.**
- Silver T1 on uv partly measures "which form did the author pick". It's a lower bound on label quality, not a triage ground truth.
- uv gives the project its first valid T4 evaluation.

## ADR-0046: The test split is evaluated through frozen sessions, in CI, from a test pack

**Context.**
- §7.4: the test split is evaluated at most twice in the whole project. §12.8: a manual, approval-protected workflow records each run and refuses a third.
- The M2 guard counted *runs* (limit 2), but the final evaluation covers several configs.
- A counter also freezes nothing: prompts and post-processing live in code, so a config fingerprint alone lets a prompt change through.
- The owner chose to run the evaluation in CI and to publish a test pack for it (2026-10-01).

**Decision.**
- **Session** (`eval/test_session.py`): a file committed before any test issue is scored (`reports/test-eval/<slug>/session-N.yaml`). It holds:
  - each config's path, name and fingerprint (extended over a routed system's parts);
  - a hash of `src/triagelab`, `skills` and `configs`, with line endings normalised so Windows and Linux agree;
  - the dataset hash.
- **A test run is refused** unless:
  - its config is in the session;
  - the config, the code and the dataset are unchanged since the freeze;
  - the run covers the whole split;
  - that config has no completed run in the session;
  - the repository has at most two sessions.

  Every start and completion is appended to an audit log, which is committed with the results.
- **Test pack:** `gate pack --with-test` builds a pack with every split and the full retrieval history. It's published only when a session is frozen. Only `test-eval.yml` unpacks it (`--allow-test`); the regression gate's unpack still refuses it.
- **Workflow (`test-eval.yml`):**
  - manual dispatch only, in the approval-protected `eval` environment;
  - refuses a session that already succeeded in this workflow;
  - runs `triagelab test-session run`;
  - uploads the runs and the audit log for 90 days.

  Gold scoring happens afterwards, offline, from the stored predictions.
- **Frozen for session 1** (owner, 2026-10-01): the routed system (headline), the full agent, the stuffed agent, the TF-IDF classifier and the single-shot LLM.

**Consequences.**
- "Evaluated once" is enforced by code and by the workflow, not by convention, and the freeze covers prompts as well as configs.
- After publication the test issues and their silver labels are public. That's acceptable only because every decision is frozen first.
- A session pins the exact code: the evaluation has to run before any further change to `src`, `skills` or `configs`.

**As run (2026-10-02).**
- Session 1 of both repositories was frozen in commit `682f46a` on one code hash (`6de34cd0…`), five configs each.
- The packs were published only after that commit was pushed: releases `testpack-python__cpython-v1` and `testpack-astral-sh__uv-v1`, both targeting the freeze commit, each with its SHA-256 in the release notes.
- GitHub dispatches only workflows that exist on the default branch, so `test-eval.yml` reached `main` through its own small PR (#8) and is dispatched against the M8 branch, where the session files live.
- Freezing through the real command found a bug the unit tests had missed (two `--config` options on `test-session freeze`). It was fixed before the freeze, and the command now has a test that goes through the CLI.

**Correction: session 1 was re-frozen once, before anything was scored (2026-10-02).**
- **What happened:** the first CPython run (36947286684) was refused in CI at the first config, with "The code, skills or configs changed after the session was frozen". Nothing had changed: `git diff 682f46a -- src skills configs` was empty.
- **Cause:** `code_hash` sorted `Path` objects. They compare case-insensitively on Windows and case-sensitively on Linux, so `SKILL.md` and `references/` hashed in a different order on the machine that froze the session and the one that ran it. The existing test covered line endings but not file order.
- **Nothing was evaluated:** the run stopped at authorization, wrote no run and no audit line, and uploaded no artifact. The queued uv run was cancelled before it started.
- **Fix:** files are sorted by their path parts as plain strings. Two tests were added:
  - a hand-computed digest that pins the order;
  - a check that every committed session that hasn't run yet matches the checkout (code hash and every config fingerprint). CI runs it on Linux and Windows, so a freeze is verified on both before a run is requested.
- **Re-freeze:** session 1 of both repositories was frozen again in place with the same configs. The session files differ from the first freeze only in `created_at`, `code_hash` and the note; all ten config fingerprints and both dataset hashes are unchanged. Since the first freeze, the frozen trees differ only in that one function.
- **Why not session 2:** the limit of two sessions counts evaluations of the test split, and none took place. Opening session 2 would have spent the project's one spare evaluation on a tooling bug.

## ADR-0047: Repository-specific prompt wording lives in the profile

**Context.**
- A smoke run of the uv configs on 12 **train** issues (never dev or test) showed that 20% of model calls ran into the 4,000-token output limit and 2 of 12 issues ended as fallbacks. On CPython dev the rate is 0.3%.
- The shared prompt still carried CPython wording from iteration 1:
  - "area labels have no prefix (write `stdlib`, never `area-stdlib`)", while uv's area labels are literally `area:windows`;
  - headings that put uv's `performance`/`compatibility` under "Area labels" and its `area:` labels under "Topic and OS labels";
  - the single-shot prompt's "one type-* label".
- H4 says a new repository needs only a new skill and profile. A repo rule hard-coded in the harness contradicts that.

**Decision.**
- `RepoProfile.wording` (`PromptWording`) holds the label note, the two headings and the single-shot phrase, with neutral defaults.
- CPython's profile states the exact words that used to be hard-coded, so its prompts are byte-identical (cache, cassettes and results unchanged; a test pins the text).
- uv's profile states its own wording.
- Nothing else in the harness changed.

**Consequences.**
- On the same 12 train issues, with the uv wording:
  - calls at the output limit fell from 7 of 35 to 3 of 33;
  - fallbacks fell from 2 to 0;
  - median latency fell from 100 s to 34 s.
- The remaining loops are the 9B model's own indecision (question vs. documentation; wanting to verify code it has no tool for). The harness bounds them (output cap, then a nudge), and the rate is reported as a transfer finding.
- This is a correction to the transfer claim: the harness was not repo-neutral until this change. It was found before any uv dev or test issue was evaluated.
