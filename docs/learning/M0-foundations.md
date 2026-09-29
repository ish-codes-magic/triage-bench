# M0: Foundations

**What M0 built:** the plumbing every later milestone relies on:
- a typed config system
- a model client with a disk cache, retries, exact cost accounting and a budget hard stop
- a run registry
- a CLI
- hardened CI

**Why it matters:** an eval project is only as trustworthy as its bookkeeping. If you can't say what config, code and model produced a number, and what it cost, the number isn't evidence.

```
triagelab llm ping
  └─ load_config ─► create_run (runs/<id>/ config.yaml, git_sha, manifest.json)
  └─ build_llm_client (wiring.py: the composition root)
       └─ LLMClient.complete
            1. price_for(model)            unpriced model → refuse
            2. cache.get(key)              hit → return, $0, record savings
            3. guard.check(worst case)     would break a cap → refuse before calling
            4. call_with_retries(backend)  transient errors only, jittered backoff
            5. cost_usd(usage) → guard.charge → ledger.record
            6. cache.put(key, response)
  └─ write_cost(run_dir)                   always, even on a budget stop
```

---

## 1. Concepts, and where they live

| Concept | What to take away | Code |
|---|---|---|
| **Canonical hashing** | Equal objects must hash equal on every machine. `hash()` is salted per process, and `json.dumps` depends on key order. So: sorted keys, fixed separators, UTF-8. | `src/triagelab/hashing.py`: `canonical_json`, `stable_hash` |
| **Typed, layered config** | `extra="forbid"` turns typos into load errors. `extends:` makes each experiment a diff against the base. The fingerprint ties a run to its exact config. | `src/triagelab/config.py`: `load_config`, `deep_merge`, `Config.fingerprint`, `PortablePath` |
| **Ports & adapters** | The client depends on a `Protocol`, not on LiteLLM. Only the adapter imports the vendor library, and the composition root decides which concrete classes go together. | `llm_client.py`: `CompletionBackend`; `litellm_backend.py`: `LiteLLMBackend`; `wiring.py`: `build_llm_client` |
| **Budget hard stop** | Check the *worst case* before the call and charge the *actual* cost after. A check that only runs after the call can overshoot. | `cost.py`: `worst_case_cost_usd`, `BudgetGuard.check/charge` |
| **Provable upper bound** | Instead of estimating tokens with a tokenizer, bound them: at most one token per UTF-8 byte for byte-level tokenizers. Over-counting is safe; under-counting isn't. | `llm_client.py`: `prompt_tokens_upper_bound` |
| **Semantic cache keys** | The key contains everything that can change the answer and nothing that can't. The `sample` index gives k-run consistency samples distinct entries. | `llm_client.py`: `LLMRequest.cache_key`; `cache.py`: `DiskCache` |
| **Atomic writes** | Write to a temp file, then `os.replace`. A crash leaves either the old entry or the new one, never half of one. | `cache.py`: `DiskCache.put` |
| **Retries done right** | Retry only transient errors (408/409/429/5xx), use full-jitter backoff, treat the server's `Retry-After` as a floor, and have exactly one retry layer. | `retry.py`: `call_with_retries`, `backoff_delay`; `litellm_backend.py`: `is_retryable` |
| **Append-only ledger** | The all-time budget has to outlive the process. The spend so far is the sum of a JSONL file. | `ledger.py`: `SpendLedger` |
| **Run provenance** | Every run records its resolved config, commit (flagged `-dirty` for uncommitted changes), versions and cost. Folders are claimed atomically and never overwritten. | `eval/registry.py`: `create_run`, `_claim_run_dir` |
| **CI hardening** | Actions pinned to SHAs, least-privilege token, no persisted credentials, the same hooks locally and in CI, a two-OS matrix, and workflows linted with actionlint. | `.github/workflows/ci.yml`, `.github/actions/setup-env/action.yml`, `.pre-commit-config.yaml` |
| **YOUR TURN mechanics** | The tests xfail only on `NotImplementedError`. CI stays green, and a wrong implementation still fails. | `tests/conftest.py` |

---

## 2. What we verified before coding (AGENTS.md §14)

Everything below was checked against official sources on **2026-09-29**. Several findings contradicted what a model trained earlier would "remember"; those are marked ⚠️.

### Model provider layer: LiteLLM 1.103.0 ([PyPI](https://pypi.org/project/litellm/), [docs](https://docs.litellm.ai/docs/completion/input))
- ⚠️ **Import-time download.** By default it downloads its model/capability map on import, so behaviour can change daily. We pin `LITELLM_LOCAL_MODEL_COST_MAP=True`.
- ⚠️ **Retries.** The OpenAI path retries twice on its own. We pass `num_retries=0` so ours are the only retries.
- ⚠️ **Silent zero cost.** For models missing from its bundled map, `response_cost` is **0.0 with no warning**. That's why we keep our own price table.
- ⚠️ **Token counting on Windows.** `token_counter` fails offline on Windows (the bundled tiktoken files have CRLF line endings; [issue #41855](https://github.com/BerriAI/litellm/issues/41855)). Hence the byte upper bound.
- **Structured output.** It goes through `response_format`, and the JSON lands in `choices[0].message.content`.
  - For Anthropic, LiteLLM uses native structured output only if its map says the model supports it. Otherwise it uses a forced tool call, which Claude 5.x models reject with a 400. See ADR-0003.
- **Usage.** `usage.prompt_tokens` includes cache reads and writes for Anthropic, and cached tokens are in `prompt_tokens_details.cached_tokens`. The resolved model is in `response.model`.
- **Testing.** `mock_response` works offline, including mocked errors such as `"litellm.RateLimitError"`.

### Candidate models ([Anthropic](https://platform.claude.com/docs/en/about-claude/pricing), [OpenAI](https://developers.openai.com/api/docs/pricing), [Google](https://ai.google.dev/gemini-api/docs/pricing))

| Model | $/M in / out | Training cutoff | Logprobs | Temperature |
|---|---|---|---|---|
| Claude Opus 5.5 | 4 / 20 | Jun 2026 | no | only 1.0 accepted |
| Claude Sonnet 5.5 | 2 / 10 | Jun 2026 | no | non-default values → 400 |
| Claude Haiku 4.5 | 1 / 5 | Jul 2025 | no | yes; retiring ≥ 2026-10-15 |
| GPT-6 Sol | 2 / 10 | Apr 2026 | only at `reasoning_effort: none` | same condition |
| GPT-6 Luna | 0.10 / 0.50 | May 2026 | only at `reasoning_effort: none` | same condition |
| Gemini 3.8 Flash | 0.75 / 3.75 (until 2026-12-31) | Mar 2026 (some domains Jan 2025) | chosen token only via LiteLLM | docs say strip it |

What this means for the project:
- ⚠️ **Temperature 0 is effectively gone** on current frontier models. Determinism is measured, not assumed (ADR-0004).
- ⚠️ **The data window depends on which models we pick.**
  - With any Claude 5.x model, `data_start_date` must be 2026-07-01 or later.
  - An OpenAI-only set allows 2026-05-19 or later.
- **The logprob arm of E6** is only confirmed feasible on GPT-6 Sol/Luna.

### MCP ([spec changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog), [Python SDK](https://py.sdk.modelcontextprotocol.io/), [migration guide](https://py.sdk.modelcontextprotocol.io/migration/))
- **Spec.** The current version is `2026-07-28`, and the protocol is now stateless:
  - the `initialize` handshake is removed, and servers must implement `server/discover`;
  - `Mcp-Session-Id` is removed;
  - sampling, roots and logging are deprecated.
- ⚠️ **Python SDK `mcp` 2.2.0.** `FastMCP` was renamed to **`MCPServer`** (`from mcp.server import MCPServer`), and `create_connected_server_and_client_session` was removed.
  - For in-process tests, pass the server object straight to `Client`: `async with Client(server) as c`.
- **Tools.** `@mcp.tool()` builds the schema from type hints and the docstring, and the return annotation becomes `output_schema`.
  - Annotations are passed like `ToolAnnotations(read_only_hint=True)`; they are hints, not guarantees.
- **Inspector.** It needs Node ≥ 22.19. Launch it with `uv run mcp dev server.py` or `npx @modelcontextprotocol/inspector uv run server.py`.

### Agent Skills ([specification](https://agentskills.io/specification), [client guide](https://agentskills.io/client-implementation/adding-skills-support))
- **`name`:** 1–64 characters of `[a-z0-9-]`, and it **must match the directory name**.
- **`description`:** 1–1024 characters. It should say what the skill does *and when to use it*.
- **Optional fields:** `license`, `compatibility`, `metadata`, and `allowed-tools` (experimental).
- **Progressive disclosure has three levels:**
  - metadata (about 100 tokens) at startup;
  - the body (under 5k tokens) on activation;
  - `references/`, `scripts/` and `assets/` on demand, kept one level deep.
- **Client guidance for our `load_skill`:** take the name as an enum, strip the front matter, list the bundled files without reading them, protect skill content from compaction, and deduplicate repeat activations.
- **Validator:** `skills-ref validate` ([repo](https://github.com/agentskills/agentskills/tree/main/skills-ref)).

### GitHub API ([REST issues](https://docs.github.com/en/rest/issues/issues), [timeline](https://docs.github.com/en/rest/issues/timeline), [GraphQL changelog](https://docs.github.com/en/graphql/overview/changelog), [rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api))
- **Duplicates:**
  - REST `state_reason` can be `duplicate` (since 2025-07).
  - GraphQL has `IssueClosedStateReason.DUPLICATE` and `Issue.duplicateOf` (since 2025-05-22).
  - ⚠️ The REST `marked_as_duplicate` event **does not contain the original issue's number**. GraphQL's `MarkedAsDuplicateEvent.canonical` does, so T2 ground truth uses GraphQL.
- **Closing PRs:** `Issue.closedByPullRequestsReferences(includeClosedPrs: true)`, then `PullRequest.files` for the changed paths.
  - Whether merged PRs are included is **unverified**; test it at M1.
- **Filtering:**
  - drop pull requests from the issues endpoint with the `pull_request` key;
  - spot bots with `actor.type == "Bot"` (REST) or `__typename == "Bot"` (GraphQL).
- **Rate limits:** 5,000 requests per hour (REST) and 5,000 points per hour (GraphQL), plus secondary limits.
  - Back off using `retry-after`, else `x-ratelimit-reset`, else at least 60 s followed by exponential backoff.

### Jev / TypeSafe AI ([docs](https://docs.typesafe.ai/introduction), [llms.txt](https://docs.typesafe.ai/llms.txt), [known failure modes](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md))
- **Primitives:** `choice`, `score` and `noul` (the yes/no one) via `POST /v1/systemone`.
  - The model version is returned in `model`, e.g. `jev-1.13.0`.
  - SDK `typesafe-sdk` 0.7.2, env var `TYPESAFE_API_KEY`.
  - $0.042 per million input tokens; output is free.
- ⚠️ **Confidence fields:**
  - `noul` returns only P(yes), with **no confidence field**.
  - Choice/score `confidence` is a *concentration statistic* of the probabilities; the docs don't claim it is calibrated.
  - For H5, analyse the probabilities, not `confidence`.
- ⚠️ **Mismatch with AGENTS.md §11:**
  - `score(lo, hi)` doesn't map onto Jev's score, which uses 2–10 rubric levels;
  - multi-label needs one `noul` per label.
- **Known failure modes that matter for triage:**
  - comparing dates is unreliable (so do date logic in code);
  - lots of irrelevant input hurts accuracy (so trim logs);
  - adversarial text can move the answer (prompt injection, E9);
  - a `noul` and its negation needn't sum to 1.
- **LLM adapter:** TypeSafe publishes `system-one-adapter` 0.2.1. The ADR choosing between it and our own adapter is due at M7.

### GitHub Actions (each action's releases page)
| Action | Version | SHA |
|---|---|---|
| `actions/checkout` | v7.0.1 | `3d3c42e5…` |
| `astral-sh/setup-uv` | v10.2.0 | `c18668ad…` |

- setup-uv's `enable-cache: auto` turns caching off for tag pushes, releases and `pull_request_target`, to prevent cache poisoning.
- Dependabot supports `uv` natively.

---

## 3. How the two exercises were solved

**`deep_merge`** (`config.py`):
- Start from `copy.deepcopy(base)`.
- For each key in `override`: if both sides are dicts, recurse; otherwise take a deep copy of the override value.
- **The trap:** `dict(base)` is only a *shallow* copy. A key present only in `base` would hand back the *same* nested dict, so editing the merged config would silently edit the parent too. `test_deep_merge_result_shares_nothing_with_base` pins this down.
- **Why lists replace instead of concatenating:** an experiment must be able to *remove* a tool by restating the list.

**`backoff_delay`** (`retry.py`):
- The formula is `rng.uniform(0, min(cap, base * 2 ** attempt))`.
- The exponent is clamped at 60, because `2.0 ** 1100` raises `OverflowError`, and past ~2⁶⁰ the cap wins anyway.
- The random source is injected, so a test can pin it to the ceiling (`_MaxRng`) or seed it.

## 4. Pitfalls (most of these actually happened during M0)

1. **Path separators leak into hashes.** On Windows, `Path` serialized as `configs\prices.yaml`, so the same config fingerprinted differently per OS. Fix: `PortablePath` serializes as POSIX (commit `fix(config): …`).
2. **Timestamp IDs collide.** Two runs started in the same second got the same ID and the second one crashed. Fix: claim the folder with an atomic `mkdir` loop and add `-2`, `-3` suffixes (commit `fix(registry): …`).
3. **CRLF from Python on Windows.** `Path.write_text` translates `\n` to `\r\n`. `.gitattributes` (`eol=lf`) and the `mixed-line-ending` hook catch it.
4. **pre-commit stashes unstaged changes, not untracked files.** A whole-project hook like pyright can see a half-state: a new untracked file next to the *old* version of a file it depends on. Commit dependencies before the files that use them.
5. **Caching sampled outputs.** At temperature > 0, a naive cache turns "5 samples" into "1 sample replayed 5 times". The `sample` index in the key prevents that.
6. **Trusting the library's cost.** LiteLLM reports $0.00 for models it doesn't know, with no warning. A budget built on that number never trips.
7. **Nested retries.** SDK retries (e.g. 3 attempts) times ours (4) is 12 attempts, and they're invisible. Keep exactly one retry layer.
8. **Silently dropped parameters.** With `drop_params=True`, a `seed` you think you sent isn't sent, and your "seeded" run isn't seeded.
9. **Knowledge from memory is stale.** The MCP SDK renamed `FastMCP` and removed the old test helper. Verify first (§14).

---

## 5. How an interviewer might probe this

- *"How do you enforce a hard spend cap when you don't know how long the output will be?"* → `max_tokens` bounds the output exactly, and bytes bound the input. Check the worst case before the call and charge the actual cost after.
- *"Why not count tokens with tiktoken?"* → Every provider tokenizes differently, tokenizers need downloads, and an estimate can under-count. An upper bound can't under-count, and a budget check only needs a bound.
- *"What goes into your cache key, and what would break if you added the timeout? Or left out the schema?"*
  - Timeout in the key: needless misses.
  - Schema left out: a structured request could get an unstructured cached answer.
  - Sample index left out: consistency samples collapse into one.
- *"LLMs aren't deterministic. How can your results be reproducible?"* → Cached responses make *re-runs* reproducible. Variance *across samples* is measured (pass^k, agreement) and reported, not wished away.
- *"Why full jitter instead of plain exponential backoff?"* → To break retry synchronization, the "thundering herd".
- *"Why pin GitHub Actions by SHA?"* → Tags are mutable, and a compromised tag can inject code into your pipeline. SHAs are immutable, and Dependabot keeps them fresh.
- *"Why wrap LiteLLM in your own protocol?"* → Testability (a fake backend), a single place for provider quirks, and the freedom to swap it out. The cost is one small adapter.

---

## 6. Self-check questions

1. `BudgetGuard.check` is called with a projection built from `prompt_tokens_upper_bound`. Name two ways the *actual* cost could still exceed the projection, and say why neither is possible here.
2. You run the same `llm ping` on Windows and in CI on Linux. What guarantees the cache key and config fingerprint are identical?
3. A test marked `@pytest.mark.your_turn` fails with `AssertionError`. Does CI go red? Why?
4. Why does `call_with_retries` take `delay` as a function instead of calling `backoff_delay` directly?
5. What breaks if LiteLLM's retries are left on *and* ours are on?

<details><summary>Answers</summary>

1. The two ways are (a) more output tokens than projected and (b) more input tokens than projected. (a) can't happen, because the provider stops at `max_tokens` and the projection assumes the full `max_tokens` at the output rate. (b) can't happen, because at most one token per UTF-8 byte (plus fixed overhead) is a ceiling for byte-level tokenizers. The projection also ignores cache discounts, which can only lower the real cost.
2. `canonical_json` sorts keys and uses fixed separators and UTF-8. Paths serialize as POSIX through `PortablePath`. `.gitattributes` keeps every checked-in file LF on both OSes. Nothing machine-specific (timeouts, absolute paths in the request) goes into the key.
3. Yes. `conftest.py` applies `xfail(raises=NotImplementedError)`, so only `NotImplementedError` is tolerated. An `AssertionError` means the implementation exists but is wrong, and that's a real failure.
4. Dependency injection. The loop's own tests stay deterministic (no real sleeping, no randomness), and the policy (how long to wait) is separated from the mechanism (when to retry).
5. The attempts multiply (e.g. 3 × 4 = 12), the retries LiteLLM does are invisible to our traces and stats, the `attempts`/`retries` numbers in cost.json are wrong, and the overall latency is unpredictable.

</details>
