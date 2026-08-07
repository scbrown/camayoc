# Competency questions — metrics and nonfunctional requirements

**The ontology states that a metric EXISTS, what it MEANS, who OWNS it, what it
GATES, and HOW TO FETCH IT. It never stores the values.**

That sentence is the whole design constraint, and it is not a stylistic
preference. Two reasons, one principled and one measured:

- **Principled.** `docs/design/ingress.md` rule 5: *"No stored judgment that
  decays (liveness, currency, 'still in progress'). Judgments are queries at read
  time."* A current metric value is the canonical decaying judgment — "latency is
  200ms" is true at write time and false a second later.
- **Measured.** The store this ontology serves runs at parallelism 1.0 behind a
  single mutex and was measured at 112–157% of serial capacity under ordinary
  load. A scrape-interval firehose is not a modelling mistake here, it is an
  outage.

So: time-series systems keep the samples. This ontology keeps **meaning,
ownership, and the retrieval method** — and because it keeps the method, the
values remain reachable from the graph without ever living in it.

## The three entities and why they are separate

    NonFunctionalRequirement   declared   "this store answers under 2s"       — human-rooted, standing
    Metric                     declared   identity, unit, meaning, RETRIEVAL METHOD
    Observation                observed   a violation or a decision-input, NOT every sample

**Requirement and metric are separated deliberately, and this is the load-bearing
choice.** A requirement is what we promised; a metric is a thing we measure that
*claims* to test it. Collapsing them makes the most useful question in this file
unaskable — see Q4.

## Questions

### Existence, meaning, ownership

1. What metrics exist for `<service/component>`, and what does each one mean?
2. Who owns `<metric>` — and is that owner currently able to act? (Joins to the
   liveness questions in the verification slice; alert keepers were found
   pointing at stopped principals seven times out of ten.)
3. What nonfunctional requirements are declared for `<service>`, by whom, and
   when?

### Validity — the question that motivated this slice

4. Does `<alert/metric>` actually measure the requirement it names? What is its
   probe, and has that probe been shown to FAIL when the requirement is violated?
5. Which requirements have NO metric claiming to measure them? (Unmeasured
   promises.)
6. Which metrics measure nothing that is declared? (Orphan instrumentation —
   noise with an owner.)

> **Why 4 exists.** A store alert fired for six hours while the service answered
> in 155ms; separately, an alert's *name* was read as its *mechanism* and drove a
> wrong root cause into an escalation. In both cases the requirement was met, the
> probe disagreed, and nothing in the system could represent the difference. Q4 is
> section A of the verification slice applied one layer up: **an alert whose probe
> cannot fail when the requirement is violated is a check that cannot fail.**

### Retrieval — the ontology as pointer

7. How do I fetch `<metric>` right now — which system, which query, which
   parameters?
8. Which metrics are retrievable from a system that is currently unreachable?
   (A metric whose method cannot run is not a measurement, and must not read as
   healthy.)
9. What did `<metric>` inform — which decisions cite it as evidence?

### History without storing history

10. As of `<date>`, what was the declared threshold for `<requirement>`, and who
    had changed it? (Bitemporal on the DECLARATION, not on the samples — thresholds
    change rarely and the change is exactly what an audit needs.)
11. Which requirements were relaxed, and in service of what decision?

## Retrieval methods are executable, not documentation

A `Metric` carries enough to run: the SYSTEM (`prometheus` | `quipu` | `bd` |
`hank` | `shell`), the QUERY, and its PARAMETERS. This mirrors the named stored
queries this repo already plans (quipu #79) — same idea, other backends.

The payoff is discovery without a human: an agent asking *"is this service
meeting its latency requirement?"* resolves requirement → metric → method →
executes it, with no operator in the loop and no hardcoded endpoint.

Measured cost of not having it: answering "what is CD and why did it stop" took
grepping an ansible role, reading a systemd unit, and finally the journal — three
sources, none discoverable from the others, and the first two answers were wrong.

## Acceptance

The slice is done when 1, 4 and 7 run as named queries against a fixture, **and**:

- **Q7 executes.** A metric's stored method must actually retrieve a value in a
  test, not merely be well-formed. A method that has never run is documentation.
- **Q4 returns non-empty on a seeded fixture** containing an alert whose probe
  cannot fail. A validity question that cannot find a known-invalid alert has the
  defect it exists to detect.
- **Q8 distinguishes UNREACHABLE from HEALTHY.** Not-measured must never render
  as met — the failure this whole stack keeps paying for.
