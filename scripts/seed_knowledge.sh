#!/usr/bin/env bash
# camayoc seed — give the graph its anchor entities: the codebase + docs.
#
#   seed_knowledge.sh                # seed from the current project
#   seed_knowledge.sh /path/to/repo  # seed from another local tree
#   seed_knowledge.sh <git-url>      # shallow-clone into .quipu/seed/ and seed
#
# Why: the competency questions hang off entities — "what did we decide about
# X" needs X to exist. Walking the code and docs (deterministic, observed by
# construction) mints modules, symbols, documents and sections for decisions
# to anchor to. The walk is SHACL-validated: code-entities shapes load first,
# so a malformed seed is refused, not absorbed.
set -u

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
SERVER="${QUIPU_SERVER:-http://localhost:3030}"; SERVER=${SERVER%/}
AUTH=()
[ -n "${QUIPU_AUTH_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer $QUIPU_AUTH_TOKEN")
say() { printf '%s\n' "$*"; }

curl -sf -m 3 "$SERVER/health" >/dev/null 2>&1 || {
  say "seed: quipu unreachable at $SERVER — run /camayoc:bootstrap first."
  say "This is 'could not look', not 'nothing exists'."
  exit 1
}

# Resolve the source tree
SRC="${1:-$PROJECT_DIR}"
case "$SRC" in
  http://*|https://*|git@*)
    NAME=$(basename "$SRC" .git)
    DEST="$PROJECT_DIR/.quipu/seed/$NAME"
    if [ -d "$DEST/.git" ]; then
      say "seed: reusing existing clone at $DEST"
    else
      say "seed: shallow-cloning $SRC ..."
      mkdir -p "$PROJECT_DIR/.quipu/seed"
      git clone --depth 1 "$SRC" "$DEST" || { say "seed: clone failed"; exit 1; }
    fi
    SRC="$DEST"
    ;;
esac
[ -d "$SRC" ] || { say "seed: not a directory: $SRC"; exit 1; }
say "seed: source tree $SRC"

# Gate first: load the code-entities shapes so the walk is validated
R=$(python3 -c 'import json,sys; print(json.dumps({"action":"load","name":"code-entities","turtle":open(sys.argv[1]).read()}))' "$PLUGIN_ROOT/shapes/code-entities.ttl" \
    | curl -sf -m 10 -X POST "$SERVER/shapes" -H 'Content-Type: application/json' "${AUTH[@]}" -d @- 2>&1) \
  && say "shapes: code-entities loaded" || { say "shapes load FAILED: $R"; exit 1; }

# Walk → Turtle
TTL=$(mktemp "${TMPDIR:-/tmp}/camayoc-seed-XXXXXX.ttl")
trap 'rm -f "$TTL"' EXIT
python3 "$PLUGIN_ROOT/scripts/ingest_repos.py" "$SRC" -o "$TTL" || { say "seed: walker failed"; exit 1; }
TRIPLE_HINT=$(grep -c ' ;$\| \.$' "$TTL" 2>/dev/null || echo '?')
say "seed: walked $(basename "$SRC") (~$TRIPLE_HINT statement lines)"

# Ingest, SHACL-gated
R=$(python3 -c 'import json,sys; print(json.dumps({"turtle": open(sys.argv[1]).read(), "actor": "camayoc-seed", "source": sys.argv[2]}))' "$TTL" "$SRC" \
    | curl -sf -m 120 -X POST "$SERVER/knot" -H 'Content-Type: application/json' "${AUTH[@]}" -d @- 2>&1) || {
  say "seed: ingest REFUSED or failed:"
  say "  $R"
  say "  A refusal means the gate is working — fix the walker output, don't bypass."
  exit 2
}
COUNT=$(printf '%s' "$R" | sed -n 's/.*"count"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p')
CONFORMS=$(printf '%s' "$R" | sed -n 's/.*"conforms"[[:space:]]*:[[:space:]]*\(true\|false\).*/\1/p')
say "seed: ingested ${COUNT:-?} facts (conforms: ${CONFORMS:-n/a})"
say "seed: done — modules, symbols, documents and sections are now anchors for"
say "seed: decisions ('what did we decide about X' has its X). Re-run after big"
say "seed: refactors; the ingest is idempotent at the fact level."
