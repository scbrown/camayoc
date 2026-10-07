"""Stored queries read a record shape in either namespace (aegis-9dpcta).

The Quechua rename moves vocabulary, never instance IRIs, and a writer switches
one RECORD SHAPE at a time: a class plus every property it writes for that
class that has a published Quechua twin. Properties without a twin (closedAt,
assignedTo, trajectoryOf, ...) stay legacy in both shapes. So a reader of a
record shape needs exactly two branches, an all-legacy one and an all-Quechua
one, joined by UNION and never joined ACROSS (the served quipu is 15-25x
slower on a join across a UNION boundary; measured on aegis-9dpcta).

Each query here is run against its own existing fixture in five arms:

  legacy      the fixture as written: the positive control, never empty;
  quechua     every record of the shape rewritten: the same answer, so a
              Quechua-typed record is a POSITIVE CONTROL, not an empty match;
  mixed       half the records rewritten: the same answer;
  double      every record carrying both spellings: the same answer, because
              DISTINCT keeps a double-typed record from counting twice;
  mutant      the Quechua branch renamed back to legacy must FAIL the quechua
              arm, so the test can tell a dual-read query from a legacy one.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from rdflib_guard import HAVE_RDFLIB, requires_rdflib

if HAVE_RDFLIB:
    import rdflib
    from rdflib import RDF, URIRef

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "queries"
FIXTURES = ROOT / "tests" / "fixtures"
A = "http://aegis.gastown.local/ontology/"
Q = "https://scbrown.github.io/quechua/ns#"
EX = "http://camayoc.test/fixture/"

# Terms each record shape writes that have a published Quechua twin.
SHAPES = {
    "WorkItem": {
        "sourceKind", "outcome", "blockedOn", "inWorkflowRun", "touchesRepo",
        "touchesHost", "touchesService", "grantsAction", "scopeProvenance",
    },
    "Blocker": {
        "sourceKind", "blockerEvidence", "demonstratedBy", "blockerKind",
        "resolutionQuery", "resolvesOn", "prRef", "tool", "minVersion", "repoRef",
    },
}

# query, fixture, the record shape it reads, params
CASES = (
    ("camayoc_blocked_on_closed_dependency", "verification-liveness.ttl", "WorkItem", {}),
    ("camayoc_work_per_token", "verification-liveness.ttl", "WorkItem",
     {"principal": f"{EX}principal-strider"}),
    ("camayoc_blockers_by_evidence_kind", "verification-liveness.ttl", "Blocker", {}),
    ("camayoc_gp_admissible_exemplars", "golden-paths.ttl", "WorkItem", {}),
)


def template(name: str, params: dict) -> str:
    text = json.loads((QUERIES / f"{name}.json").read_text())["template"]
    for key, value in params.items():
        text = text.replace("{" + key + "}", value)
    return text


def rows(graph, query: str) -> list[tuple]:
    return sorted(tuple("" if v is None else str(v) for v in row) for row in graph.query(query))


def rewrite(graph, shape: str, keep_legacy: bool, which) -> "rdflib.Graph":
    """Move the chosen records of `shape` into Quechua, record by record."""
    twins = SHAPES[shape]
    records = sorted(graph.subjects(RDF.type, URIRef(A + shape)), key=str)
    chosen = {r for i, r in enumerate(records) if which(i)}
    out = rdflib.Graph()
    for s, p, o in graph:
        moved = []
        if s in chosen and p == RDF.type and o == URIRef(A + shape):
            moved = [(s, p, URIRef(Q + shape))]
        elif s in chosen and str(p).startswith(A) and str(p)[len(A):] in twins:
            moved = [(s, URIRef(Q + str(p)[len(A):]), o)]
        if not moved or keep_legacy:
            out.add((s, p, o))
        for triple in moved:
            out.add(triple)
    return out


@requires_rdflib
class DualReadQueryTests(unittest.TestCase):
    def test_every_arm_returns_the_legacy_answer(self):
        for name, fixture, shape, params in CASES:
            with self.subTest(query=name):
                legacy = rdflib.Graph().parse(FIXTURES / fixture)
                query = template(name, params)
                expected = rows(legacy, query)
                self.assertTrue(expected, f"{name}: the legacy control returned nothing")
                arms = {
                    "quechua": rewrite(legacy, shape, False, lambda i: True),
                    "mixed": rewrite(legacy, shape, False, lambda i: i % 2 == 0),
                    "double": rewrite(legacy, shape, True, lambda i: True),
                }
                for arm, graph in arms.items():
                    self.assertNotEqual(
                        set(legacy), set(graph), f"{name}/{arm}: the rewrite moved nothing"
                    )
                    self.assertEqual(expected, rows(graph, query), f"{name}/{arm}")

    def test_a_legacy_only_mutant_fails_the_quechua_arm(self):
        for name, fixture, shape, params in CASES:
            with self.subTest(query=name):
                legacy = rdflib.Graph().parse(FIXTURES / fixture)
                quechua = rewrite(legacy, shape, False, lambda i: True)
                query = template(name, params)
                # Rename in the BODY only. Renaming the prologue too would turn
                # `PREFIX quechua: <...>` into a second `PREFIX aegis:` bound to
                # the Quechua namespace, silently moving EVERY term: a mutant
                # that passes or fails for the wrong reason.
                head, body = query.split("SELECT", 1)
                mutant = head + "SELECT" + body.replace("quechua:", "aegis:")
                self.assertNotEqual(query, mutant)
                self.assertNotEqual(rows(quechua, query), rows(quechua, mutant), name)

    def test_branches_differ_only_by_the_shapes_twin_terms(self):
        """The Quechua branch is the legacy branch with this shape's twins
        renamed, nothing else: a term without a twin must stay legacy."""
        for name, _fixture, shape, _params in CASES:
            with self.subTest(query=name):
                legacy_branch, quechua_branch = union_branches(template(name, {}))
                renamed = legacy_branch
                for term in sorted(SHAPES[shape] | {shape}):
                    renamed = re.sub(rf"\baegis:{term}\b", f"quechua:{term}", renamed)
                self.assertEqual(renamed, quechua_branch, name)
                self.assertNotEqual(legacy_branch, quechua_branch, name)


def union_branches(query: str) -> tuple[str, str]:
    """The two groups around the query's first top-level `} UNION {`."""
    mid = query.index("} UNION {")
    depth, start = 0, mid
    while True:
        start -= 1
        if query[start] == "}":
            depth += 1
        elif query[start] == "{":
            if depth == 0:
                break
            depth -= 1
    depth, end = 0, mid + len("} UNION {")
    while True:
        if query[end] == "{":
            depth += 1
        elif query[end] == "}":
            if depth == 0:
                break
            depth -= 1
        end += 1
    return query[start + 1 : mid].strip(), query[mid + len("} UNION {") : end].strip()

# seeds' schema.org model (aegis-bqgdr3): a WorkItem is a schema:Action. The
# governance twins stay quechua; three seed predicates move to schema.org;
# camayoc-only terms (trajectoryOf, stepOf, ...) stay legacy. rdfs:label stays
# (seeds writes it beside schema:name for quipu's label floor).
S = "https://schema.org/"
SCHEMA_MOVES = {"closedAt": "endTime", "assignedTo": "agent", "identifier": "identifier"}
SCHEMA_CASES = tuple(c for c in CASES if c[2] == "WorkItem")


def to_schema(graph, which) -> "rdflib.Graph":
    """Move the chosen WorkItems into seeds' schema.org model, record by record."""
    records = sorted(graph.subjects(RDF.type, URIRef(A + "WorkItem")), key=str)
    chosen = {r for i, r in enumerate(records) if which(i)}
    out = rdflib.Graph()
    for s, p, o in graph:
        local = str(p)[len(A):] if str(p).startswith(A) else None
        if s not in chosen:
            out.add((s, p, o))
        elif p == RDF.type and o == URIRef(A + "WorkItem"):
            out.add((s, p, URIRef(S + "Action")))
        elif local in SCHEMA_MOVES:
            out.add((s, URIRef(S + SCHEMA_MOVES[local]), o))
        elif local in SHAPES["WorkItem"]:
            out.add((s, URIRef(Q + local), o))
        else:
            out.add((s, p, o))
    return out


def _rekey(term):
    return URIRef(str(term) + "-sd") if isinstance(term, URIRef) and str(term).startswith(EX) else term


def rekey(graph) -> "rdflib.Graph":
    """The same records on a second board: every fixture IRI gets a suffix."""
    out = rdflib.Graph()
    for s, p, o in graph:
        out.add((_rekey(s), p, _rekey(o)))
    return out


@requires_rdflib
class SchemaActionBranchTests(unittest.TestCase):
    def test_schema_and_mixed_arms_return_the_legacy_answer(self):
        for name, fixture, _shape, params in SCHEMA_CASES:
            with self.subTest(query=name):
                legacy = rdflib.Graph().parse(FIXTURES / fixture)
                query = template(name, params)
                expected = rows(legacy, query)
                self.assertTrue(expected, f"{name}: the legacy control returned nothing")
                schema = to_schema(legacy, lambda i: True)
                self.assertNotEqual(set(legacy), set(schema), f"{name}: moved nothing")
                self.assertEqual(expected, rows(schema, query), f"{name}/schema")
                # Two whole boards side by side, one per model: seeds cuts a
                # board over at once and a dependency never crosses models, so
                # this (not record-by-record mixing) is the mixed state.
                # The reference is two LEGACY boards, so aggregates work too.
                reference = rows(legacy + rekey(legacy), query)
                self.assertNotEqual(reference, [], name)
                self.assertEqual(reference, rows(legacy + rekey(schema), query),
                                 f"{name}/legacy-board+schema-board")

    def test_without_the_schema_branch_the_schema_arm_fails(self):
        for name, fixture, _shape, params in SCHEMA_CASES:
            with self.subTest(query=name):
                schema = to_schema(rdflib.Graph().parse(FIXTURES / fixture), lambda i: True)
                query = template(name, params)
                mutant = query.replace("schema:Action", "schema:NotAnAction")
                self.assertNotEqual(query, mutant)
                self.assertNotEqual(rows(schema, query), rows(schema, mutant), name)

    def test_schema_branch_is_the_quechua_branch_with_only_mapped_terms_moved(self):
        for name, _fixture, _shape, _params in SCHEMA_CASES:
            with self.subTest(query=name):
                q = template(name, {})
                _, quechua_branch = union_branches(q)
                second = q.index(quechua_branch) + len(quechua_branch)
                _, schema_branch = union_branches(q[second - len(quechua_branch) - 3:])
                expected = quechua_branch.replace("quechua:WorkItem", "schema:Action")
                for old, new in SCHEMA_MOVES.items():
                    expected = re.sub(rf"\baegis:{old}\b", f"schema:{new}", expected)
                self.assertEqual(expected, schema_branch, name)


if __name__ == "__main__":
    unittest.main()
