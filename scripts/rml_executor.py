#!/usr/bin/env python3
"""Compile and deterministically materialize Camayoc's governed RML subset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib import error, request
from urllib.parse import quote

from rdflib import Dataset, Graph, Literal, Namespace, RDF, URIRef

RML = Namespace("http://semweb.mmlab.be/ns/rml#")
RR = Namespace("http://www.w3.org/ns/r2rml#")
QL = Namespace("http://semweb.mmlab.be/ns/ql#")
AEGIS = Namespace("http://aegis.gastown.local/ontology/")
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
    source_uri: str
    access_via: str
    freshness: str
    verified_by: str
    formulation: URIRef
    iterator: str | None
    query: str | None
    target_graph: URIRef
    subject_map: TermMap
    classes: tuple[URIRef, ...]
    predicate_objects: tuple[PredicateObject, ...]
    mapping_hash: str


@dataclass(frozen=True)
class SourceResult:
    records: tuple[dict, ...]
    source_hash: str
    byte_count: int


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
    language = _one(graph, node, RR.language, False)
    return TermMap(
        kind, value, _one(graph, node, RR.termType, False),
        _one(graph, node, RR.datatype, False),
        str(language) if language else None,
    )


def compile_mapping_data(data: str, mapping_iri: str) -> Plan:
    """Parse and preflight a complete mapping closure before source access."""
    graph = Graph().parse(data=data, format="turtle")
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
    source_uri = _one(graph, source, AEGIS.source_uri)
    access_via = _one(graph, source, AEGIS.access_via)
    freshness = _one(graph, source, AEGIS.freshness)
    verified_by = _one(graph, source, AEGIS.verified_by)
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
        mapping, source, str(source_uri), str(access_via), str(freshness), str(verified_by),
        formulation, str(iterator) if iterator else None,
        str(query) if query else None, target, subject_map,
        tuple(sorted(graph.objects(subject_node, RR["class"]), key=str)),
        tuple(sorted(predicate_objects, key=lambda item: str(item.predicate))),
        "sha256:" + hashlib.sha256(b"".join(sorted(canonical.splitlines(True)))).hexdigest(),
    )


def compile_mapping(path: Path, mapping_iri: str) -> Plan:
    return compile_mapping_data(path.read_text(), mapping_iri)


def fetch_mapping(server: str, mapping_iri: str, opener=request.urlopen) -> str:
    """Fetch the lossless bounded mapping and external-pointer closure through `/export`."""
    if any(char in mapping_iri for char in '<>"{}|') or ":" not in mapping_iri:
        raise RmlExecutionError("mapping_not_found: invalid mapping IRI")
    query = f"""PREFIX rml: <{RML}> PREFIX rr: <{RR}>
CONSTRUCT {{ ?s ?p ?o }} WHERE {{
  {{ VALUES ?s {{ <{mapping_iri}> }} }} UNION
  {{ <{mapping_iri}> (rml:logicalSource|rr:subjectMap|rr:predicateObjectMap) ?s }} UNION
  {{ <{mapping_iri}> rr:predicateObjectMap/rr:objectMap ?s }} UNION
  {{ <{mapping_iri}> rml:logicalSource/rml:source ?s }}
  ?s ?p ?o
}}"""
    body = json.dumps({"construct": query, "format": "turtle"}, sort_keys=True).encode()
    req = request.Request(
        server.rstrip("/") + "/export", data=body,
        headers={"Content-Type": "application/json", "X-Quipu-Client": "agent-adhoc"},
        method="POST",
    )
    try:
        with opener(req, timeout=30) as response:
            turtle = response.read().decode("utf-8")
    except (error.URLError, TimeoutError, UnicodeDecodeError) as exc:
        raise RmlExecutionError(f"mapping_not_found: {exc}") from exc
    if not turtle.strip():
        raise RmlExecutionError("mapping_not_found: empty closure")
    return turtle


def _bounded_path(path: Path, allowed_root: Path) -> Path:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved != root and root not in resolved.parents:
        raise RmlExecutionError("source_policy_refused: path escapes allowed root")
    if not resolved.is_file():
        raise RmlExecutionError("source_unreachable: source is not a regular file")
    return resolved


def _bounded_bytes(path: Path, allowed_root: Path, max_bytes: int) -> bytes:
    resolved = _bounded_path(path, allowed_root)
    size = resolved.stat().st_size
    if size > max_bytes:
        raise RmlExecutionError(f"source_policy_refused: {size} bytes exceeds {max_bytes}")
    return resolved.read_bytes()


def _validate_sql(query: str | None) -> str:
    if not query:
        raise RmlExecutionError("source_policy_refused: SQL mapping requires rml:query")
    stripped = query.strip()
    if not re.fullmatch(r"(?is)SELECT\b.*;?", stripped) or ";" in stripped.rstrip(";"):
        raise RmlExecutionError("source_policy_refused: exactly one SELECT is required")
    forbidden = re.search(
        r"(?i)\b(?:ATTACH|DETACH|INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|PRAGMA|VACUUM)\b",
        stripped,
    )
    if forbidden:
        raise RmlExecutionError(f"source_policy_refused: forbidden SQL token {forbidden.group(0)}")
    return stripped.rstrip(";")


def load_source(
    plan: Plan,
    source_path: Path,
    allowed_root: Path,
    *,
    max_bytes: int = 1_000_000,
    max_rows: int = 10_000,
) -> SourceResult:
    """Open one bounded source only after the complete mapping plan exists."""
    if plan.access_via != "file":
        raise RmlExecutionError(f"source_policy_refused: access_via={plan.access_via}")
    if plan.formulation == QL.JSONPath:
        if plan.iterator not in (None, "$[*]"):
            raise RmlExecutionError("unsupported_term: JSON iterator must be $[*]")
        payload = _bounded_bytes(source_path, allowed_root, max_bytes)
        try:
            records = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RmlExecutionError(f"materialization_error: invalid JSON: {exc}") from exc
        if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
            raise RmlExecutionError("materialization_error: JSON source must be an array of objects")
    elif plan.formulation == QL.CSV:
        if plan.iterator not in (None, "row"):
            raise RmlExecutionError("unsupported_term: CSV iterator must be row or omitted")
        payload = _bounded_bytes(source_path, allowed_root, max_bytes)
        try:
            text = payload.decode("utf-8")
            rows = list(csv.reader(text.splitlines()))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise RmlExecutionError(f"materialization_error: invalid CSV: {exc}") from exc
        if not rows or not rows[0] or len(rows[0]) != len(set(rows[0])):
            raise RmlExecutionError("materialization_error: CSV header missing or duplicated")
        if any(len(row) != len(rows[0]) for row in rows[1:]):
            raise RmlExecutionError("materialization_error: CSV row width differs from header")
        records = [dict(zip(rows[0], row)) for row in rows[1:]]
    elif plan.formulation == RR.SQL2008:
        query = _validate_sql(plan.query)
        resolved = _bounded_path(source_path, allowed_root)
        if resolved.stat().st_size > max_bytes:
            raise RmlExecutionError("source_policy_refused: SQLite file exceeds byte limit")
        try:
            with sqlite3.connect(f"file:{resolved}?mode=ro&immutable=1", uri=True) as conn:
                conn.set_progress_handler(lambda: 1, 1_000_000)
                cursor = conn.execute(query)
                columns = [item[0] for item in cursor.description or ()]
                if not columns or len(columns) != len(set(columns)):
                    raise RmlExecutionError("materialization_error: SQL columns missing or duplicated")
                records = [dict(zip(columns, row)) for row in cursor.fetchmany(max_rows + 1)]
        except sqlite3.Error as exc:
            raise RmlExecutionError(f"materialization_error: SQLite read failed: {exc}") from exc
        payload = resolved.read_bytes()
    else:
        raise RmlExecutionError(f"unsupported_term: {plan.formulation}")
    if len(records) > max_rows:
        raise RmlExecutionError(f"source_policy_refused: row count exceeds {max_rows}")
    return SourceResult(
        tuple(records), "sha256:" + hashlib.sha256(payload).hexdigest(), len(payload)
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


def nquads_to_turtle(nquads: str) -> str:
    """Strip the already-validated common graph term for a graph-scoped `/knot` write."""
    graph = Graph()
    dataset = Dataset().parse(data=nquads, format="nquads")
    for subject, predicate, obj, _context in dataset.quads((None, None, None, None)):
        graph.add((subject, predicate, obj))
    return graph.serialize(format="turtle")


def governed_write(
    server: str,
    plan: Plan,
    nquads: str,
    actor: str,
    source_hash: str,
    bearer: str | None = None,
    opener=request.urlopen,
) -> dict:
    """Commit deterministic output once with mapping/source provenance."""
    provenance = (
        f"rml:{plan.mapping_iri}|mapping={plan.mapping_hash}|source={plan.source_iri}|"
        f"verified={source_hash}"
    )
    body = json.dumps(
        {
            "turtle": nquads_to_turtle(nquads),
            "graph": str(plan.target_graph),
            "actor": actor,
            "source": provenance,
        },
        sort_keys=True,
    ).encode()
    req = request.Request(
        server.rstrip("/") + "/knot", data=body,
        headers={"Content-Type": "application/json", "X-Quipu-Client": "agent-adhoc"},
        method="POST",
    )
    if bearer:
        req.add_header("Authorization", f"Bearer {bearer}")
    try:
        with opener(req, timeout=30) as response:
            result = json.load(response)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RmlExecutionError(f"write_refused: HTTP {exc.code} {detail}") from exc
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RmlExecutionError(f"write_indeterminate: {exc}") from exc
    if result.get("conforms") is not True or not isinstance(result.get("tx_id"), int):
        raise RmlExecutionError(f"write_refused: {result}")
    return result


def auth_token() -> str | None:
    """Resolve Quipu write auth without placing credentials in mapping data."""
    if os.environ.get("QUIPU_AUTH_TOKEN"):
        return os.environ["QUIPU_AUTH_TOKEN"]
    path = Path.home() / ".config/aegis/quipu_token"
    try:
        return path.read_text().strip() or None
    except OSError:
        return None


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("validate", "execute"))
    result.add_argument("triples_map_iri")
    result.add_argument("--mapping-file", type=Path)
    result.add_argument("--source-file", type=Path)
    result.add_argument("--allowed-root", type=Path)
    result.add_argument("--server")
    result.add_argument("--actor")
    result.add_argument("--dry-run", action="store_true")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.mapping_file:
            plan = compile_mapping(args.mapping_file, args.triples_map_iri)
        elif args.server:
            plan = compile_mapping_data(
                fetch_mapping(args.server, args.triples_map_iri), args.triples_map_iri
            )
        else:
            raise RmlExecutionError("mapping_not_found: --mapping-file or --server is required")
        output = {"phase": "validated", "mapping": str(plan.mapping_iri), "mapping_hash": plan.mapping_hash}
        if args.command == "execute":
            if not args.source_file:
                raise RmlExecutionError("source_policy_refused: --source-file is required")
            source = load_source(plan, args.source_file, args.allowed_root or args.source_file.parent)
            nquads = materialize(plan, source.records)
            output.update(
                phase="materialized", nquads=nquads, source_hash=source.source_hash,
                input_count=len(source.records), output_count=len(nquads.splitlines()),
            )
            if args.server and not args.dry_run:
                if not args.actor:
                    raise RmlExecutionError("source_policy_refused: --actor is required for writes")
                output.update(phase="committed", write=governed_write(
                    args.server, plan, nquads, args.actor, source.source_hash, auth_token()
                ))
    except (OSError, json.JSONDecodeError, RmlExecutionError) as exc:
        print(json.dumps({"phase": "refused", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
