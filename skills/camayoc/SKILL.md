---
name: camayoc
description: Use governed memory backed by a quipu knowledge store. Load this when working in a project that has (or should have) a quipu — to query prior decisions and conventions before re-deciding them, to record decisions/work/outcomes at the moment they happen, to bootstrap a new store with the camayoc ontology and shapes, or when the user mentions quipu, camayoc, knowledge graph memory, "what did we decide", or recording a decision.
---

# camayoc — the knot-keeper's skill

You are working with governed memory: a quipu store where facts carry
provenance tags and SHACL refuses writes that lack them. This skill teaches
the four moves. The shapes enforce the rules whether or not you follow the
guidance — a refused write means the gate is working, not that you should
route around it.

**Server:** resolve in this order: `$QUIPU_SERVER` → project config
(`.bobbin/config.toml` or `env.json`) → `http://localhost:3030`. Reads are
open; writes need `Authorization: Bearer $QUIPU_AUTH_TOKEN` when the server
is gated. Never hardcode a server or namespace — they are deployment
parameters.

## Move 0 — Bootstrap (only when the store is bare)

1. Probe: `GET /health`, then `GET /stats`. Unreachable is NOT "no
   knowledge" — say you could not look; do not proceed as if empty.
2. Check shapes: `POST /shapes {"action":"list"}`. If camayoc shapes are
   missing, load `ontology/*.ttl` then `shapes/*.shapes.ttl` from this repo
   via `POST /shapes {"action":"load","name":...,"turtle":...}` (idempotent).
3. **Prove the gate**: attempt one deliberately untagged probe write and
   confirm it is REFUSED; then write and retract a correctly tagged probe.
   A store that accepts the untagged probe has no gate — report that, do
   not ingest into it.

## Move 1 — Query first

Before deciding anything a past session may have decided, ask. The
competency questions in `competency/` are the canonical set. Until stored
queries land in quipu, use `POST /query` with SPARQL; the patterns:

- *What did we decide about X, and why?* — find `camayoc:Decision` nodes
  whose `about`/`decidedIn` reaches X; read `chose`, `over`, `rationale`.
- *What conventions apply here?* — `sourceKind "declared"` facts in scope.
- *Prior work on this area?* — work items linked to the entity, with
  outcomes.

Respect the tags in what comes back: a fact tagged `inferred` is a lead,
not a law. If two sources conflict, the conflict is the answer — report it
as contested; do not silently pick.

## Move 2 — Record at the moment

When a decision is made **in this session**, record it now — not in a
wrap-up summary. One episode per decision or small batch, via
`POST /episode` (idempotent — branch on `outcome`, never on `count`;
`unchanged` is success):

```json
{
  "name": "decision-<short-slug>",
  "source": "<work-item or session ref>",
  "nodes": [
    {"name": "<decision-slug>", "type": "Decision",
     "properties": {"chose": "...", "over": "...", "rationale": "...",
                     "sourceKind": "declared|inferred", "ts": "<iso8601>"}}
  ],
  "edges": [
    {"source": "<decision-slug>", "target": "<work-item>", "relation": "decidedIn"}
  ]
}
```

Likewise work items (created/closed, with `ts`) and outcomes
(`done|abandoned|superseded|failed`) at session end. Reuse existing node
names **byte-for-byte** — a re-worded name mints a duplicate entity.

## Move 3 — Tag honestly

`sourceKind` is mandatory and means exactly:

- **`observed`** — a record exists and you (or a parser) read it. Cite it.
- **`declared`** — a human said it, in this session or a document. Quote or
  reference them.
- **`inferred`** — you concluded it. It goes to the inferred plane, low
  trust, promotable later by someone with authority — never by you
  up-tagging it.

Never claim `observed` or `declared` for your own conclusion. The gate will
not catch a plausible lie about source — only you can. That honesty is the
entire value of the record to the next reader.

## Never

- Write to a governed plane without the tags (the store refuses; do not
  work around a refusal — report it).
- Store a judgment that decays (liveness, "currently in progress",
  "latest"). Store facts true at write time; derive status by query.
- Treat "could not reach quipu" as "no knowledge exists". Different answers.
- Summarize a session's decisions from memory at the end instead of
  recording them when they happened. Late recall is `inferred`; in-the-moment
  recording is `declared`.
