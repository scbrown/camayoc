# Design: Ingress — how knowledge earns its way into the graph

> **Implementation status (2026-08-06):** ⬜ **Founding design — nothing built.**

## 1. The discipline, in five rules

1. **Episode-shaped writes only.** Every camayoc ingress goes through quipu's
   `/episode` path, which supplies `prov:wasGeneratedBy` automatically and is
   idempotent (branch on `outcome`, never on `count`). No free-Turtle writes
   to governed planes — the provenance chain must be unskippable.
2. **SHACL refuses the untagged.** Every fact carries `camayoc:sourceKind`
   (`observed` | `declared` | `inferred`) and a source reference. Closed
   vocabulary, `minCount 1`, from the first load. This is NeuralAmplifier's
   proven posture (its ingest literally refuses a mod file claiming to be
   canonical), generalized.
3. **Deterministic-first.** If a parser can produce the fact from a record,
   the parser does — no model in the loop on `observed` facts, because a
   hallucinated fact is indistinguishable downstream from a real one on
   exactly the facts tagged trustworthy.
4. **Inference is quarantined, not banned.** LLM-derived knowledge (session
   summaries, "lessons learned," failure diagnoses) is valuable — it lands in
   its own plane (named graph) labelled low-trust in the lattice, so the
   label meets through every query that touches it. It can *earn* promotion
   (a graph move, bitemporal and auditable) — it can never masquerade.
5. **Facts true at write time.** No stored judgment that decays (liveness,
   currency, "still in progress"). Judgments are queries at read time.

## 2. Planes by velocity

Mirroring the pattern NeuralAmplifier proved (datalinks / doctrine / memory),
mapped onto quipu named graphs with lattice labels:

| Plane (named graph) | Contents | Velocity | `sourceKind` | Trust label |
|---|---|---|---|---|
| `crew:records` | task lifecycle, decisions, outcomes (skill-recorded or parser-backfilled) | per-event | `observed` / `declared` | high |
| `crew:declared` | conventions, directives, standing decisions a human stated | occasional | `declared` | high (human root) |
| `crew:inferred` | model-written summaries, diagnoses, lessons | per-session | `inferred` | low, promotable |
| `code:*` | hank-promoted structure (already governed upstream) | per-commit | `observed` | per hank tier |

## 3. Sources

### 3.1 The skill-guided agent — the first-class source

The primary ingress surface is **the agent itself**, guided by the shipped
skill ([skill.md](skill.md), `skills/camayoc/SKILL.md`): it records
decisions, work items and outcomes as tagged episodes at the moment they
happen. Guidance and enforcement are deliberately separate — the skill makes
the honest tag the path of least resistance; the shapes refuse what the
skill failed to prevent. **No harness is a dependency**: any agent with HTTP
reaches the whole surface.

### 3.2 Harness record parsers — optional enrichment

A harness with its own records (shantytown's task/crew records, with the
`ts`/`item`/`item_status` payload its event store already learned an event
must carry) can be backfilled and corroborated by a deterministic parser
translating records → episodes tagged `observed`. Shantytown's adapter table
reserves a `knowledge` layer for the emit half; that is a welcome
*integration* on that repo's schedule — camayoc works identically without
it, and its none-adapter proves the independence in the other direction.

### 3.3 Git

Commit history → work-item linkage (`aegis:implements`, `aegis:modifies` —
the provenance chain quipu's co-occurrence shapes already define). Pure
`observed`; hank already promotes the structural half.

### 3.4 Sessions (the inferred plane)

Transcript-derived summaries and diagnoses, written by a model, landing in
`crew:inferred` only. The interesting future here is the SARC trust-predicate
gap: a producer that records sub-agent responses is exactly what a session
adapter is — but v1 claims only quarantine, not evaluation.

## 4. What ingress never does

- Never writes to a governed plane without the tags (SHACL enforces).
- Never upgrades its own output: promotion out of `crew:inferred` is a
  governed graph move requiring authority over the target plane, not an
  ingress feature.
- Never stores a judgment that decays (§1.5).
- Never models the tracker's message format — the record is evidence about
  the work, not the shape of the work.

## 5. Related

- [bootstrap-ontology.md](bootstrap-ontology.md) — the vocabulary these
  writes carry.
- [skill.md](skill.md) — the skill-as-interface usage model this section
  implements.
- [task-lifecycle-slice.md](task-lifecycle-slice.md) — the first slice; its
  record mapping is the enrichment parser's translation table.
- shantytown `docs/adapters.md` — the reserved knowledge seam and the
  two-implementations rule; `shantytown/events.py` — the event-payload
  lessons §1.5 inherits.
- quipu `docs/design/graph-labels.md` — the lattice that makes quarantine
  enforceable rather than aspirational.
