# Design: First Slice — task lifecycle + decisions

> **Implementation status (2026-08-06):** ⬜ **Founding design — nothing built.**
> This slice is the forcing function for the bootstrap ontology: no term is
> minted until a row in the mapping below or a question in the competency
> suite needs it.

## 1. Why this slice

"What did we decide about X, and why" is the highest-value question a crew's
memory can answer, and the task lifecycle is the provenance spine every
decision hangs from. It is also the slice with the most honest data source:
shantytown's task/crew records exist today, are deterministic to parse, and
their event architecture has already learned exactly which facts an event can
carry truthfully.

## 2. The mapping: st records → episodes

One episode per record batch, all facts tagged `sourceKind: observed`, into
the `crew:records` plane. Candidate mapping (the implementation refines
against real records; the *shape* is the commitment):

| St record | Episode facts |
|---|---|
| task created (`st task "…"` → `st-1`) | `crew:st-1 a camayoc:WorkItem ; rdfs:label "…" ; camayoc:createdAt <ts>` |
| task assigned / inboxed to agent | `crew:st-1 camayoc:assignedTo <agent-iri>` (the agent is the existing `aegis:Principal`) |
| agent stop with item held | `camayoc:workedOn` occurrence with `ts`, `item_status` — exactly the payload st's event store records, no more (no liveness verdicts: facts true at write time) |
| task done / closed | `crew:st-1 camayoc:outcome camayoc:done ; camayoc:closedAt <ts>` |
| decision recorded | `camayoc:Decision` node: `decidedIn crew:st-1 ; decidedBy <principal> ; chose "…" ; over "…" ; rationale "…"` |

Decisions are the one place the slice needs a record st does not currently
write: a **decision record**. Two paths, both kept open: (a) a lightweight st
convention (a `decision:` line in task notes the parser lifts), and (b) the
session adapter writing decisions into `crew:inferred` until a human or
convention promotes them. Start with (a) — declared/observed beats inferred.

## 3. Competency questions = acceptance tests

The slice's question set lives in
[competency/crew-task-lifecycle.md](../../competency/crew-task-lifecycle.md)
and doubles as the test suite: the slice is **done** when each question runs
as a named stored query (quipu #79) against a graph built from *real*
shantytown records, and an agent (or Stiwi) accepts the answers as faithful.
That definition-of-done is stolen deliberately from the claims planning doc:
model with sign-off, real historical data validated, questions running as
named queries, and a trace a reviewer accepts.

## 4. Deliverables

1. `ontology/core.ttl` + `shapes/core.shapes.ttl` — the bootstrap terms the
   mapping actually needs (and no more).
2. `ontology/crew.ttl` + `shapes/crew.shapes.ttl` — the crew domain.
3. `camayoc crew ingest <st-root>` — the deterministic record→episode
   adapter (tail mode; the st-native emitter seam comes later and does not
   block).
4. The competency queries as stored queries, shipped for `crew.qpack` when
   quipu #79/#81 land; runnable as raw SPARQL until then.
5. An eval gate: `just check` runs the questions against a fixture graph
   built from recorded st activity.

## 5. Scope boundaries (honest)

- **No task↔code linkage in this slice** (`aegis:modifies` joins come with
  the git adapter, next slice) — the decision spine must stand alone first.
- **No failure-memory** ("has this been seen before") — needs the inferred
  plane and its promotion story; deliberately after the observed spine.
- **No st code changes required.** Tail mode reads records; the native
  emitter is st's reserved seam, on st's schedule.
- **Nothing here claims real-time.** Ingest is batch/poll; the crew's live
  coordination stays in st where it belongs.
