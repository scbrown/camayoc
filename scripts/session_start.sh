#!/usr/bin/env bash
# camayoc SessionStart hook — probe governed memory, report honestly.
# Emits hookSpecificOutput.additionalContext. Never blocks a session:
# every path exits 0 with a one-line truthful status. "Could not reach
# quipu" is NOT "no knowledge" — the two answers are kept distinct.
set -u

resolve_server() {
  if [ -n "${QUIPU_SERVER:-}" ]; then echo "$QUIPU_SERVER"; return; fi
  for f in "${CLAUDE_PROJECT_DIR:-.}/env.json" "./env.json"; do
    if [ -f "$f" ]; then
      s=$(sed -n 's/.*"quipu_server"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$f" | head -1)
      if [ -n "$s" ]; then echo "$s"; return; fi
    fi
  done
  echo "http://localhost:3030"
}

emit() {
  # $1 = context string (single line). JSON-escape the minimum.
  esc=$(printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g')
  printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$esc"
}

SERVER=$(resolve_server); SERVER=${SERVER%/}

STATS=$(curl -sf -m 2 "$SERVER/stats" 2>/dev/null) || {
  emit "camayoc: could not reach quipu at $SERVER — governed memory UNAVAILABLE this session (this is 'could not look', not 'nothing exists'). To enable: start quipu-server (cargo install quipu --features full; quipu-server --db .quipu/store.db) then run /camayoc:bootstrap."
  exit 0
}

FACTS=$(printf '%s' "$STATS" | sed -n 's/.*"facts"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p')
SHAPES=$(curl -sf -m 2 -X POST "$SERVER/shapes" -H 'Content-Type: application/json' \
  ${QUIPU_AUTH_TOKEN:+-H "Authorization: Bearer $QUIPU_AUTH_TOKEN"} \
  -d '{"action":"list"}' 2>/dev/null)

if printf '%s' "${SHAPES:-}" | grep -q 'camayoc-core'; then
  emit "camayoc: governed memory ACTIVE at $SERVER (${FACTS:-?} facts, camayoc shapes loaded). Query before re-deciding (competency questions in the camayoc skill); record decisions as tagged episodes AT THE MOMENT they happen; sourceKind observed|declared|inferred, tagged honestly."
else
  emit "camayoc: quipu reachable at $SERVER (${FACTS:-?} facts) but camayoc shapes are NOT loaded — the gate is not proven. Run /camayoc:bootstrap before ingesting; reads are fine."
fi
exit 0
