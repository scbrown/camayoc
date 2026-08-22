# The 2026-08-06/07 incident corpus

> **Implementation status (2026-08-22):** 🟡 **Labelled, denominator
> incomplete.** The instances and their taxonomy are recorded
> contemporaneously and are solid. The **rate** the paper needs is *not*
> computable from the record as it was kept, and §4 says so explicitly rather
> than estimating one. §5 specifies the instrumentation that would fix this
> for the next window — audited 2026-08-22, none of it is buildable in
> camayoc alone: items 1–2 need the refusal side recorded somewhere queryable,
> and a refused write never enters the graph, so that count lives with quipu's
> refusal path; item 3 depended on the cost-accounting vocabulary, which
> landed later on 2026-08-22 (`camayoc-e29` — the terms and stored queries
> exist; the parser that fills them for a live window is still to build).
> Tracked as `camayoc-0d3` rather than left as prose.
> (§4.2's own lesson bit this repo once more meanwhile: the coverage tool's
> verification denominator was itself undercounted until 2026-08-22 — six §D
> questions were missing from it.)

Source of record: [`../../competency/verification-and-liveness.md`](../../competency/verification-and-liveness.md),
written during and immediately after the night of **2026-08-06/07** on a live
crew. This document turns that prose into a labelled corpus with the taxonomy
as categories, per `camayoc-101`.

## 1. Why this is the paper's strongest asset

Papers about verification integrity are usually arguments. This one has
instances: **eleven separate checks that could not have failed**, observed in
one night, on a running multi-agent crew, recorded by the people who were
fooled by them rather than reconstructed afterwards by someone looking for
examples.

The unifying observation, and the sentence the paper should be built on:

> The night's dominant failure was not a wrong answer. It was **a check
> performed against something adjacent to the claim, reported as verification,
> by careful people.**

"By careful people" is load-bearing. Nothing here is explained by negligence,
which is what makes it a systems problem and therefore an admission-gate
problem.

## 2. Category A — verification integrity

Seven recurring forms. Each was observed at least once; the eleven instances
distribute across these seven forms (per-form counts are **not** recoverable —
see §4.2).

| ID | Form | What was checked | What was claimed | The adjacency |
|----|------|------------------|------------------|---------------|
| **A1** | Redundancy that wasn't | One guard present and working | "Belt and braces — there's a second mechanism" | The documented backup did not exist. The single point of failure was documented *as* a redundancy. |
| **A2** | Right test, wrong mode | Byte identity of a file | "The file is unchanged on disk" | The comparison ran against a **read-write open**, so it compared the buffer to itself. |
| **A3** | Partial-key comparison | Schema `(type, name)` | "The schema matches" | `ADD COLUMN` changes neither type nor name of existing columns, so the whole class of additive migration was invisible to the check. |
| **A4** | Branches that don't branch | A binding condition with two arms | "Both paths are covered" | Both arms called **the same function**. The conditional was decorative. |
| **A5** | Matching the description, not the thing | `grep -c` over a test payload | "The bug signature is present/absent" | The payload contained a *description* of the bug. The grep matched the prose, not the behaviour. |
| **A6** | Zero-from-nothing | `grep` over a capture | "Absent — count is 0" | The capture was **empty**. A `0` from an empty input and a `0` from a populated one are different facts; the check could not tell them apart. |
| **A7** | Corroboration that doesn't discriminate | Evidence consistent with hypothesis H1 | "This confirms H1" | The same evidence was **equally consistent with H2**. It had no discriminating power between the live hypotheses. |

**The falsifier test applied to each.** For every row, ask the constraint
camayoc enforces at ingress — *what result would have proved this wrong, and
could the check have produced that result?*

- A1, A4: no. The check's output was independent of the property claimed.
- A2, A6: no, **given the conditions on the night**. Under other conditions
  (read-only open; non-empty capture) the same check is sound. This is the
  distinction competency question #5 preserves deliberately: a check in an
  adjacent setting is valid exactly when the mechanism under test does not
  depend on the variable that changed. These two are not bad checks; they are
  sound checks run outside their preconditions, which the falsifier field would
  have surfaced by forcing the precondition to be named.
- A3: partially — it could fail for a renamed or retyped column, never for an
  added one. **A falsifier scoped narrower than the claim.** The most insidious
  form, because the check does work sometimes.
- A5, A7: no. Both could return "confirmed" under the negation of the claim.

**This is the paper's argument in miniature and it should be presented exactly
this way.** Not "these were bad checks" — a reader nods and moves on — but
"here are seven checks, and the single question `what would have falsified
this?` separates all seven from verification, mechanically, without hindsight."
A3 in particular is where the mandatory `falsifier` field earns its keep: a
human writing "renamed or retyped column" into the field has, in that act,
noticed that `ADD COLUMN` is not covered.

## 3. Category B — held-work liveness, and Category C — armed ≠ merged

**B: four mechanisms, one missing predicate.** Four P1s open simultaneously,
one root cause: *every routing mechanism recorded an owner without checking the
owner was alive.*

| Mechanism | Recorded | Never checked |
|---|---|---|
| Bead assignment | assignee | assignee running? |
| Alert keeper labels | keeper | keeper running? |
| `BLOCKED` status | blocker | blocker still real? |
| `in_progress` status | holder | holder running? |

Consequence identical in all four, and worst-possible: *a thing correctly
detected and correctly recorded is indistinguishable, from every dashboard,
from a thing that was never detected at all.*

Measured durations: a P1 blocked **14 days** on a dependency that had already
cleared; a retraction that never propagated for **14 days**; a CI break unread
for **6 hours across 12 production deploys**.

The sharpest instance is recursive and should be quoted verbatim in the paper:
**the bead documenting invisible in-progress work was itself sitting
in-progress, invisible, on a stopped agent.**

**C: armed ≠ merged ≠ correct.** A guard correct in git and absent from every
execution path for **24h**; a config feature landed, tested, and inert until
armed; a rules file **six weeks** stale reaching agents while the current one
sat in the repo; **17** host execution paths running scripts out of individual
working trees.

B and C are the same defect at different layers: a fact recorded at write time
that silently decays. They are why ingress rule 5 refuses to store decaying
judgments at all, and why liveness is a read-time join rather than a stored
predicate.

## 4. The two attacks, answered

`camayoc-101` names both, and they are the right attacks.

### 4.1 Selection bias: were these found by looking for them?

**Partly, and the corpus must say so.**

Honest reconstruction of how the instances surfaced:

- **The Category B family was not sought.** Four P1s were open simultaneously
  and the common cause was noticed *because* they collided. This is closer to a
  census than a search: the population is "P1s open that night", and the
  discovery was of a shared cause, not of instances of a pattern.
- **The Category A instances were partly sought.** Once A1 was found — a
  documented redundancy that did not exist — the crew began asking the falsifier
  question of other checks, and found more. **The first instance was
  incidental; later ones were elicited by a search.**

This matters and cuts a specific way. A corpus assembled by searching for a
pattern demonstrates that the pattern is *findable*, not that it is *common*.
So the corpus supports:

> ✅ "When we asked what would have falsified each check, checks failed that
> question at a rate that surprised us, across seven distinct forms."

and does **not** support:

> ❌ "N% of verifications in this codebase are unfalsifiable."

The paper must make exactly the first claim. The second requires a denominator
we do not have.

### 4.2 Count versus rate: eleven out of what?

**The denominator is not recoverable from the record as kept.** Stating this
plainly is the only defensible option, and it is consistent with the paper's own
thesis: a claim must name what would falsify it, and "eleven instances" names
nothing.

What *is* anchored:

| Quantity | Value | Confidence |
|---|---|---|
| Instances of unfalsifiable verification | 11 | Recorded contemporaneously |
| Distinct forms | 7 | Recorded |
| Window | one night, 2026-08-06/07 | Recorded |
| Simultaneous P1s sharing one root cause | 4 | Recorded |
| Routing mechanisms missing the liveness predicate | 4 of 4 examined | Recorded — **this one is a rate** |

What is **not** anchored, and must not be estimated:

- **Total verifications performed that night.** Not counted. Without it there is
  no "11 out of N".
- **Per-form counts.** Eleven instances across seven forms; the distribution was
  not recorded.
- **Crew size and agent-hours.** Not captured in the record, so no per-agent or
  per-hour normalisation.

**The one genuine rate in the corpus is Category B: 4 of 4.** Every routing
mechanism examined lacked the liveness predicate — a complete census of a small,
enumerable population, with no selection step, because the four were identified
by their collision rather than by a search. That is the number the paper should
lead with when a rate is demanded, and it should be presented for exactly what
it is: a small denominator, completely enumerated.

## 5. What would fix this for the next window

Concrete instrumentation, so the gap is a finding with a remedy rather than an
apology:

1. **Count the denominator at ingress.** Once `Verification` is a shape-gated
   class, every accepted verification is a stored fact. Total accepted, total
   refused for a missing falsifier, and the ratio become queryable — and the
   refusal count is itself the rate this corpus lacks, measured prospectively
   and without a search step.
2. **Record the form.** A controlled vocabulary over A1–A7 on refused
   verifications gives per-form counts directly.
3. **Normalise by agent-hours**, available from the cost-accounting slice
   (competency §D, Q17) — both harnesses already write complete per-session
   token accounting to local disk, so agent-hours are a deterministic-parser
   fact and need no new plumbing.

Note the shape of this: **the mechanism the paper proposes is also the
instrument that would have measured the problem it was built for.** That is
worth one sentence in the paper and no more — it is a genuine property of the
design, and overselling it would be its own unfalsifiable claim.

## 6. How to use this corpus in the paper

- **Lead with A1–A7 and the falsifier question applied to each.** It is
  concrete, it is mechanical, and it requires no hindsight.
- **Use B's 4-of-4 as the rate**, with the small enumerated denominator stated.
- **Put §4 in the paper, not in an appendix.** A corpus that names its own
  selection bias and its own missing denominator is more credible than one that
  does not, and this paper in particular cannot argue that claims must be
  falsifiable while making an unfalsifiable one about its own evidence.
- **State that the LIVENESS corpus motivates the mechanism rather than
  validating it.** As of later on 2026-08-22 the scope of that sentence
  narrowed: the cost/denominator family (§D, Q16–21) and the section-A
  single-edge questions (Q3/Q4/Q5/Q7/Q12) run as stored queries
  (`camayoc-89e`, `camayoc-e29`; 16/19 on that slice, up from 5/19 that
  morning — the "4 of 47" this bullet cited on 2026-08-17 predates the
  golden-paths slice's 12/16). What still does not exist is the
  liveness-join family (#6, #8, #9) — the four-beads-one-cause questions
  themselves — which remain GAP rows in `just query-coverage`; see
  [`implemented-set.md`](implemented-set.md) §2. For section B the corpus
  is still the *problem statement*, with the evaluation to follow.
