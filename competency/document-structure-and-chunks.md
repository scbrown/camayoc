# Competency questions — document structure and chunks

The test suite for the document-structure slice. Bobbin chunks source files
and documents into retrievable pieces and now emits deterministic
relationships between them (adjacency, containment); those facts are headed
for the graph, and `shapes/code-entities.ttl` already ships advisory shapes
for `bobbin:CodeModule`, `CodeSymbol`, `Document`, `Section`, `Bundle`, and
`Commit` with no question suite behind them. This file closes that gap
retroactively and covers the chunk terms before they are minted
(`bobbin:Chunk`, `bobbin:nextChunk`, chunk-level `bobbin:inDocument`,
`bobbin:chunkOrder`). Same discipline as the earlier slices: every ontology
term must be owed to a question here, and every question must eventually run
as a named stored query (quipu #79) against real records. Parameters in
angle brackets.

## A. Membership — "what is this a part of?"

1. Which document or module is chunk `<chunk>` part of?
2. Which chunks make up `<document>`, and in what order do they appear?
3. Which section of `<document>` does chunk `<chunk>` fall inside, and what
   is that section's heading?

## B. Order and adjacency — "what comes next?"

4. What chunk immediately follows `<chunk>` in its document, and what
   immediately precedes it?
5. Reading `<document>` start to finish, what is the sequence of its
   sections at each heading depth?
6. What is the first chunk of section `<section>` — the place an agent
   should start reading?

## C. Hierarchy — "what contains what?"

7. What is the parent section of `<section>`, and what are its child
   sections?
8. Which sections of `<document>` sit at heading depth `<n>`?
9. Which standalone blocks (tables, fenced code) belong to section
   `<section>`?

## D. Code and document entities — the terms already shipped

These retroactively cover the classes and predicates `shapes/code-entities.ttl`
has enforced since the first repo ingest, which until now had no question
owing them.

10. Which symbols are defined in module `<module>`, and of what kind?
11. Which sections, in which documents, mention symbol `<symbol>`?
12. Which repository does entity `<entity>` come from, and under what file
    path?

## E. Provenance and change — "is this still true?"

13. Has the content of chunk `<chunk>` changed since `<timestamp>` — does
    its recorded content hash still match?
14. For a chunk-level fact such as adjacency or containment, what is its
    source: parser-observed at index time, or inferred by a model — and in
    which trust plane does it live?

## Acceptance

The slice is done when 1–9 run as named queries against a fixture graph
built from a real bobbin chunk export and the answers are accepted as
faithful; 10–12 additionally run against the already-live code-entity graph
(three repos, ingested hourly); 13–14 must return correct provenance and
plane attributions, never presenting an inferred relationship at observed
standing. No chunk term is minted in `ontology/core.ttl` or constrained in
shapes beyond advisory (`sh:nodeKind`/datatype) until the emitter that
writes it is measured live.
