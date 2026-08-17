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
> evidence that no blocker exists. **Rule 1 corrected (2026-08-16):** it claimed
> episode-shaped ingress; every real ingest is and always was a `/knot` write, so
> the rule now states the boundary it actually governs and `tests/test_knot_provenance.py`
> enforces the `actor` + `source` floor it narrowed to (camayoc-99t).

## 1. The discipline, in five rules

1. **Episode-shaped writes for agent-recorded facts.** Everything the skill
   records in the moment — decisions, work items, outcomes — goes through
   quipu's `/episode` path, which supplies `prov:wasGeneratedBy` automatically
   and is idempotent (branch on `outcome`, never on `count`). That is where the
   provenance chain must be unskippable: those facts have an author, a moment
   and a motive, and a later reader has to be able to weigh them.

   **Bulk deterministic loads go through `POST /knot`, and this rule does not
   pretend otherwise.** The ontology and shapes (`scripts/bootstrap.sh`), the
   repository walk (`scripts/seed_knowledge.sh`) and the metric catalogue
   (`scripts/reconcile_metrics.sh`) are free-Turtle knot writes. They carry
   `actor` and `source` in the payload instead of a PROV activity;
   `prov:wasGeneratedBy` appears nowhere in the codebase outside these design
   docs.

   This rule previously read "every camayoc ingress goes through `/episode` …
   no free-Turtle writes to governed planes", which was false in every
   particular: the *only* `/episode` calls in the repository are the four
   deliberately-invalid gate probes in `scripts/gate_probe.sh`, and every
   successful ingest has always been a knot write (camayoc-99t).

   **What the narrowing costs.** `actor` + `source` is a weaker record than a
   PROV activity: it names who wrote and what they read, but not the run, and
   it is not chained, so a knot-written fact cannot be traced to the invocation
   that produced it. That is an acceptable trade for the ontology and shapes —
   schema, not claims — and a real gap for the seed walk and the metric
   catalogue, which *are* claims about a codebase. `tests/test_knot_provenance.py`
   holds the narrowed rule to its own terms: a knot write that names neither
   its actor nor its source fails the suite, so the weaker record cannot
   quietly become no record.
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

### 2.1 Implementation status: the table above is a design, not a deployment

**Nothing routes yet.** No script names a graph, no shape targets one, no query
carries a `GRAPH` clause. An `inferred`-tagged node lands in exactly the same
place an `observed` one does, so quarantine is skill discipline and a `sourceKind`
string — not an enforced boundary (camayoc-s0h).

Read against quipu's source rather than assumed, because the shape of the gap
decides who fixes it:

| Capability | State in quipu | Citation |
|---|---|---|
| Quad store, `GRAPH` / `FROM NAMED` in SPARQL | **exists** | `src/store/migrate.rs:33`, `src/sparql/pattern.rs:352-372` |
| Write into a named graph via `/episode` | **exists** (`graph` field) | `src/episode/mod.rs:177-181`, test at `src/episode/tests.rs:912` |
| Write into a named graph via `/knot` | **does not exist** | hardcoded to ROOT, `src/rdf.rs:180-182` |
| Trust lattice, labels, query-time floors | **exists** | `src/lattice.rs`, `src/store/labels.rs:730` |
| HTTP or CLI route to *set* a graph label | **does not exist** | only caller of `set_graph_label` is `src/pack.rs:450` |
| Labelling a graph `/episode` created | **refused** — the write interns the IRI without registering it | `src/store/labels.rs:344-350` vs `src/episode/mod.rs:371` |
| Store-level primitive that *registers* a graph | **exists, with no caller** | `Store::graph_create`, `src/store/overlays.rs:42` |

So routing is blocked in a specific and fixable way rather than generally:

1. **Every real camayoc ingest is a `/knot` write** (rule 1), and `/knot` cannot
   target a graph. Worse, it takes a free-form JSON body with no unknown-field
   rejection, so a `"graph"` key added to a knot payload is **silently dropped** —
   routing would appear to be implemented and do nothing. `tests/test_knot_provenance.py`
   pins that no knot payload carries one.
2. **Labels have no write route at all.** The whole lattice — composition,
   per-row annotation, query-time floors — is built and reachable only from
   Rust. A plane camayoc created could not be labelled `low-trust` even by hand.

**What unblocks this, in order.** Re-verified 2026-08-17, and the estimate is
smaller than it looks, because the missing pieces are *exposure* rather than
mechanism:

- `Store::graph_create` (`src/store/overlays.rs:42`) is **exactly** the
  registration `set_graph_label` presumes — written, tested, idempotent, and
  refusing a class change. It has **no caller outside its own tests**.
- `Store::set_graph_label` (`src/store/labels.rs:208`) is likewise built and
  reachable only from Rust, its single production caller being `src/pack.rs:450`.

So quipu does not need two mechanisms built; it needs `graph_create` invoked
when `/episode` is handed a `graph` it has not seen (or a route that does it),
and an HTTP route over `set_graph_label`. Camayoc then moves agent-recorded
facts to `/episode` with `graph` derived from `sourceKind` — and note that
`/episode`'s `graph` field **already works**, so camayoc's half is not blocked
on routing at all, only on the labels.

Until the label route exists, routing alone would produce separate graphs that
every query still reads at equal trust — the appearance of quarantine without
the substance, and worse than none. **That ordering, not the missing routing,
is why this is not partially shipped**, and it is worth being precise about:
camayoc could route today and must not.

This is a `built` blocker in the sense of §1.8, not a `stated` one: the
citations above are the demonstration.

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
