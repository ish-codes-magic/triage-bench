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
