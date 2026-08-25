# Competency questions — workflow runs and the archive

The questions that earn the workflow vocabulary (shuttle's export target)
and the graph-kind / deep-freeze surface (quipu
`docs/design/graph-kinds-and-deep-freeze.md`). Per the house rule, every
term minted for workflows is owed to a question here.

Conventions: workflow facts live in time-windowed operational graphs
(`{WINDOW_NS}shuttle/runs/{YYYY-MM}`, `quipu:dataKind "operational"` —
`scripts/windows.py`); frozen windows compose back in explicitly via
`FROM <window-iri>`, `FROM <urn:quipu:dataset:frozen>`, or the `/query`
`include_kinds` param. State transitions are append-only
`aegis:TransitionEvent`s — the measured rule that triple-level retract
deletes nothing, applied at the producer; `aegis:currentState` is
re-asserted per transition, never mutated.

## Runs and their lifecycle

1. Which runs of workflow `<definition>` exist in window `<month>`, and what
   is each run's current state?
2. What state was run `<run>` in at time `<instant>`? (bitemporal — extends
   crew-task-lifecycle 15 to workflow state, answered from the valid-time
   windows on the re-asserted `aegis:currentState` facts)
3. What is the full transition history of run `<run>` — which steps, in what
   order, each from-state to to-state, at what time?
4. Which runs completed in window `<month>`, and with what `aegis:outcome`?
   Which are still open (current state non-terminal)?
5. Which steps does workflow definition `<definition>` declare, and which of
   them did run `<run>` actually pass through?

## Agents and signatures

6. Which agent performed transition `<event>`, and does its
   `aegis:signature` verify against a registered key — an
   `aegis:VerifierRegistration` whose `aegis:verifier` matches the agent and
   whose `aegis:publicKey` verifies the canonical `shuttle-transition-v1`
   message?
7. Which transitions in window `<month>` carry no signature, or a signature
   with no matching registration in the identity graph? (the
   `shuttle-unverified-transitions` stored query — unverifiable transitions
   are detectable from day one even though write-gate enforcement is a
   follow-on, quipu-8cc)
8. What did agent `<principal>` do across all runs in `<time-window>` —
   including runs whose window is now frozen? (crosses hot and archive:
   `include_kinds` or `FROM` both windows)

## Graph kinds and the archive

9. Which graphs hold `<kind>` data, which are frozen, and what does each
   declare on the other label axes? (`GET /graphs` — also the consumer
   capability probe: a 404 means the store predates graph kinds, to be read
   as "cannot tell", never as "no graphs")
10. Can question `<query>` be answered without composing archive graphs —
    i.e. does its dataset's composed kind label include `archive`?
11. Where did window `<month>`'s facts go when it froze, and who authorized
    it? (`quipu:lifecycleState`, `quipu:frozenInto` — the pack's content
    hash — and `quipu:frozenAt` in the meta-graph)
12. Which windows are freezable now — `operational` kind, not yet frozen,
    and every run in them terminal?

## The move rule (resolves camayoc-913)

13. When fact `<fact>` was promoted out of `crew:inferred`, was its
    source-plane interval closed — and is the original still visible as-of
    its write time? (the decided rule, shared by plane promotion and deep
    freeze: assert in the target, close in the source — a bitemporal
    retraction, never a deletion — and record the move; see
    `scripts/promote_plane.py`)
14. For a thawed window `<month>`, is the freeze still on the record? (the
    `frozen_packs` row keeps `thawed_at` rather than disappearing, and the
    closed `quipu:lifecycleState` fact remains bitemporal history)

## Acceptance

The slice is done when 1–12 run as named queries against a fixture graph
holding at least one exported shuttle run in a hot window and one in a
frozen window, and 13–14 replay correctly across a promotion and a
freeze/thaw cycle.

**Measured against that acceptance, 2026-08-25 (camayoc-rkb).** The fixture
exists — `tests/fixtures/workflow-archive.trig`, a TriG dataset with a hot
window, a frozen window, the definitions plane and the identity graph — and
1–5, 7, 8 and 13 run as named queries against it
(`queries/camayoc_wf_*.json`, 36 tests). **The acceptance as written is not
reachable, and that is a finding rather than a shortfall.** 9–12 and 14 ask
about graph kinds, freeze state, composed dataset labels and thaw records:
those are properties of quipu's meta-graph and store tables, served by
`GET /graphs`, and no SPARQL query over this ontology can reach them. 6 asks
whether a signature *verifies*; SPARQL can fetch the registered public key
and cannot evaluate an ed25519 signature against it. 14's freeze half is
replayable and its thaw half is not. The questions stay as they are — they
are the right questions, and camayoc is the wrong place to answer some of
them from, which is exactly what a competency suite is for.
