# M3: Retrieval and the repo-intel MCP server

**What M3 built:**
- a time-aware retrieval stack (corpus, our own BM25, dense embeddings, reciprocal rank fusion);
- a duplicate-retrieval benchmark;
- `repo-intel`, a read-only MCP server with five tools, tested in three layers (unit, in-process client, MCP Inspector);
- a frozen source checkout for code search.

**Why it matters:** duplicates (T2) are unsolvable without search, and components (T3) benefit from code lookup. M4's agent gets both through MCP. Every piece enforces the same rule as the snapshots: *nothing from after the issue's creation*.

```
issues.jsonl + index_history.jsonl ──(stream)──► Corpus (creation-time text + timeline)
      visible(as_of) = prefix of created_at-sorted docs
      ├─ TimeAwareBM25: posting lists; IDF/avgdl from the visible prefix only
      ├─ DenseIndex: arctic-embed-s vectors (resumable, keyed by issue #), prefix rows
      └─ reciprocal_rank_fusion(k=60) ──► HybridSearcher.search(query, as_of, k)
repo-intel (MCPServer, stdio) ── RepoIntel(lazy searcher, CodeSearcher, CodeOwners, ceiling)
      search_similar_issues · get_issue · search_code · get_codeowners · list_components
      all read_only_hint=True; as_of checked in the corpus and against an optional ceiling
```

---

## 1. Concepts, and where they live

| Concept | What to take away | Code |
|---|---|---|
| **Leakage by statistics** | Filtering results by date isn't enough. Global IDF and average document length let future documents shape past rankings. Compute them from the visible prefix. | `retrieval/bm25.py`: `TimeAwareBM25` |
| **Posting lists + bisect** | Docs sorted by time make "visible as of t" a prefix. `bisect_left` on each posting list gives the document frequency *at* t in O(log n). | `bm25.py`: `scores` |
| **Reciprocal rank fusion** | `Σ w/(k+rank)`. It fuses rankers with incomparable scores (BM25 vs. cosine) and rewards agreement. | `retrieval/fusion.py` |
| **Dense retrieval** | Normalised embeddings, cosine as a dot product. Time safety comes for free with prefix rows. | `retrieval/dense.py`, `retrieval/encoders.py` |
| **Resumable batch jobs** | 30 minutes of CPU embedding on a memory-starved laptop *will* be interrupted. Key outputs by stable id and write in chunks. | `retrieval/embeddings.py` |
| **Coverage vs. ranking** | Report retrieval both on all queries (what an agent faces) and on reachable ones (ranking quality). Growing the index moves the first and can lower the second. | `retrieval/evaluate.py` |
| **Paired comparison of retrievers** | Rank once and keep the lists (`Rankings`). Score each retriever, then bootstrap the *per-query* difference between two of them. Overlapping marginal intervals do not mean "no difference". | `evaluate.py`: `rank`, `score`, `compare` |
| **Atomic writes** | Write to `*.tmp`, then `replace()`. A kill mid-write leaves a stray temp file, never a truncated chunk that breaks every later load. | `embeddings.py`: `embed_corpus` |
| **MCP server design** | Read-only annotations, structured outputs, descriptions as versioned prompts, bounded outputs with truncation markers. | `mcp_server/server.py` |
| **Defence in depth for `as_of`** | Corpus refusal, a server ceiling, and (M4) the harness injecting `as_of` so the model can't choose it. | `retrieval/corpus.py`, `server.py`: `check_as_of` |
| **Lazy startup** | MCP clients wait about 15 s for the handshake. Load heavy state on first use, not at boot. | `server.py`: `RepoIntel.searcher` |
| **Frozen code** | Code search on a tree from before the eval window, so fixes can't leak through the code. | `data/checkout.py` |

## 2. Results (`reports/retrieval/python__cpython.md`)

**Setup:**
- 202 silver duplicates from train/dev, with the test window excluded.
- Each duplicate is searched as of its own creation, with itself excluded.
- 152 queries (75%) are *reachable*: the original is in the index at query time.
- 95% bootstrap intervals.

| reachable queries | Recall@1 | Recall@10 | MRR |
|---|---|---|---|
| BM25 | 0.37 [0.30, 0.45] | 0.65 [0.57, 0.72] | 0.47 [0.40, 0.54] |
| dense (arctic-embed-s) | 0.54 [0.45, 0.62] | 0.76 [0.70, 0.83] | 0.62 [0.55, 0.69] |
| hybrid (RRF) | 0.52 [0.44, 0.60] | 0.76 [0.68, 0.82] | 0.61 [0.55, 0.68] |

**Paired differences on the same queries** (bold: the interval excludes 0):

| B − A | MRR | Recall@10 |
|---|---|---|
| dense − BM25 | **+0.144 [+0.079, +0.212]** | **+0.112 [+0.052, +0.178]** |
| hybrid − BM25 | **+0.143 [+0.102, +0.189]** | **+0.105 [+0.053, +0.158]** |
| hybrid − dense | −0.002 [−0.046, +0.042] | −0.007 [−0.046, +0.033] |

**What it means:**
- **Embeddings help a lot.** Duplicates often describe the same bug in different words, and BM25 can't bridge that gap.
- **Fusion added nothing over dense** on whole-issue queries. That's a mild negative result. Hybrid stays the server default (ADR-0023) because agent-written queries will be short and identifier-heavy, and that gets re-measured in M4.
- **The query prefix made no difference** (`python__cpython-query-prefix.md`). Issue-vs-issue search is symmetric, so an asymmetric "question" prefix has nothing to fix.
- **Over all queries** (what an agent faces), hybrid Recall@10 is 0.57. The ceiling is 0.75, because a quarter of originals predate the index.

## 3. What we verified before coding (§14: MCP SDK v2, checked 2026-09-29 in the installed source)

- **Server:**
  - `from mcp.server import MCPServer`;
  - tools via `@mcp.tool(...)` or `mcp.add_tool(fn, annotations=, description=)`;
  - the return annotation becomes the output schema (`structured_content`).
- **Errors:** raising `mcp.server.mcpserver.exceptions.ToolError` becomes an `is_error` result; unexpected exceptions are logged and also returned as `is_error`.
- **Annotations:** `from mcp.types import ToolAnnotations` with snake_case fields (`read_only_hint`, …).
- **In-process tests:** `async with Client(server)` connects over an in-memory transport. `call_tool` returns `.structured_content` / `.is_error`. Async tests use anyio's pytest plugin.
- **MCP Inspector CLI** (Node ≥ 22.19):
  - ⚠️ put the **server command first** and the Inspector flags after it: `inspector --cli <cmd> -e K=V --method tools/list`;
  - flags on the server command are swallowed, which is why the server reads `REPO_INTEL_*` environment variables;
  - the default connect timeout is 15 s, which is why the index loads lazily.
  - The whole check is `scripts/mcp_inspector_check.sh`.
- **CODEOWNERS:** gitignore-style without `!`, `[ ]` or `\#`; the last match wins; `.github/`, then the root, then `docs/`.

## 4. Pitfalls (these happened in M3)

1. **Global corpus statistics leak.** Off-the-shelf BM25 would have let future issues shape past rankings, so we replaced `rank-bm25`.
2. **Coverage caps retrieval.** With history from May 2025 only, half of all duplicate originals were unreachable. Extending the index to 2024 raised reachability from 50% to 75%.
3. **More history means harder ranking.** Reachable-query Recall@10 *fell* (0.77 → 0.65) as distractors doubled, even though all-query recall rose.
4. **Slow startup breaks MCP clients.** Loading about 12k issues before the handshake timed out the Inspector.
5. **Tool CLIs eat arguments.** The Inspector swallowed `-m`/`-p`, and Python then read JSON-RPC from stdin as code (`NameError: name 'true'`).
6. **The Windows exe lock.** `uv add` can't reinstall `triagelab.exe` while a long job is running. Use `uv add --no-sync` plus `uv pip install`, and `UV_NO_SYNC=1`.
7. **Test fixtures that move time.** Shifting an issue's `created_at` without its creation revision (or its events) makes the snapshot check refuse it, correctly. Twice.
8. **"Which ripgrep?"** `rg` worked in one shell because it was bundled with the tooling, not installed. Code search therefore has a Python fallback.
9. **Long jobs get killed. Plan for it.** The embedding build was stopped twice under memory pressure. It survived because vectors are keyed by issue number and each chunk is written atomically. The finish was run in capped foreground slices (`timeout 570 …`); each slice resumed from the saved chunks.
10. **Reading marginal intervals side by side.** BM25's and dense's Recall@1 intervals nearly touch ([0.30, 0.45] vs. [0.45, 0.62]), which looks borderline. The paired test on the same queries is decisive. Always compare systems with the paired test.

## 5. How an interviewer might probe this

- *"Your index only contains past issues. Is that enough to prevent leakage?"* → No. Collection statistics (IDF, average length) must also come from the past only. Show `test_future_docs_never_change_past_rankings`.
- *"Why RRF instead of a weighted sum of scores?"* → BM25 is unbounded and cosine sits in [−1, 1]. A weighted sum needs per-query calibration, while RRF uses ranks and rewards agreement.
- *"How do you stop an agent from peeking at the future through a tool?"* → The server enforces it: corpus refusal plus a ceiling, and the harness injects `as_of`. The prompt is never the control.
- *"What would you change for 10× the corpus?"* → Keep the posting lists, add a vector index (FAISS or HNSW) with time-partitioned shards, and cache the tokenisation.
- *"How do you test an MCP server?"* → Unit tests for the parts, a real in-process MCP client against the real server, and a scripted Inspector run.
- *"Hybrid didn't beat dense. Why keep it?"* → It ties dense on these queries and is more consistent against BM25. Production queries (short and agent-written) differ from the benchmark's whole-issue queries, so the choice is re-measured on M4 traces (ADR-0023). Report the tie, don't hide it.
- *"Why version tool descriptions?"* → They are prompts. Rewording one changes how the model uses the tool, so every result must trace back to the exact wording (`TOOLS_VERSION`).

## 6. Try it yourself (optional exercises)

1. **Weighted fusion.** `reciprocal_rank_fusion` takes `weights`. Give dense twice BM25's weight in `HybridSearcher.search` and re-run `triagelab retrieval eval`. Does hybrid - dense become positive, and is it significant?
2. **Agent-shaped queries.** In `duplicate_queries`, use only the title as the query text. Predict first: does the gap between BM25 and dense widen or shrink? Does hybrid now beat dense?
3. **One more metric.** Add `("recall", 1)` to `COMPARED`. Which paired differences stay significant at the top-1 cut-off?

## 7. Self-check questions

1. Why does `bisect_left(posting, n_docs)` give a term's document frequency "as of" a time?
2. Adding 6,400 older issues raised all-query Recall@10 but lowered reachable-query Recall@10. How can both be true?
3. Why must the M4 harness inject `as_of` itself, even though the server already filters by it?
4. Why is dense retrieval time-safe "by construction" while BM25 needed extra care?
5. BM25's and dense's Recall@1 intervals nearly overlap, yet the paired test says dense is clearly better. How can both be true?

<details><summary>Answers</summary>

1. Documents are indexed oldest-first, so each posting list is sorted by document index, and "visible as of t" means document indices < n. `bisect_left` counts how many postings fall below n.
2. All-query recall counts every duplicate, and many became *reachable* only with the older history. Reachable-query recall is computed over a larger, harder set (older originals, twice the distractors), so ranking quality on that set can drop while overall success rises.
3. The server filters by the `as_of` it's given. If the model chose `as_of`, it could pass a later date and legally receive future issues. Injecting `as_of` removes that degree of freedom.
4. A document's embedding depends only on that document, so a visible prefix of rows can't be influenced by later rows. BM25 scores depend on collection statistics (IDF, average length) that span documents.
5. Each marginal interval includes query-difficulty variance: some duplicates are easy for everyone, others impossible. The paired test resamples the *same* queries for both retrievers, so that shared difficulty cancels and only the per-query difference varies. That difference is consistently positive, so its interval sits well above 0.

</details>
