# Design: Ingress — how knowledge earns its way into the graph

> **Implementation status (2026-08-07):** 🟨 **Core ingress gate built:** WorkItem,
> Decision, Verification, ExecutionPath, and Blocker provenance/validation shapes are
> present. Bootstrap proves both an untagged-write refusal and a falsifier-less
> Verification refusal. Execution-path inventory is now produced by the scheduled,
> ownership-neutral aegis source and the Quipu coverage query reports `Empty`,
> `Partial`, or `Full` rather than a bare count. Hank now emits a falsifier-gated
> `Verification` and a `built` `Blocker` for each signed unsatisfied verdict. Its
> source change is merged, but it is not yet an installed/runtime producer: the
> sanctioned installer consumes release artifacts and no verdict-drain schedule is
> present. Until both are true, the blocker query's zero is an explicit gap, not
> evidence that no blocker exists.

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
6. **Verification names its falsifier.** A `Verification` carries the observable
   result that would have disproved it. The shape refuses a claim without one;
   bootstrap proves that refusal separately from the provenance-tag gate.
7. **Liveness is calculated, never written.** Producers store timestamped
   observations (a stop record, a refresh, an installed-artifact hash). A reader
   combines them with the current process or artifact state. `ExecutionPath`
   deliberately has no `isLive` property: a stored verdict would age into the
   stale fact it claims to detect.
8. **Blockers name their evidence strength.** A `Blocker` is exactly one of
   `stated` (a claim in a ticket/report) or `built` (a demonstrated failing
   case). When a built blocker links `demonstratedBy`, it must link a
   falsifier-gated `Verification`; Hank emits that link for signed unsatisfied
   verdicts. A reader can therefore keep a stated blocker visible without
   presenting it as a measurement. Absence of such a record remains a producer
   coverage question, not a claim that no blocker exists.

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

### 3.2 Tracker and harness record parsers — optional enrichment

A tracker or harness with its own records can be backfilled and corroborated
by a deterministic parser translating records → episodes tagged `observed`:

- **Beads (`bd`)** is the cleanest such source: agent-first, JSON out, and a
  bead *is* a `WorkItem` record — id, status, dependencies, lifecycle — so
  the parse is nearly a projection. Where beads is st's tracker backend, one
  parser covers both.
- **Shantytown's own records** (task/crew, with the `ts`/`item`/`item_status`
  payload its event store already learned an event must carry) parse the
  same way. Shantytown's adapter table reserves a `knowledge` layer for a
  native emit half; that is a welcome *integration* on that repo's schedule
  — camayoc works identically without it, and its none-adapter proves the
  independence in the other direction.

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
