# Competency questions — crew task lifecycle (slice 1)

The test suite for the first slice. Every ontology term must be owed to a
question here; every question here must eventually run as a named stored
query (quipu #79) against real shantytown records. Parameters in angle
brackets.

## Decisions (the reason this slice exists)

1. What did we decide about `<topic/entity>`, and why?
2. What alternatives were visible when `<decision>` was made?
3. Which decisions were made under `<work-item>`?
4. Which decisions has `<principal>` made, and in which work items?
5. Which decisions about `<entity>` conflict (contested pairs)?
6. What standing (declared) conventions apply to `<area>`?
7. Which decisions were later superseded, and by what?

## Work items

8. What work items touched `<topic/entity>`?
9. What is the full lifecycle of `<work-item>` — created, assigned, worked,
   closed, with timestamps?
10. What work items did `<principal>` work on in `<time-window>`?
11. Which work items closed with outcome `<done|abandoned|superseded|failed>`?
12. What was `<principal>` holding when it stopped at `<time>`? (st's
    `ts`/`item`/`item_status` payload, queryable after the fact)

## Provenance & trust (cross-cutting, from the bootstrap vocabulary)

13. What is the source of `<fact>` — observed record, human declaration, or
    model inference?
14. What knowledge about `<topic>` exists only in the inferred plane (i.e.
    would vanish under a high-trust floor)?
15. As of `<date>`, what did we believe about `<topic>`? (bitemporal replay —
    quipu gives this free; the question pins that the ontology never blocks
    it)

## Acceptance

The slice is done when 1–12 run as named queries against a fixture graph
built from real st records and the answers are accepted as faithful; 13–15
additionally exercise the ingress tags and must return correct plane/tier
attributions.
