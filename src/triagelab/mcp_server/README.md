# repo-intel: an MCP server for a repository's past

`repo-intel` gives an agent read-only access to a GitHub repository's issue history and source code **as they were at a chosen moment**. It was built for evaluating issue triage, where the hard requirement is that nothing from after an issue was opened can reach the model. It is useful wherever an agent must not see the future: backtests, replays, evaluations.

It is a standard [Model Context Protocol](https://modelcontextprotocol.io) server over stdio, built with the official Python SDK.

## Tools

| Tool | What it returns |
|---|---|
| `search_similar_issues(query, as_of, k)` | Earlier issues by hybrid search (BM25 + dense, fused by reciprocal rank): number, title, snippet, and the labels and state they had at `as_of`. |
| `get_issue(number, as_of)` | One earlier issue as it looked at `as_of`. Issues created at or after `as_of` do not exist. |
| `search_code(query, path_glob?, max_results)` | Matches in a frozen source checkout: path, line, snippet, component. |
| `get_codeowners(path)` | The owners and the component of a path. |
| `list_components()` | The repository's component map. |

Every tool is annotated read-only and returns bounded, structured output with truncation markers.

## The guarantee

`as_of` is enforced by the server, not by the prompt:

- only issues created strictly before `as_of` exist for a query;
- an issue shows its creation-time text, with labels and state replayed up to `as_of`;
- `--as-of-ceiling` rejects any `as_of` later than a fixed time, so a model cannot ask for a later view.

It is tested at three levels (unit tests, a real MCP client in-process, the MCP Inspector), and `triagelab runs audit` re-checks finished runs from their traces.

## Run it

The server reads a repository profile and a data folder with a retrieval index. The quickest way to get both is this project's public dataset pack for `python/cpython`:

```bash
git clone https://github.com/ish-codes-magic/triage-bench && cd triage-bench
uv sync
uv run triagelab reproduce            # downloads and verifies the dataset packs into data/
uv run triagelab data checkout -p configs/repos/python__cpython.yaml   # optional: code search
uv run repo-intel --profile configs/repos/python__cpython.yaml
```

Options (each also has an environment variable, for launchers that pass no arguments):

| Option | Environment | Meaning |
|---|---|---|
| `--profile PATH` | `REPO_INTEL_PROFILE` | The repository profile (taxonomy, components, time windows). Required. |
| `--data-dir PATH` | `REPO_INTEL_DATA_DIR` | Where the index lives. Default `data`. |
| `--no-dense` | `REPO_INTEL_DENSE=0` | BM25 only: no embedding model is loaded. |
| `--as-of-ceiling ISO8601` | | Reject any later `as_of`. |

### From an MCP client

```json
{
  "mcpServers": {
    "repo-intel": {
      "command": "uv",
      "args": ["run", "repo-intel", "--profile", "configs/repos/python__cpython.yaml"],
      "cwd": "/path/to/triage-bench"
    }
  }
}
```

### With the MCP Inspector

```bash
npx @modelcontextprotocol/inspector uv run repo-intel -p configs/repos/python__cpython.yaml
```

### As a container

The image contains the server and the repository profiles; the data folder is mounted.

```bash
docker build -t repo-intel .
docker run -i --rm -v "$PWD/data:/data" repo-intel \
    --profile /app/configs/repos/python__cpython.yaml
```

Run it with `-i` and without `-t`: the protocol runs over stdin and stdout.

## Your own repository

1. Write a profile like `configs/repos/python__cpython.yaml` (labels, components, time windows).
2. `triagelab data collect -p <profile>` and `triagelab data build -p <profile>` (needs a GitHub token).
3. `triagelab retrieval build -p <profile>` for the index, and `triagelab data checkout -p <profile>` for code search.

## Limits

- It ships inside the `triagelab` distribution, so installing it also installs the evaluation code's dependencies (ADR-0050).
- Issue bodies are creation-time text; later edits are never shown, even where they would be visible at `as_of`.
- Code search runs on one frozen checkout, taken shortly before the evaluation window. It does not move with `as_of`.
- `search_code` uses a pure-Python search unless ripgrep is switched on (ADR-0044), so results are identical everywhere but large repositories are slower.
