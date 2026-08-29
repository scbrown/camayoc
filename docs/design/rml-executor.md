# Design: governed RML-subset execution

> **Implementation status (2026-08-29):** 🟨 **Parser and deterministic JSON
> materializer built; bounded CSV/SQLite and governed write remain.** Quipu
> currently governs four external-truth pointers, but
> they are source-discovery records rather than executable RML triples maps.
> The standard RML/R2RML classes are loaded through Quipu governance. Camayoc
> MUST NOT claim complete execution until the remaining adapters, governed
> write, and end-to-end fixture below all pass.

Camayoc owns transformation from structured external truth into candidate RDF.
Quipu owns mapping storage, governance, and graph writes. The executor is a
bounded, deterministic implementation of RML 1.1.2 concepts and the W3C R2RML
term-map model; it is not a new mapping language and does not claim full RML
conformance.

## 1. Two contracts, deliberately separate

The four properties delivered by `aegis-jsyl2` describe how to locate and
verify external truth:

- `aegis:source_uri`
- `aegis:access_via`
- `aegis:freshness`
- `aegis:verified_by`

They do not say how source records become RDF terms. An executable mapping is
an `rr:TriplesMap` with an `rml:logicalSource`, one subject map, and zero or
more predicate-object maps. The triples map or its logical source links to the
governed external-truth subject; it never copies credentials into mapping RDF.

The executor MUST reject either half in isolation:

- an RML triples map without one complete external-truth pointer cannot fetch;
- an external-truth pointer without a triples map is discoverable but not
  executable.

The four live jsyl2 records are compatibility fixtures for pointer resolution,
not evidence that four executable mappings already exist.

## 2. Governance prerequisite

Before executable mappings are written to Quipu, its loaded vocabulary MUST
admit and constrain the standard classes used by this subset:

- `rr:TriplesMap`, `rr:SubjectMap`, `rr:PredicateObjectMap`, `rr:ObjectMap`;
- `rml:LogicalSource`;
- the term-map and logical-source properties listed below.

The persistent source belongs in a loaded Camayoc shape set. A pending
`/propose` record alone is not sufficient. Until the loaded `/shapes`
`vocabulary` response exposes those classes, Camayoc may parse mapping fixtures
from files for tests but MUST refuse a production `execute` request.

The shapes enforce the subset structurally: exactly one logical source and
subject map per triples map, exactly one source and reference formulation per
logical source, and exactly one of constant/reference/template on every term
map. Unsupported standard terms are rejected by Camayoc's semantic validator
before any source access.

## 3. Version-one vocabulary

Camayoc reads the established namespaces directly:

```text
rml:  http://semweb.mmlab.be/ns/rml#
rr:   http://www.w3.org/ns/r2rml#
ql:   http://semweb.mmlab.be/ns/ql#
```

Supported logical-source terms:

| Term | Version-one meaning |
|---|---|
| `rml:logicalSource` | Exactly one logical source per triples map. |
| `rml:source` | IRI of the governed external-truth subject, not a secret-bearing connection string. |
| `rml:referenceFormulation` | Exactly one of `ql:CSV`, `ql:JSONPath`, or `rr:SQL2008`. |
| `rml:iterator` | CSV row (omitted or `row`), bounded JSONPath, or absent for SQL. |
| `rml:query` | One read-only, parameterized SQLite `SELECT`; no stacked statements or mutation. |

Supported term-map terms:

| Term | Constraint |
|---|---|
| `rr:constant` | IRI or literal copied exactly. |
| `rml:reference` | CSV column, JSONPath relative to the current record, or SQL result-column name. |
| `rr:template` | Text with `{reference}` substitutions; every reference must resolve. |
| `rr:termType` | `rr:IRI` or `rr:Literal`; blank nodes are excluded. |
| `rr:datatype` | Constant datatype IRI on literal object maps. |
| `rr:language` | Constant BCP 47 language tag on literal object maps. |
| `rr:class` | Emits `rdf:type` for the generated subject. |
| `rr:predicateObjectMap` | Constant predicate plus one supported object map. |
| `rr:graph` | One explicit target named graph for the triples map. |

Version one excludes referencing object maps, joins, multiple logical sources,
custom functions, inverse expressions, dynamic predicates or graphs, XML,
remote SQL servers, SPARQL federation, streaming inputs, and RML logical
targets. Encountering any excluded term is a validation error, never a warning.

## 4. Execution state machine

One invocation progresses through five observable phases:

```text
resolve mapping -> validate plan -> open bounded source -> materialize -> commit
```

1. **Resolve mapping.** Fetch the triples map and its bounded RDF closure from
   Quipu. Resolve the referenced external-truth subject and require all four
   jsyl2 properties. Ambiguous or missing values refuse.
2. **Validate plan.** Parse the whole mapping, reject unknown/unsupported terms,
   validate the base IRI and target graph, and compile every iterator,
   reference, template, and SQL statement. This phase performs no source I/O.
3. **Open bounded source.** Dispatch by both `access_via` and reference
   formulation. Apply byte, row, time, redirect, and response limits before
   parsing. Credentials come from a named local resolver; mapping RDF never
   carries credential values.
4. **Materialize.** Iterate records in source order, generate RDF terms, sort
   the resulting quads lexically by N-Quads representation, and deduplicate
   exact duplicates. Missing required references fail the invocation; they do
   not silently omit a triple.
5. **Commit.** Serialize one deterministic episode body whose source names the
   mapping IRI and verified external-truth identity. Submit once through
   Camayoc's existing plane-routing/write lane. On timeout or gateway error,
   preserve the exact body and follow Quipu's indeterminate-write verification
   protocol; any retry is byte-identical.

`validate` runs phases 1-2. `plan` runs phases 1-3 and reports bounded source
metadata without emitting values. `execute --dry-run` runs phases 1-4 and
writes canonical N-Quads plus the episode body to stdout. Only `execute`
enters phase 5.

## 5. Source adapters and safety

The executor selects an adapter from the pair `(access_via,
referenceFormulation)`, not from a filename suffix.

| Source | Required pair | Boundary |
|---|---|---|
| CSV | `file` or `rest` + `ql:CSV` | Header required; duplicate headers refuse; RFC 4180 parsing; bounded rows/bytes. |
| JSON | `file` or `rest` + `ql:JSONPath` | UTF-8 JSON; bounded JSONPath subset rooted at `$`; no script/filter evaluation. |
| SQLite | `file` + `rr:SQL2008` | Read-only URI, one `SELECT`, bound parameters only, progress-handler deadline. |

Version one does not execute the live `promql` pointer. It remains a pointer
resolution fixture until a result-table adapter is specified. Likewise, an
HTTP response such as Garage's expected 403 auth boundary verifies a pointer
but is not mapping input.

Remote fetches refuse private or loopback destinations unless the mapping
policy explicitly names an approved resolver. Redirects are re-checked at
every hop. File sources must resolve beneath configured allowlisted roots.
SQLite opens immutable/read-only and cannot attach another database. Logs may
contain mapping IRIs, counts, hashes, and error classes; they never contain
authorization headers, source rows, or generated literal values.

## 6. Determinism and identity

For identical mapping closure, source bytes, base IRI, and executor version:

- generated RDF terms and canonical N-Quads are byte-identical;
- the episode name, source, node order, edge order, and description strings are
  byte-identical;
- rerunning produces Quipu's idempotent `unchanged` outcome or an equivalent
  no-op after read-back;
- provenance names the triples-map IRI, mapping-closure hash, external-truth
  subject IRI, verified source identity, and executor version.

Templates percent-encode substituted values when producing IRIs. Relative
IRIs require one explicit base IRI. Locale, wall-clock time, filesystem order,
hash-map order, and network response ordering cannot affect output. A mapping
that needs "now" must receive it as declared source data; the executor never
invents it.

## 7. Public interface

The first CLI surface is intentionally narrow:

```text
scripts/rml_executor.py validate <triples-map-iri> [--mapping-file FILE]
scripts/rml_executor.py plan <triples-map-iri> [--mapping-file FILE]
scripts/rml_executor.py execute <triples-map-iri> [--mapping-file FILE] [--dry-run]
```

Production mode resolves mapping RDF from Quipu. `--mapping-file` exists for
conformance tests and bootstrap before the RML shapes are loaded; non-dry-run
execution with it is refused. JSON output includes phase, mapping IRI, source
identity, mapping/source hashes, input/output counts, target graph, and a
machine-stable error code.

Error families are `mapping_not_found`, `mapping_ambiguous`,
`mapping_ungoverned`, `unsupported_term`, `invalid_term_map`,
`source_policy_refused`, `source_unreachable`, `source_changed`,
`materialization_error`, `write_indeterminate`, and `write_refused`.

## 8. Conformance fixtures

The first end-to-end fixture is a bounded JSONL export of bead records. It is
checked into `tests/fixtures/rml/` with:

- one RML Turtle mapping;
- source bytes and SHA-256;
- expected sorted N-Quads;
- expected deterministic episode JSON;
- one malformed mapping per refusal arm.

The acceptance test executes the valid mapping twice and requires byte-equal
N-Quads and episode JSON, one logical set of output facts, and provenance that
names the triples-map IRI. Negative tests cover incomplete jsyl2 pointers,
multiple term-map constructors, missing references, traversal outside an
allowlisted root, non-SELECT SQL, unsupported joins, unknown formulations, and
a failure before the mocked write endpoint receives any request.

Two later fixtures exercise CSV and SQLite. The four live jsyl2 pointer records
remain read-only integration controls: all resolve as complete pointers; only
sources whose adapter pair is supported may advance beyond source planning.

## 9. Implementation sequence

1. Land and load the Camayoc RML subset shapes; verify the server vocabulary
   and one accepted plus one refused mapping write.
2. Add pure mapping-RDF parser and semantic validator.
3. Add term generation and canonical quad emission with fixture tests.
4. Add bounded JSON, CSV, and SQLite adapters.
5. Add Quipu mapping retrieval and existing Camayoc plane/write integration.
6. Run the bead-store fixture twice against a disposable Quipu store, then one
   governed mapping end to end against the live interface.

Pack production is downstream of successful materialization: mappings and
their shapes may be carried in the same certified `.qpack.db`, but packaging
does not weaken or bypass this executor's validation and source-policy gates.

## References

- [RML 1.1.2 draft](https://rml.io/specs/rml/v/1.1.2/)
- [W3C R2RML Recommendation](https://www.w3.org/TR/r2rml/)
- [R2RML vocabulary](https://www.w3.org/ns/r2rml)
