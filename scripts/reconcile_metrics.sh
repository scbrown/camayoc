#!/usr/bin/env bash
# Reconcile Prometheus rule definitions into one producer-owned graph snapshot.
set -euo pipefail

ROOT=${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
SERVER=${QUIPU_SERVER:-http://localhost:3030}; SERVER=${SERVER%/}
SOURCE=${1:?usage: reconcile_metrics.sh RULE_FILE_OR_DIRECTORY [PROMETHEUS_ENDPOINT]}
ENDPOINT=${2:-}
AUTH=()
[ -n "${QUIPU_AUTH_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer $QUIPU_AUTH_TOKEN")

TTL=$(mktemp "${TMPDIR:-/tmp}/camayoc-metrics-XXXXXX.ttl")
PAYLOAD=$(mktemp "${TMPDIR:-/tmp}/camayoc-metrics-XXXXXX.json")
trap 'rm -f "$TTL" "$PAYLOAD"' EXIT

ARGS=("$SOURCE" -o "$TTL")
[ -n "$ENDPOINT" ] && ARGS+=(--prometheus-endpoint "$ENDPOINT")
python3 "$ROOT/scripts/ingest_metrics.py" "${ARGS[@]}"

python3 - "$TTL" > "$PAYLOAD" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    turtle = handle.read()
print(json.dumps({
    "turtle": turtle,
    "actor": "camayoc-metric-reconciler",
    "source": "prometheus-rule-catalogue",
    "replace_snapshot": True,
    "snapshot": "camayoc-prometheus-metrics",
}))
PY

curl -fsS "$SERVER/knot" -X POST -H 'Content-Type: application/json' \
  "${AUTH[@]}" --data-binary @"$PAYLOAD"
