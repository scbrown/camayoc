# The implemented set — what the paper may claim

> **Implementation status (2026-08-17):** ✅ **Current.** Every row below was
> measured against this repo at the commit shown, with the grep or file that
> produced it. Re-run before drafting; do not carry a row forward on trust.

`camayoc-100` exists because a provisional patent and a systems paper have
different standards of proof. **A patent may claim constructively reduced
embodiments. A systems paper may claim only what is built and measured.**
Provisional D discloses eight aspects. This document states, per aspect, what
is built, what is partial, and what is design-only — so drafting starts from
the implemented set rather than from D's table of contents.

Getting this wrong is the fastest route to an unrecoverable review: a reviewer
who finds one unbuilt claim stops believing the built ones.

## Verdict table

| # | D aspect | State | Evidence |
|---|----------|-------|----------|
| 1 | Provenance-refusing ingress | ✅ **Built** | `shapes/core.shapes.ttl` makes `aegis:sourceKind` mandatory; `shapes/code-entities.ttl:50` constrains it to the closed `observed\|declared\|inferred` vocabulary. Refusal proven, not asserted — `tests/test_knot_provenance.py` (216 lines). |
| 2 | Quarantined inference | ❌ **Design-only** | `docs/design/ingress.md:53-63` defines the planes; **zero non-doc references**. No script names a graph, no shape targets one, no query has a `GRAPH` clause. An inferred-tagged node lands exactly where an observed one does. Blocked on quipu — see `camayoc-s0h`. |
| 3 | Governed promotion | ❌ **Design-only** | `docs/design/ingress.md:109-111` defines it; no implementation. Doubly blocked: it is a graph *move* between planes, and the planes do not exist. See `camayoc-mip`. |
| 4 | Falsifier-gated verification | ✅ **Built** | `shapes/core.shapes.ttl:85-89` — `aegis:falsifier`, `sh:minCount 1` on `Verification`, with the refusal message. Probed by `scripts/gate_probe.sh`; the probe's own discrimination is `camayoc-104`. |
| 5 | Liveness by deliberate absence | 🟡 **Partial — and the partiality is the point** | The *vocabulary* exists (`ontology/core.ttl:74, :87` — `executionPath`, `pathOwner`), and the deliberate absence is explicit at `shapes/core.shapes.ttl:130`: liveness "belongs with hank/quipu, not a made-up write-time liveness rule". What does **not** exist is the read-time side: the liveness questions (verification-and-liveness #6-10) have **no stored queries**. See §2. |
| 6 | Installation-time gate proof | ✅ **Built** | `scripts/gate_probe.sh` (248 lines) with `tests/test_gate_probe.py` (302 lines) holding the probes to being able to fail. Independence of the arms is **not** yet established — `camayoc-104`. |
| 7 | Tier-honest serving | 🟡 **Partial** | `aegis:tier` is carried on policies (`shapes/policies/edit-grounding.ttl:49, :71, :78`) and the tier vocabulary is in `ontology/core.ttl:54`. But camayoc does not *serve* facts — yupana does. What camayoc owns is the tag's definition and its mandatory-ness, not the serving. **Claim the vocabulary; do not claim the serving.** |
| 8 | Typed non-answers | 🟡 **Partial, one instance** | Fully realised in exactly one place: `scripts/competency.py` returns `Empty \| Partial \| Full` with a `NO COVERAGE` verdict, method/threshold/watermark carried, 18 tests. That is a real instance of the discipline. It is **one** instance, on the ontology's own coverage, not a general non-answer taxonomy across camayoc's surfaces. |

**Summary: three built, three partial, two design-only.**

## 1. What this means for the paper

**Claim without qualification (aspects 1, 4, 6).** Provenance-refusing ingress,
falsifier-gated verification, and installation-time gate proof are built, tested,
and — critically — their *refusals* are tested, not just their acceptances. These
three are the paper's spine and they are strong: the falsifier shape in
particular is a genuinely unusual constraint to enforce at write time, and it is
enforced.

**Claim narrowly, with the boundary stated (aspects 5, 7, 8).**

- *Liveness by deliberate absence* should be claimed as a **design position**
  with a vocabulary, not as a mechanism. The position is defensible and
  interesting — refusing to synthesise a write-time liveness predicate, because
  liveness is a read-time join against a store that actually knows — and
  `shapes/core.shapes.ttl:130` shows the refusal was deliberate rather than
  an omission. But the paper must not imply the liveness questions are
  answerable today. They are not; see §2.
- *Tier-honest serving* is yupana's, not camayoc's. Camayoc defines and mandates
  the tag; yupana serves under it. Claim the former. This is also the cleanest
  illustration of the boundary in `docs/design/paper.md` §2.
- *Typed non-answers* should be claimed as **one worked instance**
  (`NO COVERAGE` on ontology coverage) that demonstrates the discipline, with
  the general taxonomy attributed to yupana's guard, which has ten distinctions
  and the incidents that forced each.

**Do not claim, at all (aspects 2, 3).** Quarantined inference and governed
promotion are D's headline pairing and they are **not built**. They go in future
work with the blocker named — both wait on quipu gaining graph-targeting on
`/knot` and a label-set route (`camayoc-s0h` carries the measured citations).

This is the single most important line in this document. D discloses quarantine
and promotion as the primary contemplated embodiment. A paper that inherits that
framing describes a system that does not exist.

## 2. The gap the audit surfaced: liveness is unqueryable

Aspect 5 turned up something the bead did not anticipate and that
`camayoc-102` needs.

The competency suite is 47 questions across three files
(`sha256:7a0cc4abad386885`). The repository contains **four** stored queries,
all in `queries/`, and all four serve the *metrics* slice:

```console
$ ls queries/
camayoc_metric_reachability_candidates.json
camayoc_metric_retrieval_method.json
camayoc_metrics_for_subject.json
camayoc_unvalidated_metric_claims.json
```

So the **verification-and-liveness slice has zero stored queries** — including
the four-beads-one-cause family (#6-#10) that `camayoc-101` proposes as the
paper's empirical core, and the falsifier questions (#1-#5) that motivate the
aspect the paper is strongest on.

That is a coverage figure of **4/47 ≈ 9%**, and it is the honest headline for
the evaluation section rather than something to work around. The competency
suite's own rule — every question must eventually run as a named stored query —
is currently met by under a tenth of it.

The consequence for drafting order is concrete: `camayoc-101` proposes writing
up the incident night as a labelled corpus, and the natural reviewer question is
"could your system have *answered* these questions at the time?". Today the
answer is no, because the queries do not exist. Either they get written
(`camayoc-102`), or the paper is explicit that the corpus motivates a
capability rather than demonstrating one.

## 3. Method

Each row was produced by grepping for the mechanism outside `docs/` and
`competency/` — a term that appears only in design prose is design-only by
definition, which is exactly how aspects 2 and 3 were classified. Gates green at
the time of writing: `just test` 46 passed (1 skipped), `just check` 0 issues
across 17 files.
