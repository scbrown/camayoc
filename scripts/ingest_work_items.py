#!/usr/bin/env python3
"""Deterministically map br/st tracker records to governed Camayoc WorkItems.

The tracker record is evidence for a unit of work; it is not a new ontology
class.  This adapter therefore emits the existing ``WorkItem`` class, tags it
``observed``, records the stable tracker id as ``identifier``, and routes the
episode through Camayoc's observed records plane.  Quipu remains only the
governed store receiving the resulting ordinary ``/episode`` request.

Input is the JSON emitted by ``br show <id> --json`` (a one-element array) or
one record object.  By default the episode JSON is printed.  ``--post`` sends
that exact body through Camayoc's ingress helper.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

import planes

SOURCE_KIND = "observed"
BASE_NS = "http://aegis.gastown.local/ontology/"


class WorkItemError(ValueError):
    """The tracker record cannot be mapped without guessing."""


def _entity_name(value: str) -> str:
    """Convert a local ontology IRI to the relative name `/episode` accepts."""
    name = value.removeprefix(BASE_NS)
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for c in name):
        raise WorkItemError(
            f"about target must be a safe local entity name or {BASE_NS} IRI: {value!r}"
        )
    return name


def _record(payload: object) -> dict:
    if isinstance(payload, list):
        if len(payload) != 1:
            raise WorkItemError(f"expected exactly one tracker record, got {len(payload)}")
        payload = payload[0]
    if not isinstance(payload, dict):
        raise WorkItemError("tracker payload must be an object or one-element array")
    return payload


def episode_for(payload: object, *, actor: str, source: str, about: list[str] | None = None) -> dict:
    """Return the governed episode for one tracker record.

    Mutable tracker status is deliberately not copied.  Open/in-progress is a
    read-time judgment; only a recorded close becomes the durable ``done``
    outcome required by the WorkItem model.
    """
    record = _record(payload)
    item_id = record.get("id")
    title = record.get("title")
    created = record.get("created_at")
    if not all(isinstance(v, str) and v.strip() for v in (item_id, title, created)):
        raise WorkItemError("tracker record needs non-empty id, title, and created_at")

    properties: dict[str, str] = {
        "sourceKind": SOURCE_KIND,
        "identifier": item_id,
        "createdAt": created,
    }
    if record.get("status") == "closed":
        closed = record.get("closed_at")
        if not isinstance(closed, str) or not closed.strip():
            raise WorkItemError("closed tracker record needs closed_at; refusing to invent it")
        properties.update({"closedAt": closed, "outcome": "done"})

    edges = [
        {"source": item_id, "target": _entity_name(iri), "relation": "about"}
        for iri in sorted(set(about or []))
    ]
    body = {
        "name": f"tracker-work-item:{item_id}",
        "graph": planes.plane_for(SOURCE_KIND),
        "episode_body": f"Deterministic tracker projection for {item_id}",
        "source": source,
        "actor": actor,
        "nodes": [{
            "name": item_id,
            "type": "WorkItem",
            "description": title,
            "properties": properties,
        }],
        "edges": edges,
    }
    return body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", nargs="?", type=Path, help="br JSON file; stdin when omitted")
    ap.add_argument("--actor", required=True)
    ap.add_argument("--source", help="stable source reference (default: br:<record-id>)")
    ap.add_argument("--about", action="append", default=[], help="Directive/entity IRI; repeatable")
    ap.add_argument("--post", action="store_true", help="POST the generated episode to Quipu")
    args = ap.parse_args()

    raw = args.input.read_text() if args.input else sys.stdin.read()
    payload = json.loads(raw)
    record = _record(payload)
    source = args.source or f"br:{quote(str(record.get('id', '')), safe='-')}"
    body = episode_for(record, actor=args.actor, source=source, about=args.about)
    result = planes._post("/episode", body) if args.post else body
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
