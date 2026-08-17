# The camayoc / yupana thesis boundary

> **Implementation status (2026-08-17):** ✅ **Proposed and written down on both
> sides.** Agreed by: pending keeper sign-off. The mirror of this section is in
> `yupana/docs/design/paper.md` §2.1; if the two ever disagree, neither paper
> should draft until they are reconciled.

## Why this exists before either paper drafts

`camayoc-105` names the risk precisely: both papers instantiate one principle —
**a check that cannot fail is not a check, and absence of a finding is not a
finding of absence** — and if both claim it, reviewers see one idea published
twice and both papers weaken.

Retrofitting a boundary after two drafts exist is much harder than agreeing one
now, so this is written before drafting rather than after.

## The split

**The shared principle is cited by both and claimed as a contribution by
neither.** It is older than either system. What each paper contributes is a
*layer* at which the principle is enforced, and the mechanisms that enforcement
required.

| | **camayoc** | **yupana** |
|---|---|---|
| **Layer** | Admission — what may enter the graph at all | Action — what a guard may report at the edit boundary |
| **Question** | Should this fact be stored? | Should this action proceed, and what may silence mean? |
| **Time** | Write time | Action time |
| **Mechanism** | Refusal at ingress (SHACL) | Typed verdicts from a hot projection |
| **Owns** | Provenance-refusing ingress; falsifier-gated verification; the closed source-tier vocabulary; the incident-night corpus | The non-answer taxonomy: `vacuous` ≠ pass, `unevaluated` ≠ skipped, `served_from_cache` ≠ `fail_open`, `unknown` ≠ `unsatisfied`, empty-board refusal, STALE-with-AGE |
| **Evidence** | 47 competency questions, the 2026-08-06/07 incident corpus, refusal tests | Guard latency, degradation under load, NeuralAmplifier as a second domain |

Put in one line each:

- **camayoc**: *knowledge must earn its way in, and a verification that cannot
  fail has not earned anything.*
- **yupana**: *a guard that returns nothing must say which kind of nothing.*

Each paper cites the other for the layer it does not own.

## Two collisions the bead did not anticipate

Reading both plan docs against each other turned up two places where the split
above is not self-executing. Both must be settled before drafting.

### Collision 1: the installation-time gate proof

`yupana/docs/design/paper.md` §4 closes with:

> the installer proving each refusal gate with deliberately invalid probes that
> each omit exactly one required property, so the arms discriminate

That is **camayoc's mechanism**, described in yupana's paper. It lives here:
`scripts/gate_probe.sh` (248 lines) and `tests/test_gate_probe.py` (302 lines),
and establishing that the arms genuinely discriminate is an open camayoc bead
(`camayoc-104`).

**Proposed resolution: camayoc owns it, yupana cites it.** The reasoning is that
the probes prove *admission* gates — they establish that a refusal shape is
enforced rather than merely declared, which is the admission thesis applied to
camayoc's own installer. Yupana's use of the same idea is a one-line citation,
not a contribution, and the sentence above should become a citation in yupana's
draft.

This is a nice piece of self-application and worth a sentence in camayoc's
write-up: the paper's own thesis, turned on the paper's own installer. Yupana
calls the same discipline *non-vacuity*; the papers should use one name for it,
and since the mechanism sits here, camayoc's term should follow yupana's
existing published usage rather than mint a second one.

### Collision 2: `Empty | Partial | Full` coverage reporting

Both systems report coverage as a graded verdict rather than a bare count:

- camayoc: `scripts/competency.py` returns `Empty | Partial | Full` for ontology
  coverage, with a `NO COVERAGE` outcome.
- yupana: dataset coverage reported as `empty | none | partial | full`.

**Proposed resolution: no exclusivity is needed, because neither paper claims
the shape as a contribution.** They apply it to different objects — an
ontology's reach versus a dataset's population — and each should cite the other
as an independent instance. Two systems converging on the same reporting shape
from different directions is *evidence for* the principle, and is worth one
sentence in each paper saying so. What must not happen is either paper
presenting the shape as novel.

## What this costs camayoc, stated plainly

The boundary is not free, and the paper should not pretend otherwise.

Handing the non-answer taxonomy to yupana means camayoc gives up its most
immediately legible contribution — ten crisp distinctions, each forced by an
incident, is very good paper material. What camayoc keeps is narrower and
harder to make vivid: a write-time refusal, a mandatory falsifier, and a
corpus.

Two things make that a good trade. First, camayoc's typed non-answers are
**one** instance (`NO COVERAGE`, on the ontology's own coverage — see
`implemented-set.md` aspect 8), while yupana's are a systematic taxonomy with
per-distinction incident provenance. The stronger claim belongs where the
stronger evidence is. Second, camayoc's retained territory contains the thing
neither other paper can claim: **the incident-night corpus**, eleven measured
instances of unfalsifiable verification on a live crew. Most papers about
verification integrity have no field data at all.

## Relationship to the third leg

Both papers sit in a three-paper program and should say so identically:

- **quipu** compiles SARC into the *store* — submitted, arXiv:submit/7961151.
- **yupana** compiles it into the *action*.
- **camayoc** governs *admission* — what may enter at all.

The nearest external anchor for camayoc is SARC-DQ, which quipu's related-work
section describes as gating evidence quality; evidence quality is camayoc's
territory rather than yupana's, and that is the cleanest one-sentence statement
of why the admission leg is a separate paper.
