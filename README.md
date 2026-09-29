# triagelab

**An eval-driven GitHub issue-triage system.** A cheap, typed decision model handles routine calls. An LLM agent with MCP tools and repo-specific Agent Skills handles the hard ones. Every design choice is justified by measurement: accuracy with confidence intervals, calibration, cost and failure analysis.

[![CI](https://github.com/ish-codes-magic/triage-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/ish-codes-magic/triage-bench/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![pyright strict](https://img.shields.io/badge/types-pyright%20strict-informational)
![ruff](https://img.shields.io/badge/lint-ruff-informational)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> **Status: foundations complete (M0 of 10).** The results table, cascade curve and findings land from M2 onward. Nothing below is a claimed result yet, and negative results will be reported as prominently as positive ones.

---

## The question

Most LLM demos show that something *works*. This project asks **when it is worth it**, and tests five hypotheses instead of assuming them:

| | Hypothesis |
|---|---|
| **H1** | Repo-specific Agent Skills beat generic instructions, at an acceptable token cost. |
| **H2** | Retrieving context on demand via MCP tools beats stuffing it into the prompt, on both accuracy and cost. |
| **H3** | A typed decision model with confidence-based escalation matches the full agent on routine decisions at a fraction of the cost. |
| **H4** | The harness transfers to a new repository by swapping only the skill. |
| **H5** | Each decision backend's confidences are (or are not) well calibrated in this domain. |

**Tasks:**
- issue labels (T1)
- duplicate detection (T2)
- component routing (T3)
- needs-more-info detection (T4)
- a draft triage comment (T5), scored by an LLM judge that is itself validated against human labels

Ground truth comes from real maintainer actions on public repositories. Every input is frozen at issue-creation time, and tests enforce that no later information leaks in.

## Architecture

```mermaid
flowchart LR
    I["Issue snapshot<br/>(as of creation)"] --> D{"Decision layer<br/>Jev · LLM · classifier"}
    D -- "confidence ≥ τ" --> R[TriageResult]
    D -- "confidence < τ" --> A["Agent harness<br/>(own loop)"]
    A <--> S["Agent Skills<br/>progressive disclosure"]
    A <--> M["repo-intel MCP server<br/>hybrid retrieval, as_of-guarded"]
    A --> R
    R --> E["Scorers → run registry<br/>CIs · calibration · cost · failures"]
```

- **Evaluation is offline and frozen:** dataset snapshots, a local index, and cached model responses, so any run can be reproduced exactly.
- **The core is written from scratch:**
  - the agent loop
  - progressive skill loading
  - the cascade policy
  - every metric, including bootstrap CIs and calibration

  This is deliberate: the point is to understand what agent frameworks hide.

## Engineering highlights (built so far)

- **A budget hard stop that can't be overshot.**
  - Before every call, the worst-case cost (`max_tokens` at the output rate, plus a provable byte-based ceiling on prompt tokens) is checked against both the per-run and all-time caps.
  - The actual cost is charged afterwards and appended to a spend ledger.
  - Prices come from a reviewed table that cites its sources, not from a library's silently changing map. → [ADR-0005](docs/DECISIONS.md#adr-0005-our-own-price-table-and-a-worst-case-budget-check)
- **A content-addressed response cache.**
  - Keys cover only what can change the answer, plus a sample index so repeated samples for consistency measurement stay distinct.
  - Entries are written atomically.
  - The same files double as deterministic CI cassettes. → [ADR-0006](docs/DECISIONS.md#adr-0006-content-addressed-json-response-cache)
- **Pinned model routes.**
  - Small open-weight models (Qwen3.5-9B) are served via OpenRouter, with every call pinned to one provider *and* numeric precision. Otherwise one model name silently maps to fp4, fp8 and bf16 deployments.
  - Models whose training cutoff isn't published are dated by their release, so none can have seen the evaluation issues. → [ADR-0010](docs/DECISIONS.md#adr-0010-small-open-weight-models-via-openrouter-pinned-per-role)
- **The provider behind a protocol.**
  - LiteLLM lives in one adapter, with its import-time network fetch, hidden retries and silent parameter dropping all turned off.
  - Everything else is tested offline against a fake backend. → [ADR-0003](docs/DECISIONS.md#adr-0003-litellm-behind-our-own-client)
- **Run provenance.**
  - Every run records its resolved config, config fingerprint, git SHA (flagged if dirty), versions and cost.
  - Run folders are claimed atomically and never overwritten.
- **CI/CD as a first-class concern.**
  - SHA-pinned actions and a least-privilege token.
  - The same pre-commit hooks locally and in CI, with workflows linted by actionlint.
  - An Ubuntu + Windows test matrix, and Dependabot for both actions and the `uv` lockfile.
  - Planned: an LLM regression gate that posts paired-bootstrap metric deltas on PRs, and an approval-gated, audited one-time test-set evaluation.
- **Verify, don't remember.** Before any code, every external API was checked against current docs, and several contradicted older assumptions. → [M0 learning note](docs/learning/M0-foundations.md)

## Roadmap

- [x] **M0 Foundations:** config, cached and budgeted model client, run registry, CLI, hardened CI
- [ ] **M1 Data:** collection, creation-time snapshots, ground-truth derivation, time splits, leakage tests
- [ ] **M2 Baselines + scorers:** eval runner, metrics with bootstrap CIs, first results table
- [ ] **M3 MCP server + retrieval:** `repo-intel` server, hybrid BM25 + dense retrieval, `as_of` guard
- [ ] **M4 Harness + skills:** our own agent loop, progressive skill disclosure, tracing
- [ ] **M5 Gold labels, judge, failure taxonomy**
- [ ] **M6 Iteration loop + LLM regression gate in CI**
- [ ] **M7 Decision layer:** Jev, LLM and classifier backends, calibration, cascade
- [ ] **M8 Transfer repo + one-time test-set evaluation**
- [ ] **M9 Report, results site, demo**

## Quickstart

```bash
uv sync                          # Python 3.12 + locked dependencies
uv run triagelab --help
uv run triagelab config show     # the resolved config and its fingerprint

cp .env.example .env             # add OPENROUTER_API_KEY
uv run triagelab llm ping        # one structured call: logged, costed, cached
uv run triagelab llm ping        # the second one is a cache hit and costs $0
uv run triagelab runs list       # run registry and all-time spend vs. budget
```

Development:

```bash
uv run pre-commit install        # the same hooks CI runs
uv run pytest
```

## Repository layout

```
configs/            base.yaml, prices.yaml (verified, cited), experiments/ (one YAML per ablation)
src/triagelab/      config · cost · cache · ledger · retry · llm_client · litellm_backend · wiring · cli
  eval/             run registry (runner, metrics, calibration and judge arrive from M2)
docs/               DECISIONS.md (ADRs) · learning/ (one note per milestone)
.github/            CI workflow, composite setup action, Dependabot
tests/              unit and integration tests, offline by default
```

## License

MIT
