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
# The idempotency rule this repo teaches (skills/camayoc/SKILL.md 52-54) is
# "branch on `outcome`, never on `count`; `unchanged` is success". camayoc-16y
# caught the seed path not following it. Two things were wrong:
#
#   * the response was read with sed over the raw body, so a "count" appearing
#     anywhere in it matched — the same read-a-verdict-out-of-text mistake the
#     gate probes had (camayoc-045);
#   * the status line led with the count, so a converged re-run announced
#     "ingested 0 facts". That is the SUCCESS case reading as a failure, which
#     is precisely what the rule exists to prevent.
#
# The rule is written for POST /episode and the seed uses POST /knot. Read
# against quipu: /episode returns `outcome` — one of created|updated|unchanged
# (src/episode/mod.rs:96-102) — and /knot does NOT. Its success body is
# {conforms, tx_id, count, snapshot, replaced} (src/mcp/mod.rs:512-518).
#
# So on today's quipu this always takes the no-outcome branch, and that is the
# honest report rather than a defect: the seed cannot tell convergence from a
# re-add, and says so, instead of reading a count as if it were a verdict.
# Routing the seed through /episode would earn the signal and is camayoc-s0h.
# The branch stays because the rule is the rule, and because a /knot that grows
# `outcome` should be believed the day it does.
python3 -c '
import json, sys

try:
    doc = json.loads(sys.argv[1])
except Exception:
    doc = None

if not isinstance(doc, dict):
    print("seed: the store accepted the write, but its answer was not JSON we could read.")
    print("seed: convergence is unconfirmed — that is \"could not tell\", not \"nothing landed\".")
    raise SystemExit(0)

outcome, count, conforms = doc.get("outcome"), doc.get("count"), doc.get("conforms")

# A refusal that arrives with a 2xx would otherwise slide past: curl -sf caught
# the HTTP-level refusal above, and this catches the one that did not use it.
# quipu returns the SHACL failure body with HTTP 200 (src/mcp/mod.rs:471-477):
#   {"conforms": false, "violations": N, "warnings": N, "issues": [...], "hint": "..."}
# `violations` is a COUNT and `issues` is the list. Slicing the count as a list
# is a TypeError, which would replace the violation messages with a traceback
# at the exact moment the operator needs them.
counted = doc.get("violations")
counted = counted if isinstance(counted, int) and not isinstance(counted, bool) else 0
issues = [i for i in (doc.get("issues") or doc.get("results") or []) if i]

if conforms is False or counted or issues:
    print("seed: ingest REFUSED — the store did not accept the walk.")
    for issue in issues[:5]:
        if isinstance(issue, dict):
            issue = issue.get("message") or issue.get("resultMessage") or json.dumps(issue)
        print(f"seed:   {issue}")
    if not issues:
        hint = doc.get("hint")
        print(f"seed:   {hint}" if isinstance(hint, str) and hint else f"seed:   {counted} violation(s)")
    print("seed: A refusal means the gate is working — fix the walker output, do not bypass.")
    raise SystemExit(2)

if isinstance(outcome, str):
    if outcome == "unchanged":
        print("seed: unchanged — the graph already holds this walk, which is SUCCESS.")
        print("seed: the seed is meant to converge on a re-run, not to accumulate.")
    else:
        print(f"seed: outcome {outcome}")
else:
    print("seed: the store sent no `outcome`, so convergence cannot be confirmed from")
    print("seed: this response. Below is what it did send.")

detail = []
if isinstance(count, int):
    detail.append(f"count {count}")
if conforms is True:
    detail.append("conforms true")
if detail:
    print("seed: " + ", ".join(detail) + " — detail, not the verdict. A count of 0 on a")
    print("seed: re-run is convergence, not a failed ingest.")
' "$R" || exit 2

say "seed: done — modules, symbols, documents and sections are now anchors for"
say "seed: decisions ('what did we decide about X' has its X). Re-run after big"
say "seed: refactors; the ingest is idempotent at the fact level."
