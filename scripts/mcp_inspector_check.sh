#!/usr/bin/env bash
# Layer-3 check of the repo-intel MCP server with the official MCP Inspector (CLI mode).
# Needs Node >= 22.19 and a built index (`triagelab retrieval build`). Usage:
#   scripts/mcp_inspector_check.sh [profile]
# Argument order matters: the Inspector parses flags after the server command, and a
# server command with its own flags gets them swallowed, so the server is configured via
# -e environment variables instead.
set -euo pipefail
PROFILE="${1:-configs/repos/python__cpython.yaml}"
PY="${PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY=".venv/bin/python"
SERVER=("$PY" src/triagelab/mcp_server/__main__.py)
ENV=(-e "REPO_INTEL_PROFILE=$PROFILE" -e "REPO_INTEL_DENSE=${REPO_INTEL_DENSE:-0}")
INSPECT=(npx -y @modelcontextprotocol/inspector@latest --cli)

echo "== tools/list"
"${INSPECT[@]}" "${SERVER[@]}" "${ENV[@]}" --method tools/list
echo "== search_similar_issues (as of 2026-06-01)"
"${INSPECT[@]}" "${SERVER[@]}" "${ENV[@]}" --method tools/call \
  --tool-name search_similar_issues --tool-arg "query=zipfile crashes on empty archive" \
  as_of=2026-06-01T00:00:00Z k=3
echo "== get_issue for an issue filed after as_of (must be refused)"
if "${INSPECT[@]}" "${SERVER[@]}" "${ENV[@]}" --method tools/call \
  --tool-name get_issue --tool-arg number=154672 as_of=2026-06-01T00:00:00Z; then
  echo "FAIL: a future issue was returned" >&2
  exit 1
fi
echo "OK: future issue refused"
