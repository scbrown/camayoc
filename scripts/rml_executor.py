#!/usr/bin/env python3
"""Compile and deterministically materialize Camayoc's governed RML subset."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, RDF, URIRef

RML = Namespace("http://semweb.mmlab.be/ns/rml#")
RR = Namespace("http://www.w3.org/ns/r2rml#")
QL = Namespace("http://semweb.mmlab.be/ns/ql#")
CONSTRUCTORS = (RR.constant, RML.reference, RR.template)
FORBIDDEN = (RR.parentTriplesMap, RR.joinCondition, RML.functionExecution, RML.logicalTarget)
TEMPLATE_REF = re.compile(r"\{([^{}]+)\}")


class RmlExecutionError(ValueError):
    """The mapping or source cannot satisfy the governed subset."""


@dataclass(frozen=True)
class TermMap:
    constructor: str
    value: object
    term_type: URIRef | None
    datatype: URIRef | None = None
    language: str | None = None


@dataclass(frozen=True)
class PredicateObject:
    predicate: URIRef
    object_map: TermMap


@dataclass(frozen=True)
class Plan:
    mapping_iri: URIRef
    source_iri: URIRef
    formulation: URIRef
    iterator: str | None
    query: str | None
    target_graph: URIRef
    subject_map: TermMap
    classes: tuple[URIRef, ...]
    predicate_objects: tuple[PredicateObject, ...]
    mapping_hash: str


def _one(graph: Graph, subject, predicate, required=True):
    values = list(graph.objects(subject, predicate))
    if len(values) != 1 if required else len(values) > 1:
        raise RmlExecutionError(f"invalid_term_map: {predicate} count={len(values)}")
    return values[0] if values else None


def _term_map(graph: Graph, node) -> TermMap:
    present = [(predicate, _one(graph, node, predicate, False)) for predicate in CONSTRUCTORS]
    present = [(predicate, value) for predicate, value in present if value is not None]
    if len(present) != 1:
        raise RmlExecutionError("invalid_term_map: exactly one constructor is required")
    predicate, value = present[0]
    kind = {RR.constant: "constant", RML.reference: "reference", RR.template: "template"}[predicate]
    return TermMap(
        kind, value, _one(graph, node, RR.termType, False),
        _one(graph, node, RR.datatype, False),
        str(_one(graph, node, RR.language, False)) if _one(graph, node, RR.language, False) else None,
    )


def compile_mapping(path: Path, mapping_iri: str) -> Plan:
    """Parse and preflight the complete supported mapping before source access."""
    graph = Graph().parse(path, format="turtle")
    mapping = URIRef(mapping_iri)
    if (mapping, RDF.type, RR.TriplesMap) not in graph:
        raise RmlExecutionError("mapping_not_found")
    for predicate in FORBIDDEN:
        if any(graph.triples((None, predicate, None))):
            raise RmlExecutionError(f"unsupported_term: {predicate}")
    logical = _one(graph, mapping, RML.logicalSource)
    subject_node = _one(graph, mapping, RR.subjectMap)
    target = _one(graph, mapping, RR.graph)
    source = _one(graph, logical, RML.source)
    formulation = _one(graph, logical, RML.referenceFormulation)
    if formulation not in (QL.CSV, QL.JSONPath, RR.SQL2008):
        raise RmlExecutionError(f"unsupported_term: {formulation}")
    iterator = _one(graph, logical, RML.iterator, False)
    query = _one(graph, logical, RML.query, False)
    subject_map = _term_map(graph, subject_node)
    predicate_objects = []
    for pom in graph.objects(mapping, RR.predicateObjectMap):
        predicate = _one(graph, pom, RR.predicate)
        object_node = _one(graph, pom, RR.objectMap)
        if not isinstance(predicate, URIRef):
            raise RmlExecutionError("unsupported_term: dynamic predicate")
        predicate_objects.append(PredicateObject(predicate, _term_map(graph, object_node)))
    canonical = graph.serialize(format="nt").encode()
    return Plan(
        mapping, source, formulation, str(iterator) if iterator else None,
        str(query) if query else None, target, subject_map,
        tuple(sorted(graph.objects(subject_node, RR["class"]), key=str)),
        tuple(sorted(predicate_objects, key=lambda item: str(item.predicate))),
        "sha256:" + hashlib.sha256(b"".join(sorted(canonical.splitlines(True)))).hexdigest(),
    )


def _value(term_map: TermMap, record: dict):
    if term_map.constructor == "constant":
        return term_map.value
    if term_map.constructor == "reference":
        key = str(term_map.value)
        if key not in record:
            raise RmlExecutionError(f"materialization_error: missing reference {key}")
        raw = record[key]
    else:
        template = str(term_map.value)
        def replace(match):
            key = match.group(1)
            if key not in record:
                raise RmlExecutionError(f"materialization_error: missing reference {key}")
            return quote(str(record[key]), safe="-._~")
        raw = TEMPLATE_REF.sub(replace, template)
    if term_map.term_type == RR.IRI or term_map.constructor == "template":
        return URIRef(str(raw))
    return Literal(raw, datatype=term_map.datatype, lang=term_map.language)


def materialize(plan: Plan, records: Sequence[dict]) -> str:
    """Return sorted, duplicate-free canonical N-Quads for source-order records."""
    quads = set()
    for record in records:
        subject = _value(plan.subject_map, record)
        if not isinstance(subject, URIRef):
            raise RmlExecutionError("materialization_error: subject must be an IRI")
        for class_iri in plan.classes:
            quads.add(f"{subject.n3()} {RDF.type.n3()} {class_iri.n3()} {plan.target_graph.n3()} .\n")
        for item in plan.predicate_objects:
            obj = _value(item.object_map, record)
            quads.add(f"{subject.n3()} {item.predicate.n3()} {obj.n3()} {plan.target_graph.n3()} .\n")
    return "".join(sorted(quads))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("validate", "execute"))
    result.add_argument("triples_map_iri")
    result.add_argument("--mapping-file", type=Path, required=True)
    result.add_argument("--source-file", type=Path)
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        plan = compile_mapping(args.mapping_file, args.triples_map_iri)
        output = {"phase": "validated", "mapping": str(plan.mapping_iri), "mapping_hash": plan.mapping_hash}
        if args.command == "execute":
            if not args.source_file:
                raise RmlExecutionError("source_policy_refused: --source-file is required")
            records = json.loads(args.source_file.read_text())
            output.update(phase="materialized", nquads=materialize(plan, records))
    except (OSError, json.JSONDecodeError, RmlExecutionError) as exc:
        print(json.dumps({"phase": "refused", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
