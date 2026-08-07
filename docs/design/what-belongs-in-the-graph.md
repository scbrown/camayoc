# Design: what belongs in the graph

> **Status (2026-08-07):** guidance, derived from measured incidents on a live
> crew. No classes proposed here — this is the decision procedure that should
> precede proposing any.

Four properties decide whether a fact belongs in this ontology: **decay,
reproducibility, truthiness, importance**. They are not a scoring rubric. They
are an ordered procedure, and two of them interact in a way that is easy to miss.

## 1. Does it DECAY? — if yes, never store it

A fact that stops being true is a liability, not knowledge. `ingress.md` rule 5
already forbids the shape: *"no stored judgment that decays (liveness, currency,
'still in progress'). Judgments are queries at read time."*

Canonical decaying judgments: current latency, is-this-agent-alive, is-this-work-
in-progress, remaining quota. **Store none of them.** Store what makes them
answerable — a retrieval method, an event stream, a definition.

Measured cost of getting this wrong in the other direction: alert keeper labels
are static while liveness is not, so seven of ten active alerts were owned by
principals that had stopped, and nothing reported it.

## 2. Is it REPRODUCIBLE? — if yes, store the method, not the value

Can the fact be re-derived from a durable source?

- **Reproducible** — metric definitions (re-parse the rules), code structure
  (re-walk the repo), token counts (re-read the session files). Storing these is
  a *cache*: losing it costs re-derivation, not knowledge.
- **Not reproducible** — why a decision was made, what alternatives were visible,
  what an agent was holding when it stopped, a lesson learned at 3am. The graph
  is the **only copy**. Losing it is permanent.

The graph's real job is the second category. The first belongs in it only as a
pointer — which is the whole design of the metrics slice: *the ontology says the
metric exists, what it means, who owns it, and how to fetch it; the samples live
in the time-series system.*

## 3. ⚠ REPRODUCIBILITY HAS A HALF-LIFE — and this is the trap

"Reproducible" is a claim about a source that still exists. **Check the source's
retention before deciding to store only the method.**

Measured on a live host, 2026-08-07, while designing exactly this:

    claude transcripts   709 files, oldest ~27 days old
    codex sessions       7 files, all from the day codex was installed
    retention policy     NONE CONFIGURED, in either tool or in cron

So token-cost facts are reproducible *today* and unverified for next month. Two
readings, both bad and both unmeasured: if something prunes at 30 days, the
oldest are about to vanish; if nothing ever prunes, this is unbounded disk growth
nobody is watching.

**Consequence, and it revises the metrics decision rather than contradicting it.**
Metric *samples* are reproducible from a TSDB with a stated retention — store the
method. Token *costs* are reproducible from files with **unknown** retention, and
a cost-per-work-item is small, final, and joins to entities already modelled —
**store the aggregate**, not just the reader. The rule is not "never store
reproducible facts"; it is *store the method when the source will outlive the
question, and the value when it will not*.

## 4. TRUTHINESS matters most where reproducibility is lowest

`sourceKind` does its heaviest work in exactly the place the graph is most needed.
A reproducible fact can be re-checked, so a wrong tag is recoverable. A
non-reproducible fact can only be *trusted* — nothing can ever re-derive it.

Which produces the uncomfortable quadrant: **high value, not reproducible,
`inferred`.** Session lessons, failure diagnoses, "we tried X and it did not
work." The most expensive knowledge this stack handles is also the least
trustworthy by tag and the most fragile.

That is an argument for capturing it aggressively *into the low-trust plane* —
not for relaxing the tag. Quarantine plus a promotion path is what lets valuable
uncertain knowledge exist at all without contaminating what is certain
(`ingress.md` rule 4).

## 4b. DURABILITY IS THE ADDRESSABLE FORM OF REPRODUCIBILITY — declare it, do not infer it

Sections 2 and 3 leave "is the graph the only copy?" as something a reader
*infers* from whether a derivation method is present. That is too weak to act on.
An inferred property can only be queried by ABSENCE — "show me facts missing a
field" — which is a different and worse question than the one that matters:

    which facts would be LOST if this store were lost?

So durability is **declared explicitly**, per fact:

    SoleRecord    the graph is the only copy. Loss is permanent.
    Reproducible  re-derivable from a source that still exists.
    Backed        independently persisted outside this store.

**It composes.** A derived fact is only as durable as its least durable input —
join a sole-record fact with a backed-up one and the result is sole-record,
because you cannot reconstruct it without the fragile part. That is a meet, which
makes durability a lattice axis alongside trust and freshness, while the
derivation *method* stays a per-fact value (two methods do not meet into a third).

**Two constraints inherited from the freshness axis, both mandatory:**

- **Declared, never synthesized.** Nothing may infer `Backed` because a backup
  ran once. The existing freshness type states the rule for itself — *"a producer
  declares it; there is no synthesized fresh tag, ever"* — and it holds here.
- **Undeclared is undeclared.** An unknown or missing durability must never
  default to `Backed`. Not-measured rendering as safe is the exact failure this
  whole document exists to prevent.

**And durability decays, for the reason in §3.** `Reproducible` is a claim about a
source that still exists; when that source rotates, the fact silently becomes
`SoleRecord` and nothing notices. The tag records what a producer asserted at
write time, so something must periodically re-assert or downgrade it — the same
cadence problem freshness has, which is the argument for putting both on the same
machinery rather than in prose.

## 5. IMPORTANCE gates CURATION, not storage

Importance should decide what earns an agent's attention, never whether a fact is
allowed in. Storage is cheap; curation is not.

And importance is usually only knowable **later**. "st reports success for a
message that never arrived" read as a papercut until it silently stranded a
production go-ahead. A filter applied at write time on *predicted* importance
will discard the thing that mattered.

## The procedure, condensed

    decays?              -> do not store. store what makes it answerable.
    reproducible?        -> store the method — IF the source outlives the question.
                            check retention. it is a claim, not a property.
    not reproducible?    -> the graph is the only copy. store it, and the
                            sourceKind tag is carrying the entire weight.
    importance           -> sets curation effort. never a write-time filter.
