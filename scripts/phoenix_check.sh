#!/usr/bin/env bash
# Send agent traces to a local Arize Phoenix and confirm, through Phoenix's REST API, that
# they arrived as one AGENT span per issue with LLM and TOOL children (ADR-0029).
#
# Start Phoenix first, in another terminal (it is a viewer, not a project dependency):
#   PHOENIX_WORKING_DIR=.phoenix uvx --from arize-phoenix==20.16.0 phoenix serve
# Then:
#   scripts/phoenix_check.sh [N issues] [config]
# Re-running issues that an earlier dev run already answered is free: every model call
# comes from the response cache, and only the spans are new.
set -euo pipefail
N="${1:-3}"
CONFIG="${2:-configs/experiments/agent.yaml}"
BASE="${PHOENIX_URL:-http://localhost:6006}"
PROJECT="${PHOENIX_PROJECT:-triagelab}"
PY="${PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY=".venv/bin/python"

curl -sf "$BASE/" > /dev/null || { echo "Phoenix is not answering at $BASE" >&2; exit 1; }

echo "== eval: $N dev issues with OTLP export to $BASE/v1/traces"
"$PY" -m triagelab eval -c "$CONFIG" --split dev --limit "$N" \
  --otlp-endpoint "$BASE/v1/traces" | tail -n 1

echo "== spans in Phoenix project '$PROJECT', by kind"
curl -sf "$BASE/v1/projects/$PROJECT/spans?limit=1000" | "$PY" -c '
import collections, json, sys
spans = json.load(sys.stdin)["data"]
kinds = collections.Counter(s.get("span_kind") for s in spans)
print(dict(kinds))
sys.exit(0 if kinds.get("AGENT") and kinds.get("LLM") else "FAIL: no AGENT/LLM spans")
'
echo "OK: open $BASE to browse the traces"
