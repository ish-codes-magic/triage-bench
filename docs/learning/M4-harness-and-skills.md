# M4: The agent harness, skills and tracing

**What M4 built:**
- our own agent loop;
- a synchronous MCP client for `repo-intel`;
- Agent Skills with progressive disclosure, plus a CPython skill and a generic one;
- per-issue budgets, context compaction and a validated final answer;
- tracing to JSONL and OpenTelemetry (Phoenix);
- CI that replays recorded model responses through the whole stack.

**Why it matters:** this is the part agent frameworks hide. Writing it by hand exposes exactly the choices the later experiments measure (E2 skills, E3 tools vs. stuffing, E4 architecture, E5 model size).

```
AgentTriager.triage(issue)                                   harness/agent.py
  system prompt: role + untrusted-input rule + <available_skills> catalog
  user message:  same vocabulary + <issue> block as the single-shot baseline (prompting.py)
  Toolbox (per issue)                                        harness/tools.py
    MCP tools   -> McpSession (anyio portal) -> repo-intel (stdio subprocess)
                   as_of hidden from the schema, injected = issue.created_at
    skill tools -> load_skill / read_skill_file (SkillSet)   skills/loader.py
  run_loop                                                   harness/loop.py
    compact -> LLM call (tools + submit_triage) -> execute calls -> append results
    submit_triage validates -> done | error fed back (<= 2 retries)
    near a budget: tool_choice=submit_triage                 harness/budgets.py
  IssueTrace: JSONL events + OTel spans (AGENT > LLM, TOOL)  harness/tracing.py
```

---

## 1. Concepts, and where they live

| Concept | What to take away | Code |
|---|---|---|
| **The agent loop** | A `while` loop around a model call. Everything interesting lives in the stopping rules: a valid answer, a forced answer near a budget, a nudge for text replies, a validation retry cap. | `harness/loop.py`: `run_loop` |
| **Final answer as a tool** | `submit_triage`'s parameters are the answer schema. One protocol for everything; a validation error becomes that tool's result. | `loop.py`: `submit_tool`, `_validate` |
| **Schema inlining** | Pydantic emits `$defs`/`$ref`. Small models follow flat schemas better, so refs are expanded and titles dropped. | `loop.py`: `inline_schema` |
| **Harness-injected arguments** | `as_of` never appears in a schema the model sees; the harness sets it on every call, overriding the model. Leakage control lives in code, not the prompt. | `harness/tools.py`: `hide_arguments`, `McpTool` |
| **Never-raising tools** | Bad JSON, unknown tools and server refusals come back as error *results*, so one confused step can't kill an issue. | `tools.py`: `Toolbox.execute` |
| **Sync over async** | An anyio blocking portal runs the async MCP client in one background loop; worker threads submit calls to it. | `harness/mcp_client.py`: `McpSession` |
| **Progressive disclosure** | The catalog costs about 60 tokens; the body arrives on `load_skill`; reference files arrive on `read_skill_file`. | `skills/loader.py`: `SkillSet` |
| **Budgets with a soft edge** | The step *before* a limit forces the answer; the hard stop returns a recorded fallback. | `harness/budgets.py` |
| **Replay-stable accounting** | Cached responses count at their original cost and tokens, or a replay would decide differently. | `BudgetTracker.record_call` |
| **Deterministic compaction** | Elide the oldest tool results into stubs instead of asking a model to summarise. | `harness/context.py`: `compact` |
| **Traces as data** | JSONL events are the source of truth; OTel spans (OpenInference names) are for browsing. | `harness/tracing.py` |
| **Cassettes** | The response cache doubles as recorded fixtures; `replay_only` turns a miss into a hard CI failure. | `llm_client.py`: `ReplayOnlyBackend`; `tests/smoke_dataset.py` |
| **Cache-key compatibility** | New optional fields are omitted when empty, so old requests keep their keys; a test pins one. | `llm_client.py`: `_omit_empty` |

## 2. What we verified before coding (§14, 2026-09-30)

- **MCP Python SDK 2.2.0 (installed source):**
  - `Client(server | StdioServerParameters | transport)` is an async context manager with no sync wrapper;
  - `list_tools()` and `call_tool()` return snake_case models (`input_schema`, `structured_content`, `is_error`);
  - on Windows a stdio child gets only a minimal environment (`PATH`, `TEMP`, ...), sits in a Job Object, and is killed 2 s after stdin closes.
- **Agent Skills spec** ([agentskills.io/specification](https://agentskills.io/specification), last changed 2026-08-04):
  - `name` is 1-64 characters of `a-z0-9-`, with no leading, trailing or double hyphens, and must match its folder;
  - `description` is at most 1,024 characters and says what the skill does and when to use it;
  - optional fields: `license`, `compatibility`, `metadata`, `allowed-tools`;
  - keep the body under 500 lines and references one level deep;
  - the [client guide](https://agentskills.io/client-implementation/adding-skills-support.md) recommends lenient loading, an `<available_skills>` catalog, listing resources without reading them, and exempting skill content from pruning.
- **OpenRouter endpoints** (`/api/v1/models/<id>/endpoints`):
  - 9B @ DeepInfra/bf16 supports `tools` and `tool_choice`, which the agent needs;
  - 9B @ Parasail/bf16 has **no tools**, which is fine for M7 decisions;
  - 27B @ Alibaba reports quantization `unknown`, so a `bf16` filter would drop it;
  - no endpoint lists `parallel_tool_calls`, so we never send it;
  - [tool-calling docs](https://openrouter.ai/docs/guides/features/tool-calling.md): arguments are JSON strings, results use `role: tool` + `tool_call_id`;
  - [reasoning docs](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens.md): preserving reasoning is *recommended* for tool loops ("models like Claude"), not required.
- **LiteLLM 1.103.0:**
  - `message.tool_calls[i].function.arguments` is a string;
  - OpenRouter's `reasoning` field arrives as `message.reasoning_content`;
  - `usage.completion_tokens_details.reasoning_tokens` is kept.
- **Tracing:**
  - Phoenix 20.16.0 runs with `phoenix serve`; the UI and OTLP/HTTP are on `:6006/v1/traces`, backed by SQLite;
  - its REST API has `GET /v1/projects/{id}/spans`;
  - Langfuse self-hosting needs six containers with documented minimums totalling about 25 GiB;
  - [OpenInference conventions](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md): `openinference.span.kind` (LLM, TOOL, AGENT, ...), `llm.token_count.*`, `llm.input_messages.{i}.message.*`, `tool.name`.

## 3. Results (dev, n = 100, silver labels; `reports/results/dev.md`, `reports/agent/dev-agent-v1.md`)

| system | T1 micro-F1 | T2 link F1 | T3 acc | T3 top-3 | T4 F1 | $/issue | p50 |
|---|---|---|---|---|---|---|---|
| TF-IDF classifier | 0.71 [0.64, 0.77] | 0.11 [0.00, 0.32] | 0.65 | 0.94 | 0.09 | $0 | 0.1 s |
| Qwen3.5-9B single-shot, thinking | 0.69 [0.63, 0.74] | 0.00 | 0.76 | 0.93 | 0.20 | $0.00026 | 23 s |
| **Agent v1** (CPython skill, repo-intel) | 0.72 [0.66, 0.77] | **0.43 [0.13, 0.67]** | 0.72 | 0.80 | 0.08 | $0.0072 | 164 s |

**Paired differences, agent minus baseline** (bold: the interval excludes 0):

| metric | vs. classifier | vs. single-shot (thinking) |
|---|---|---|
| T1 micro-F1 | +0.008 [−0.063, +0.085] | +0.031 [−0.022, +0.081] |
| T2 link F1 | **+0.330 [+0.082, +0.578]** | **+0.435 [+0.125, +0.667]** |
| T3 accuracy | +0.074 [−0.086, +0.220] | −0.037 [−0.164, +0.086] |
| T3 top-3 | **−0.148 [−0.245, −0.064]** | **−0.130 [−0.239, −0.025]** |
| T4 F1 | −0.004 [−0.230, +0.222] | −0.117 [−0.287, +0.048] |

**What it means:**
- **Retrieval is what the agent buys.** It is the only system that finds duplicates' originals: link-F1 0.43, against 0.11 for nearest-neighbour search and 0 without tools.
- **On labels and components, no evidence of a gain** over a free classifier, at about 28× the single-shot cost and 7× its latency.
- **The top-3 drop is a schema defect, not a capability gap.** `component_top3` was optional, so the agent named a single component on 77% of issues, while single-shot (where it's required) gives three. Next iteration: make it required.
- **Needs-info is weak everywhere** (F1 ≤ 0.20). The label is noisy and rare; M5's gold labels will show how much of that is label noise.

**How the agent behaved** (`triagelab runs stats`):
- **Skill load rate: 1%** (1 of 100 issues called `load_skill`). Progressive disclosure was almost never used, so this run is effectively "no skill".
- **53 of 100 answers were forced** by the step budget (52 × `max_steps`, 1 × `max_tool_calls`), with 9.4 tool calls per issue: search thrash.
- **0 validation errors** after the `"None"` fix, and 0 compactions (prompts stayed under about 24k tokens).
- **Cost:** 69k input tokens per issue; $0.72 for the whole dev set. p50 latency (164 s) includes OpenRouter 429 back-offs: 9 issues needed the retry pass and 5 a resume, both nearly free thanks to the cache.

## 4. Pitfalls (these happened in M4)

1. **The model doesn't load the skill.** It happened in 0 of 3 first issues, even with "call load_skill first" in the prompt. Progressive disclosure assumes the model *chooses* to disclose; a 9B model often doesn't.
2. **Query thrashing.** One issue ran 10 near-identical searches ("statistics.quantiles ...") until the step budget forced an answer. Without a stopping criterion, "more searching" is always locally attractive.
3. **Null spelled as text.** Qwen wrote `"duplicate_of": "None"`, and each one cost a validation round-trip. We fixed it with a narrow before-validator, not a looser schema.
4. **A refusal that leaked, or would have.** "#N is not visible" read as "exists later". The fix gives one message for later, PR and pre-index issues, and a test proves they're identical.
5. **Budgets vs. replay.** Counting cache hits as $0 would trip the cost limit at a different step during replay and break determinism.
6. **CRLF in recorded files.** Python text mode wrote CRLF on Windows. Cassettes must be byte-identical across OSes, so the cache now writes `\n`.
7. **Pre-commit and untracked files.** Pre-commit stashes *unstaged* changes but leaves *untracked* files, so pyright type-checked a new test against an old module. Commit in dependency order, parking new files if needed.
8. **The recording ledger.** The smoke configs used a private spend ledger; a recording run would have spent money invisibly to the $150 cap.
9. **Optional fields get omitted.** Giving `component_top3` a default meant the model usually skipped it, which quietly turned top-3 accuracy into top-1. In a tool schema, "optional" reads as "skip me". Require what you intend to score.
10. **Partial runs in the results table.** A later `--limit 3` demo run would have replaced the full dev run's row. The table now keeps the most complete run per config.

## 5. How an interviewer might probe this

- *"Why write your own loop instead of using a framework?"* → Every number in E2-E5 depends on what the loop does at its edges: budgets, retries, context, forced answers. Frameworks make those choices silently; here each is a tested, traced function.
- *"How do you stop the agent from time-travelling?"* → Three layers: the corpus refuses later issues, the server has a ceiling, and the harness removes `as_of` from the schema and injects it. The prompt is never the control.
- *"How do you test an LLM agent deterministically in CI?"* → Record responses once into a content-addressed cache and replay them read-only through the real stack; any unrecorded request fails. Ours were recorded on Windows and replay on Linux.
- *"What happens when the model returns malformed output?"* → The validation error goes back as the submit tool's result, up to 2 retries. After that the issue is scored as a fallback with its reason, never silently dropped.
- *"How would you handle a 10x longer conversation?"* → Truncate results at source, elide the oldest results (never skills or the issue), and log every compaction. An LLM summary is the next step, but it costs a call and reproducibility.

## 6. Try it yourself (optional exercises)

1. **Force skill loading.** Add a config flag that makes the first call `tool_choice=load_skill`. Compare the skill load rate and T1 on 20 dev issues with `runs stats` and `compare`.
2. **Stop the thrash.** In `Toolbox.execute`, detect a repeated call (same tool, near-identical arguments) and return "you already searched this; decide or try a different angle". Does `tool_calls_mean` fall without hurting T2?
3. **Watch it in Phoenix.** `uvx --from arize-phoenix phoenix serve`, then set `tracing.otlp_endpoint: http://localhost:6006/v1/traces` and re-run 5 issues. The model calls come from cache, so it's free.

## 7. Self-check questions

1. Why is the final answer a tool call rather than a JSON reply?
2. The model passes `as_of` for a date in the future. What happens, and at which layer?
3. Why do budgets count a cached response at its original cost?
4. Why does compaction never elide skill content or the most recent results?
5. A PR changes one word of `SKILL.md`. What does CI do, and why is that desirable?

<details><summary>Answers</summary>

1. One protocol covers every step, and schema validation errors can go back to the model as the tool's result. A forced final call is just `tool_choice=submit_triage`.
2. The schema the model sees has no `as_of`, and `McpTool` overwrites any value the model sends with the issue's creation time. Even without that, the corpus and the server ceiling would refuse later issues.
3. So a replay makes the same decisions as the recorded run. Counting hits as free would change when the cost limit forces an answer, which changes every later request and misses the cassettes.
4. Skill content is the instructions the model is following (the spec's client guide says to exempt it). The last results are what the model is reasoning about right now. Old search results are the cheapest to re-fetch.
5. The system prompt's skill catalog or the loaded body changes, so the requests' cache keys change, the replay backend raises `CassetteMissError`, and the job fails. A prompt change can't slip through untested; you re-record deliberately (about 5 cents).

</details>
