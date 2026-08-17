# Design: Camayoc paper plan — how knowledge earns its way into the graph

> **Implementation status (2026-08-17):** 🟡 **Planned.** Nothing drafted. The
> evidence is unusually asymmetric: the *corpus* is strong and already
> taxonomized, the *evaluation* is thin — 4 of 47 competency questions run as
> stored queries. Read
> [`implemented-set.md`](implemented-set.md) before drafting a single sentence;
> it is the gate on what this paper may claim.

## Status

- **Date:** 2026-08-17 (rev 1)
- **Status:** Planning. Boundary agreed; implemented set measured; evaluation gap known and quantified.
- **Related:** [`implemented-set.md`](implemented-set.md) (what may be claimed),
  [`thesis-boundary.md`](thesis-boundary.md) (the camayoc/yupana split),
  [`incident-corpus.md`](incident-corpus.md) (the empirical core),
  [`ingress.md`](ingress.md) (the mechanism),
  [`../vision.md`](../vision.md) (the TrustGraph foil),
  [`../patents/provisional-grounding-cluster.md`](../patents/provisional-grounding-cluster.md) (D — **claims more than is built**).

## 1. Intent and thesis

**Thesis, from the README:** *how knowledge earns its way into the graph, so
that the store never has to trust an extractor.*

Sharpened for a paper:

> A knowledge store that accepts machine-written facts has a trust problem it
> cannot solve internally, because by the time a fact is in the store the
> question "why should I believe this?" has already been answered — badly.
> **The answer must be a refusal at admission, not a confidence score at read
> time.** And the refusal must itself be falsifiable, or it is decoration.

Two halves, and the second is what makes it a paper rather than a design note.
Anyone can add a mandatory provenance tag. The contribution is applying the
same standard *to the checks themselves*: a `Verification` is refused at ingress
unless it names the result that would have proved it wrong.

That constraint sounds pedantic until you have field data. We have field data
(§4), and it says that on one night on a live crew, **eleven separate checks
could not have failed** and were reported as verification by careful people.

## 2. Positioning

### The three-paper program

Worded identically here and in yupana's plan:

- **quipu** compiles SARC into the **store** — submitted, `arXiv:submit/7961151`.
- **yupana** compiles it into the **action**.
- **camayoc** governs **admission** — what may enter at all.

The nearest external anchor is **SARC-DQ**, which quipu's related-work section
describes as gating evidence quality. Evidence quality is precisely camayoc's
territory rather than yupana's, and that is the one-sentence justification for
the admission leg being its own paper.

### The named foil: TrustGraph

Already stated in [`../vision.md`](../vision.md) and it should open the paper,
because it is concrete and it is a real system rather than a straw one:

> The temptation is to bolt an extraction pipeline onto the store. TrustGraph
> and its peers do exactly that, and it works — until you ask "why should I
> believe this fact?" and the answer is "a model wrote it during ingestion."

The paper's structural claim follows: **the extraction layer must live outside
the store, with its own discipline, its own tests, and its own refusals.** Be
fair to the foil — the integrated approach has real ergonomic advantages, and
the paper is stronger for saying so before arguing the trade is wrong for
agent-written knowledge specifically.

### The boundary with yupana

Settled in [`thesis-boundary.md`](thesis-boundary.md) and mirrored in yupana's
plan §2.1. Short version: camayoc owns **admission**, yupana owns **the guard's
non-answers at the action boundary**, neither claims the shared principle, each
cites the other. Two collisions were found and resolved there — the installer
gate proof (camayoc's, yupana cites) and `Empty|Partial|Full` coverage
reporting (convergent, both keep, neither claims).

## 3. Contributions

- **C1 — Provenance-refusing ingress with a closed, per-class-narrowed
  vocabulary.** `aegis:sourceKind` is mandatory and constrained to
  `observed | declared | inferred`; a write carrying an unrecognised value fails
  now, not at read time. Built; refusal tested
  (`tests/test_knot_provenance.py`).
- **C2 — Falsifier-gated verification.** `aegis:falsifier`, `sh:minCount 1`, on
  every `Verification`. A verification that does not name what would have
  disproved it is refused at ingress rather than stored and believed. Built.
  **This is the paper's sharpest single mechanism** and the one with no obvious
  precedent in knowledge-graph ingress.
- **C3 — The incident corpus.** Eleven measured instances of unfalsifiable
  verification and a four-mechanism/one-missing-predicate liveness family, from
  one night on a live crew, taxonomized into seven recurring forms. See §4 and
  [`incident-corpus.md`](incident-corpus.md). **Most papers about verification
  integrity have no field data at all.**
- **C4 — Installation-time gate proof.** Each refusal gate is proven by a probe
  that omits exactly one required property, so the arms discriminate — the
  paper's own thesis applied to the paper's own installer. Built
  (`scripts/gate_probe.sh`, `tests/test_gate_probe.py`); *independence* of the
  arms is open (`camayoc-104`) and is a precondition for claiming C4 as stated.
- **C5 — Liveness by deliberate absence, as a design position.** Judgments that
  decay are never stored; liveness is a read-time join. Claim the position and
  the vocabulary. **Do not claim the mechanism** — see §6.

## 4. The empirical core

Full write-up in [`incident-corpus.md`](incident-corpus.md); source is
`competency/verification-and-liveness.md`, recorded contemporaneously on
2026-08-06/07.

**Section A — verification integrity.** Seven forms, each measured at least
once:

1. a guard documented as belt-and-braces that was the *only* mechanism
2. a byte-identity test that passed against a read-write open
3. a schema check comparing `(type, name)` only, so `ADD COLUMN` was invisible
4. a binding condition whose two branches were the same function
5. a `grep -c` matching the *description* of the bug in the test payload
6. a `grep` against an empty capture whose `0` read as "absent"
7. a "corroboration" equally consistent with both competing hypotheses

The unifying shape — and the sentence the paper should be built around — is
that none of these was a wrong answer. Each was **a check performed against
something adjacent to the claim, and reported as verification.**

**Section B — held-work liveness.** Four simultaneous P1s, one root cause:
every routing mechanism recorded an owner without checking the owner was alive.
Bead assignment, alert keeper labels, `BLOCKED` status, `in_progress` status —
four mechanisms, one missing predicate, identical worst-case consequence: *a
thing correctly detected and correctly recorded is indistinguishable, from every
dashboard, from a thing that was never detected at all.* The sharpest instance
is recursive and should be quoted verbatim: the bead *documenting* invisible
in-progress work, sitting in-progress, invisible, on a stopped agent.

**Section C — armed ≠ merged ≠ correct.** A guard correct in git and absent
from every execution path for 24h; a rules file six weeks stale reaching agents
while the current one sat in the repo.

### The two attacks this section must survive

Named in `camayoc-101` and both are fair:

- **Selection bias.** Were these found by looking for them? What is the
  denominator? A corpus assembled by searching for instances of a pattern
  proves the pattern is findable, not that it is common.
- **Count vs rate.** "Eleven instances" is unanchored. Eleven out of what, over
  what period, on how many agents?

[`incident-corpus.md`](incident-corpus.md) answers both explicitly, including
where the honest answer is "we cannot compute this from the record we kept".
**Do not paper over that.** A corpus with a stated denominator gap is credible;
a corpus with a silent one is not, and the paper's own thesis is that a claim
must name what would falsify it.

## 5. Evaluation — and its honest state

**Methodology: competency questions, which are the standard for ontology work.**
The suite is 47 questions across three slices, machine-readable and watermarked
(`sha256:7a0cc4abad386885`, `scripts/competency.py`). The suite sets its own bar:
*every question must eventually run as a named stored query.*

**Current coverage: 4 of 47 (≈9%).** All four stored queries serve the metrics
slice. The verification-and-liveness slice — the one this paper's corpus is
about — has **zero**.

That is the evaluation section's headline and it must be stated, not managed.
It has a direct consequence for the paper's claim: the corpus in §4 **motivates**
a capability rather than demonstrating one. A reviewer will ask "could your
system have answered these questions on the night?", and today the answer is no.

Three routes, in order of preference:

1. **Close the gap for the slice that matters** (`camayoc-102`): implement Q1–Q13
   as stored queries against a fixture graph. The suite's own acceptance
   criterion already demands that Q2 and Q6 return **non-empty** results on a
   deliberately seeded fixture — *a query that cannot return findings has the
   same defect as the checks in section A, one level up.* That self-application
   is a paper-worthy sentence and it is already written down.
2. **Report per-question coverage as a result**, using the `Empty | Partial |
   Full` verdict the tooling already produces, and treat the gaps as findings —
   a question that cannot be expressed as a query is an ontology gap
   (`camayoc-b6h`).
3. Draft without an evaluation and submit as a design paper. **Not recommended**;
   the competency-question methodology is the reason an ontology paper is
   reviewable at all, and skipping it forfeits the strongest available frame.

**Route 1 is the recommendation, and it is the critical path.** Everything else
in this plan is writing; this is the only item that requires building.

## 6. Scope boundaries (honest)

From [`implemented-set.md`](implemented-set.md), which is authoritative:

- **Quarantined inference and governed promotion are NOT built.** D discloses
  them as the primary contemplated embodiment. Zero non-doc references exist:
  an inferred-tagged node lands exactly where an observed one does, and
  quarantine is skill discipline only. They go in **future work with the
  blocker named** (`camayoc-s0h` carries measured citations to two specific
  quipu gaps). A paper that inherits D's framing describes a system that does
  not exist.
- **Tier-honest serving is yupana's.** Camayoc defines and mandates the tag;
  yupana serves under it. Claim the vocabulary, not the serving.
- **Typed non-answers: one instance, not a taxonomy.** `NO COVERAGE` on the
  ontology's own coverage. The systematic taxonomy is yupana's.
- **Liveness: a position and a vocabulary, not a mechanism.** The terms exist
  (`ontology/core.ttl:74, :87`) and the refusal to synthesise a write-time
  liveness predicate is explicit and deliberate
  (`shapes/core.shapes.ttl:130`). The read-time queries do not exist.

## 7. Paper outline

1. **Introduction** — the TrustGraph question: why should I believe this fact?
2. **Background** — SARC and SARC-DQ; the three-paper program; what quipu and
   yupana already claim.
3. **The admission problem** — why a store cannot solve trust internally.
4. **Mechanism** — closed provenance vocabulary, write-time refusal, the
   falsifier constraint on `Verification`.
5. **Proving the gates** — installation-time probes, one omitted property each,
   arms that discriminate. Self-application of the thesis.
6. **Field evidence** — the incident corpus, with denominator and rate stated.
7. **Evaluation** — competency questions, per-question coverage, gaps as
   findings.
8. **Limitations** — §6, in full and unhedged.
9. **Related work** — TrustGraph and extraction-in-store platforms; SARC-DQ;
   provenance vocabularies (PROV-O — say plainly why `sourceKind` is narrower
   and why narrowness is the point); SHACL validation as a gate rather than a
   report; ontology competency questions (Grüninger & Fox) as evaluation
   methodology.
10. **Conclusion.**

## 8. Build order

1. ~~Agree the yupana boundary~~ — done, [`thesis-boundary.md`](thesis-boundary.md).
2. ~~Produce the implemented set~~ — done, [`implemented-set.md`](implemented-set.md).
3. ~~Write up the incident corpus with denominator and rate~~ — done, [`incident-corpus.md`](incident-corpus.md).
4. **Prove the gate probes adversarially** (`camayoc-104`) — precondition for C4.
5. **Close the competency-query gap for the verification slice** (`camayoc-102`)
   — the critical path, and the only build work.
6. Draft §§1–5 from the mechanism docs; they are stable.
7. Draft §7 last, against whatever coverage step 5 actually reaches.

## 9. What this paper is not

- Not a retrieval paper. That is bobbin's, and its own measurement problems are
  documented there.
- Not a store paper. Quipu's is submitted and its evaluation is spent.
- Not a guard paper. Yupana owns the action boundary and the non-answer
  taxonomy.
- Not a claim that quarantined inference works. It is not built.
