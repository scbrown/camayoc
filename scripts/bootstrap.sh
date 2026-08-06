#!/usr/bin/env bash
# camayoc bootstrap — stand up governed memory and PROVE the gate.
# Idempotent. Exits non-zero only when the store accepted what it must
# refuse (a gate that is off is a report, not something to route around).
set -u

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
SERVER="${QUIPU_SERVER:-http://localhost:3030}"; SERVER=${SERVER%/}
AUTH=()
[ -n "${QUIPU_AUTH_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer $QUIPU_AUTH_TOKEN")

say() { printf '%s\n' "$*"; }

# 1. Probe
say "camayoc bootstrap → $SERVER"
HEALTH=$(curl -sf -m 3 "$SERVER/health" 2>/dev/null) || {
  say "REFUSING TO PROCEED: quipu unreachable at $SERVER."
  say "This is 'could not look', not 'nothing exists'. Start one:"
  say "  cargo install quipu --features full"
  say "  quipu-server --db .quipu/store.db"
  exit 1
}
say "health: ok"

# 2. Load ontology (facts) + shapes (the gate), idempotently
ONTO="$PLUGIN_ROOT/ontology/core.ttl"
SHAPES="$PLUGIN_ROOT/shapes/core.shapes.ttl"
[ -f "$ONTO" ] && [ -f "$SHAPES" ] || { say "missing $ONTO / $SHAPES"; exit 1; }

py_json_turtle() { python3 -c 'import json,sys; print(json.dumps({sys.argv[1]: open(sys.argv[2]).read(), **dict(a.split("=",1) for a in sys.argv[3:])}))' "$@"; }

R=$(py_json_turtle turtle "$ONTO" "actor=camayoc-bootstrap" | curl -sf -m 10 -X POST "$SERVER/knot" -H 'Content-Type: application/json' "${AUTH[@]}" -d @- 2>&1) \
  && say "ontology: loaded (core.ttl)" || { say "ontology load FAILED: $R"; exit 1; }

R=$(python3 -c 'import json,sys; print(json.dumps({"action":"load","name":"camayoc-core","turtle":open(sys.argv[1]).read()}))' "$SHAPES" \
    | curl -sf -m 10 -X POST "$SERVER/shapes" -H 'Content-Type: application/json' "${AUTH[@]}" -d @- 2>&1) \
  && say "shapes: loaded (camayoc-core)" || { say "shapes load FAILED: $R"; exit 1; }

# 3. PROVE the gate: an untagged Decision must be REFUSED.
#    (validate_on_write must be enabled in the store's [quipu.shacl] config —
#    a store that accepts this probe has no gate, and we say so.)
PROBE=$(curl -s -m 10 -X POST "$SERVER/episode" -H 'Content-Type: application/json' "${AUTH[@]}" -d '{
  "name": "camayoc-gate-probe-untagged",
  "nodes": [{"name": "camayoc-gate-probe", "type": "Decision",
             "properties": {"chose": "nothing — this is a gate probe"}}]
}' 2>&1)
if printf '%s' "$PROBE" | grep -qi 'conforms.*false\|violation\|refus\|sourceKind'; then
  say "gate: PROVEN — untagged probe refused, as it must be."
else
  say "gate: NOT PROVEN — the store ACCEPTED an untagged Decision."
  say "  response: $PROBE"
  say "  Enable [quipu.shacl] validate_on_write, or every trust tag is advisory."
  say "  Not retrying, not routing around. Fix the gate first."
  exit 2
fi

say "camayoc: governed memory ready. Query first; record at the moment; tag honestly."
