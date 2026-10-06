# Example queries and setups

A starter library of stored queries for the questions most graphs get asked
first, and three setup recipes that say which shapes and queries to install
for a given kind of graph. Every example is a quipu stored query: load it with
`quipu_queries`, ask it with `quipu_ask`, and ship it to someone else inside a
qpack, where it travels as the share's sealed `queries.ttl` member.

| Query | Asks | Parameters |
|---|---|---|
| `camayoc_ex_ready_work` | open work items whose every `blockedOn` target is closed | none |
| `camayoc_ex_blocked_by_chain` | everything an item waits on, transitively | `item` (IRI) |
| `camayoc_ex_my_plate` | open work items assigned to a principal | `assignee` (IRI) |
| `camayoc_ex_recently_changed` | work items with a tracker observation at or after an instant | `since` (ISO-8601) |
| `camayoc_ex_who_said_this` | every claim about a subject, with its `sourceKind`, decider and observation time | `subject` (IRI) |
| `camayoc_ex_stale_facts` | anything whose `reviewAfter` has passed | `asof` (ISO-8601) |
| `camayoc_ex_orphaned_entities` | labelled nodes with no link in or out | none |
| `camayoc_ex_symbols_in_module` | the code symbols a module defines | `module` (IRI) |
| `camayoc_ex_active_directives` | directives nothing has superseded | none |
| `camayoc_ex_directives_about` | every directive about a subject, and what superseded each | `subject` (IRI) |

Staleness and readiness are computed when you ask, from dates and edges
written when the facts were true. Nothing here stores a judgment such as
"stale" or "ready"; that is the repo-wide rule, and these queries follow it.

## Setups

`setups.json` is the machine-readable form of this table. Paths are relative to
the repository root.

| Setup | Ontology to knot | Shapes to load | Queries to install |
|---|---|---|---|
| **work ledger** | `ontology/core.ttl` | `shapes/core.shapes.ttl` | ready work, blocked-by chain, my plate, recently changed, who said this, stale facts, orphaned entities |
| **code graph** | none | `shapes/code-entities.ttl` | symbols in module, orphaned entities |
| **directive / policy graph** | `ontology/core.ttl` | `shapes/core.shapes.ttl`, `examples/shapes/directives.shapes.ttl` | active directives, directives about, who said this, stale facts, orphaned entities |

Load the shapes before anything else. On the receiving side of a qpack the
order matters more: a receiver that has not loaded shapes sanctioning a class
quarantines the pack, and a pack whose queries target a class the receiver
does not sanction is quarantined for that reason alone.

```bash
quipu shapes load camayoc-core shapes/core.shapes.ttl --db ledger.db
quipu knot ontology/core.ttl --db ledger.db
# then, against a quipu-server on ledger.db, POST each definition to /queries:
curl -s localhost:3030/queries -H 'Content-Type: application/json' \
  -d @examples/queries/camayoc_ex_ready_work.json
curl -s localhost:3030/ask -H 'Content-Type: application/json' \
  -d '{"name": "camayoc_ex_ready_work"}'
```

`examples/shapes/directives.shapes.ttl` is the one shape set this library adds.
camayoc's core shapes govern work items and decisions but not directives, and a
directive class that no loaded shape targets cannot travel in a qpack without
quarantining it. The shape mints no terms.

## Shipping the library in a qpack

```bash
quipu share --output my-pack --queries camayoc_ex_ready_work \
  --queries camayoc_ex_my_plate --db ledger.db
quipu import my-pack --query-namespace ledger --db receiver.db
quipu import promote <share-id> --db receiver.db
# the receiver now answers "ledger/camayoc_ex_ready_work"
```

Without `--queries`, a share carries every stored query registered against
the shared graph. On import, queries land as `<namespace>/<name>`, never over
a local query of the same name. A differing definition already at that name is
reported as a collision and left in place unless the import says
`--replace-queries`. See quipu's sharing reference for the full contract.

## Proof

- `tests/test_examples.py` runs every case in `cases.json` against
  `fixtures/examples.ttl` with rdflib and requires the exact rows named there,
  in order. Every case names a strict subset of its query's candidates, so a
  query that returned everything would fail.
- `scripts/examples_qpack.py` (`just examples-qpack`) is the dogfood. It loads
  the setups into a producer store, registers the library, and shares it with
  `quipu share --queries`. It then imports the share into a fresh store under a
  pack namespace, promotes it, and asks every case again. It passes only if
  the receiver's answers equal the producer's and the expected rows.
  **Dependency:** it needs a quipu whose `share` writes `queries.ttl`
  (quipu aegis-fxpbys.2, scbrown/quipu#351). An older quipu exits 3 and the
  test skips by name.
