# camayoc - Agent Instructions

## Project Overview

The knot-keeper: bootstrap ontology, knowledge ingress discipline, and
knowledge-pack production for the quipu stack. Camayoc owns what facts MEAN
and how they EARN their way into the graph; it is deliberately not a store
(quipu), not a harness (shantytown), and not retrieval (bobbin).

Sibling repos: scbrown/quipu (governed store), scbrown/shantytown (crew
harness), scbrown/hank (code structure), scbrown/bobbin (retrieval).

## Conventions

- **Competency questions before classes.** No ontology term without a question
  in competency/ that needs it; the question suite is the test suite.
- **Reuse before minting** — aegis:/prov:/quipu:/bobbin: vocabularies first;
  camayoc: only for genuinely unowned terms. Namespaces are parameters, never
  hardcoded hostnames.
- **rdfs:range only, never rdfs:domain** on shared predicates.
- **Facts true at write time; judgments at read time.** Nothing stored that
  decays.
- **Deterministic-first ingress**; model-inferred facts land quarantined in
  low-trust planes, tagged, never masquerading.
- Design docs live in docs/design/ with an implementation-status banner in
  the quipu house style.

## Build Commands

```bash
just check           # markdown lint (grows the competency eval gate)
just test            # placeholder until slice 1
```

## Before Every Push

Run `just check`. Do not push on failure. Work is not complete until
`git push` succeeds.
