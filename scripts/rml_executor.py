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
# v1 also forbade rr:parentTriplesMap and rr:joinCondition; referencing object
# maps are the v2 addition (camayoc-5bf) because they are the R2RML spelling of
# Spanner Graph's foreign-key-shaped edges. Functions and logical targets stay
# out: they would make output depend on code the mapping closure cannot carry.
FORBIDDEN = (RML.functionExecution, RML.logicalTarget)
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
class ParentSource:
    """A cross-source join's parent logical source, loadable like a plan's own."""

    source_iri: URIRef
    source_uri: str
    access_via: str
    formulation: URIRef
    iterator: str | None
    query: str | None


@dataclass(frozen=True)
class RefObject:
    """A referencing object map: the object is the parent map's subject for the
    row(s) the join conditions select. Joins compare the string form of values,
    so a CSV "1" and a SQLite 1 meet — the deterministic choice, stated rather
    than left to adapter luck."""

    parent_map: URIRef
    parent_subject: TermMap
    source_key: str
    joins: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PredicateObject:
    predicate: URIRef
    object_map: TermMap | RefObject


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
    # Cross-source parents only; a same-source join reads the child's records.
    parent_sources: tuple[tuple[str, ParentSource], ...] = ()


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


def _parent_source(graph: Graph, logical) -> ParentSource:
    source = _one(graph, logical, RML.source)
    formulation = _one(graph, logical, RML.referenceFormulation)
    if formulation not in (QL.CSV, QL.JSONPath, RR.SQL2008):
        raise RmlExecutionError(f"unsupported_term: {formulation}")
    iterator = _one(graph, logical, RML.iterator, False)
    query = _one(graph, logical, RML.query, False)
    return ParentSource(
        source,
        str(_one(graph, source, AEGIS.source_uri)),
        str(_one(graph, source, AEGIS.access_via)),
        formulation,
        str(iterator) if iterator else None,
        str(query) if query else None,
    )


def _ref_object(graph: Graph, node, parent, child_logical, parent_sources: dict) -> RefObject:
    if any(_one(graph, node, predicate, False) is not None for predicate in CONSTRUCTORS):
        raise RmlExecutionError("invalid_term_map: ref object map cannot also carry a constructor")
    if (parent, RDF.type, RR.TriplesMap) not in graph:
        raise RmlExecutionError("invalid_term_map: parentTriplesMap is not a TriplesMap in the closure")
    joins = []
    for join in graph.objects(node, RR.joinCondition):
        joins.append((str(_one(graph, join, RR.child)), str(_one(graph, join, RR.parent))))
    if not joins:
        # No implicit identity join, even same-source: edge semantics must not
        # depend on which logical source two maps happen to share.
        raise RmlExecutionError("invalid_term_map: ref object map requires at least one joinCondition")
    parent_logical = _one(graph, parent, RML.logicalSource)
    parent_subject = _term_map(graph, _one(graph, parent, RR.subjectMap))
    if parent_logical == child_logical:
        source_key = str(child_logical)
    elif isinstance(parent_logical, URIRef):
        source_key = str(parent_logical)
        parent_sources.setdefault(source_key, _parent_source(graph, parent_logical))
    else:
        # A cross-source parent must be addressable so --parent-source-file
        # can name it; a blank-node logical source cannot be.
        raise RmlExecutionError("unsupported_term: cross-source join needs an IRI logical source")
    return RefObject(parent, parent_subject, source_key, tuple(sorted(joins)))


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
    parent_sources: dict[str, ParentSource] = {}
    for pom in graph.objects(mapping, RR.predicateObjectMap):
        predicate = _one(graph, pom, RR.predicate)
        object_node = _one(graph, pom, RR.objectMap)
        if not isinstance(predicate, URIRef):
            raise RmlExecutionError("unsupported_term: dynamic predicate")
        parent = _one(graph, object_node, RR.parentTriplesMap, False)
        if parent is not None:
            object_map = _ref_object(graph, object_node, parent, logical, parent_sources)
        else:
            object_map = _term_map(graph, object_node)
        predicate_objects.append(PredicateObject(predicate, object_map))
    canonical = graph.serialize(format="nt").encode()
    return Plan(
        mapping, source, str(source_uri), str(access_via), str(freshness), str(verified_by),
        formulation, str(iterator) if iterator else None,
        str(query) if query else None, target, subject_map,
        tuple(sorted(graph.objects(subject_node, RR["class"]), key=str)),
        tuple(sorted(predicate_objects, key=lambda item: str(item.predicate))),
        "sha256:" + hashlib.sha256(b"".join(sorted(canonical.splitlines(True)))).hexdigest(),
        tuple(sorted(parent_sources.items())),
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
  {{ <{mapping_iri}> rml:logicalSource/rml:source ?s }} UNION
  {{ <{mapping_iri}> rr:predicateObjectMap/rr:objectMap/rr:joinCondition ?s }} UNION
  {{ <{mapping_iri}> rr:predicateObjectMap/rr:objectMap/rr:parentTriplesMap ?s }} UNION
  {{ <{mapping_iri}> rr:predicateObjectMap/rr:objectMap/rr:parentTriplesMap/(rml:logicalSource|rr:subjectMap) ?s }} UNION
  {{ <{mapping_iri}> rr:predicateObjectMap/rr:objectMap/rr:parentTriplesMap/rml:logicalSource/rml:source ?s }}
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


def _join_key(record: dict, columns: Sequence[str]) -> tuple[str, ...]:
    for column in columns:
        if column not in record:
            raise RmlExecutionError(f"materialization_error: missing join reference {column}")
    return tuple(str(record[column]) for column in columns)


def _parent_indexes(plan: Plan, records, parent_records) -> dict[RefObject, dict]:
    """Hash-join build side: parent join-key tuple -> generated parent subjects."""
    cross_keys = {key for key, _ in plan.parent_sources}
    indexes: dict[RefObject, dict] = {}
    for item in plan.predicate_objects:
        ref = item.object_map
        if not isinstance(ref, RefObject) or ref in indexes:
            continue
        if ref.source_key in cross_keys:
            if ref.source_key not in (parent_records or {}):
                raise RmlExecutionError(
                    f"source_policy_refused: no parent source provided for {ref.source_key}"
                )
            rows = parent_records[ref.source_key]
        else:
            rows = records
        index: dict = {}
        for row in rows:
            subject = _value(ref.parent_subject, row)
            if not isinstance(subject, URIRef):
                raise RmlExecutionError("materialization_error: parent subject must be an IRI")
            index.setdefault(_join_key(row, [parent for _, parent in ref.joins]), set()).add(subject)
        indexes[ref] = index
    return indexes


def materialize_with_stats(
    plan: Plan, records: Sequence[dict], parent_records: dict | None = None
) -> tuple[str, int]:
    """Sorted, duplicate-free canonical N-Quads, plus the unmatched-join count.

    An unmatched join emits no triple (standard R2RML) but is COUNTED so the
    silence is visible in the invocation report — the same stance Spanner takes
    on dangling edges: absent unless a constraint says otherwise, never quiet.
    """
    indexes = _parent_indexes(plan, records, parent_records)
    quads = set()
    unmatched = 0
    for record in records:
        subject = _value(plan.subject_map, record)
        if not isinstance(subject, URIRef):
            raise RmlExecutionError("materialization_error: subject must be an IRI")
        for class_iri in plan.classes:
            quads.add(f"{subject.n3()} {RDF.type.n3()} {class_iri.n3()} {plan.target_graph.n3()} .\n")
        for item in plan.predicate_objects:
            if isinstance(item.object_map, RefObject):
                ref = item.object_map
                parents = indexes[ref].get(_join_key(record, [child for child, _ in ref.joins]))
                if not parents:
                    unmatched += 1
                    continue
                for parent_subject in parents:
                    quads.add(
                        f"{subject.n3()} {item.predicate.n3()} {parent_subject.n3()} "
                        f"{plan.target_graph.n3()} .\n"
                    )
            else:
                obj = _value(item.object_map, record)
                quads.add(f"{subject.n3()} {item.predicate.n3()} {obj.n3()} {plan.target_graph.n3()} .\n")
    return "".join(sorted(quads)), unmatched


def materialize(plan: Plan, records: Sequence[dict], parent_records: dict | None = None) -> str:
    """Return sorted, duplicate-free canonical N-Quads for source-order records."""
    return materialize_with_stats(plan, records, parent_records)[0]


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


def fetch_materialization(server: str, target_graph, opener=request.urlopen) -> dict | None:
    """Read the target graph's last-materialization stamp from `GET /graphs`.

    Quipu serves it parsed from transaction provenance (quipu-212), so this
    is the record of what actually committed, not a registry that can drift.
    `None` means the graph has never been RML-materialized (or predates the
    surface — an absent field, like an absent freshness note, is 'cannot
    tell', never 'fresh')."""
    req = request.Request(
        server.rstrip("/") + "/graphs", headers={"X-Quipu-Client": "agent-adhoc"}
    )
    try:
        with opener(req, timeout=30) as response:
            body = json.load(response)
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RmlExecutionError(f"freshness_indeterminate: {exc}") from exc
    for row in body.get("graphs", ()):
        if row.get("iri") == str(target_graph):
            return row.get("materialization")
    return None


FRESHNESS_WINDOW = re.compile(r"max_age\((\d+)([smhd])\)")
_WINDOW_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _window_elapsed(freshness: str, materialized_at: str | None, now) -> bool:
    """True when a machine-readable aegis:freshness window has passed.

    Only `max_age(N[smhd])` is machine-readable; any other declared freshness
    (e.g. `snapshot(fixture)`) contributes nothing to the verdict — the hash
    comparison stands alone. `now` arrives as an argument because the
    executor never invents it; the verdict is a read-time judgment and the
    caller owns the clock."""
    import datetime as _dt

    match = FRESHNESS_WINDOW.fullmatch(freshness or "")
    if not match or not materialized_at:
        return False
    then = _dt.datetime.fromisoformat(materialized_at.replace("Z", "+00:00"))
    if then.tzinfo is None:
        then = then.replace(tzinfo=_dt.timezone.utc)
    window = int(match.group(1)) * _WINDOW_SECONDS[match.group(2)]
    return (now - then).total_seconds() > window


def freshness_verdict(plan: Plan, current_hash: str, materialization: dict | None, now) -> dict:
    """The stale/fresh judgment behind `freshness` and `remap`.

    A mapping is STALE when the source bytes no longer match the hash the
    last materialization verified, or when a declared max_age window has
    elapsed. NEVER_MATERIALIZED is its own verdict, not a kind of stale —
    the caller may need to distinguish 'run it the first time' from 're-run
    it'. FRESH means re-running would reach quipu's idempotent `unchanged`
    outcome for the same bytes, which is also why over-triggering remap is
    harmless."""
    if materialization is None:
        return {"verdict": "never_materialized", "current_hash": current_hash}
    result = {
        "current_hash": current_hash,
        "materialized_hash": materialization.get("verified_hash"),
        "materialized_at": materialization.get("timestamp"),
        "materialized_tx": materialization.get("tx"),
    }
    if materialization.get("verified_hash") != current_hash:
        return {"verdict": "stale", "reason": "source_hash_changed", **result}
    if _window_elapsed(plan.freshness, materialization.get("timestamp"), now):
        return {"verdict": "stale", "reason": "window_elapsed", **result}
    return {"verdict": "fresh", **result}


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
    result.add_argument("command", choices=("validate", "execute", "freshness", "remap"))
    result.add_argument("triples_map_iri")
    result.add_argument("--mapping-file", type=Path)
    result.add_argument("--source-file", type=Path)
    # <logical-source-iri>=<path>, once per cross-source join parent.
    result.add_argument("--parent-source-file", action="append", default=[])
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
        if args.command in ("freshness", "remap"):
            if not args.server:
                raise RmlExecutionError("freshness_indeterminate: --server is required")
            if not args.source_file:
                raise RmlExecutionError("source_policy_refused: --source-file is required")
            import datetime as _dt

            source = load_source(plan, args.source_file, args.allowed_root or args.source_file.parent)
            stamp = fetch_materialization(args.server, plan.target_graph)
            verdict = freshness_verdict(
                plan, source.source_hash, stamp, _dt.datetime.now(_dt.timezone.utc)
            )
            output.update(phase="freshness", **verdict)
            if args.command == "freshness" or verdict["verdict"] == "fresh":
                # remap on a fresh mapping is a deliberate no-op: the same
                # bytes would only reach quipu's idempotent `unchanged`.
                print(json.dumps(output, sort_keys=True))
                return 0
            # remap on stale/never_materialized falls through to execute.
            args.command = "execute"
        if args.command == "execute":
            if not args.source_file:
                raise RmlExecutionError("source_policy_refused: --source-file is required")
            source = load_source(plan, args.source_file, args.allowed_root or args.source_file.parent)
            provided = {}
            for spec in args.parent_source_file:
                key, _, path = spec.partition("=")
                if not key or not path:
                    raise RmlExecutionError(
                        "source_policy_refused: --parent-source-file needs <logical-source-iri>=<path>"
                    )
                provided[key] = Path(path)
            parent_records = {}
            for key, parent_source in plan.parent_sources:
                if key not in provided:
                    raise RmlExecutionError(
                        f"source_policy_refused: cross-source join needs --parent-source-file {key}=<path>"
                    )
                parent_records[key] = load_source(
                    parent_source, provided[key], args.allowed_root or provided[key].parent
                ).records
            nquads, unmatched = materialize_with_stats(plan, source.records, parent_records)
            output.update(
                phase="materialized", nquads=nquads, source_hash=source.source_hash,
                input_count=len(source.records), output_count=len(nquads.splitlines()),
            )
            if any(isinstance(item.object_map, RefObject) for item in plan.predicate_objects):
                output.update(unmatched_joins=unmatched)
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
