#!/usr/bin/env python3
"""Which work is blocked, which just became unblocked, and which we cannot tell (aegis-c0awwp).

`aegis:blockedOn` points a WorkItem at what it waits on: another WorkItem (a
tracker dependency) or a Blocker condition with a checkable resolution. Whether
a blocker still holds is evaluated HERE, at read time, and never stored:

  WorkItem target   resolved when its current status is closed: the latest
                    Observation's observedStatus is "closed", or the WorkItem
                    carries aegis:closedAt. No status at all -> unknown.
  Blocker, date     resolved from aegis:resolvesOn onward.
  Blocker, query    resolved when its aegis:resolutionQuery ASK answers true;
                    false -> unresolved; an error or a malformed answer -> unknown.
  Blocker, neither  unknown: a stated reason nobody can check.

A work item is UNBLOCKED when every target is resolved, BLOCKED when any is
unresolved, and UNKNOWN otherwise. "Could not tell" never rounds to
"unblocked": that is the one direction an event consumer would act on.
Items whose own current status is closed are left out.

Reads only, with single-pattern queries (joins over the store time out), across
the default graph and the observed-records plane.

    python3 scripts/blocked_by.py            # JSON: one verdict per blocked item
    python3 scripts/blocked_by.py --item aegis-bgk9ho
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import planes  # noqa: E402
from ingest_work_items import BASE_NS  # noqa: E402

CLIENT = "camayoc-ingress"
A = BASE_NS
TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RESOLVED, UNRESOLVED, UNKNOWN = "resolved", "unresolved", "unknown"
BLOCKED, UNBLOCKED = "BLOCKED", "UNBLOCKED"


def graphs() -> list[str | None]:
    return [None, planes.plane_for("observed")]


def _iri(term: str) -> str:
    if term.startswith("aegis:"):
        return A + term[len("aegis:"):]
    return term


def _local(term: str) -> str:
    return _iri(term)[len(A):] if _iri(term).startswith(A) else term


def select(post, query: str) -> list[dict]:
    """Rows from every graph a record can live in, de-duplicated."""
    seen, rows = set(), []
    for graph in graphs():
        result = post("/query", {"query": query, **({"graph": graph} if graph else {})})
        if not isinstance(result.get("rows"), list) or result.get("truncated"):
            raise ValueError(f"query unproven in {graph or 'default'}: {query[:80]}")
        for row in result["rows"]:
            key = json.dumps(row, sort_keys=True)
            if key not in seen:
                seen.add(key)
                rows.append(row)
    return rows


def current_status(post, item: str) -> str | None:
    """The tracker status of a WorkItem from its LATEST Observation; "closed"
    also when the WorkItem carries aegis:closedAt; None when nothing says."""
    if select(post, f"SELECT ?c WHERE {{ <{A}{item}> <{A}closedAt> ?c }}"):
        return "closed"
    obs = latest_observation(post, item)
    if obs is None:
        return None
    rows = select(post, f"SELECT ?st WHERE {{ <{A}{obs}> <{A}observedStatus> ?st }}")
    if rows:
        return str(rows[0]["st"]).strip('"')
    # Older Observations carry status only inside their JSON snapshot.
    rows = select(post, f"SELECT ?v WHERE {{ <{A}{obs}> <{A}observedValue> ?v }}")
    try:
        raw = str(rows[0]["v"])
        raw = raw[1:-1].encode().decode("unicode_escape") if raw.startswith('"') else raw
        return json.loads(raw).get("status")
    except (IndexError, ValueError, AttributeError):
        return None


def latest_observation(post, item: str) -> str | None:
    """The WorkItem's Observation with the latest observedAt, or None."""
    rows = select(post, f"SELECT ?obs ?at WHERE {{ <{A}{item}> <{A}observes> ?obs . "
                        f"?obs <{A}observedAt> ?at }}")
    if not rows:
        return None
    return _local(max(rows, key=lambda r: str(r.get("at", "")))["obs"])


def blocker_state(post, target: str, today: dt.date) -> tuple[str, str]:
    """(state, why) for one blockedOn target."""
    types = {_iri(r["t"]) for r in select(post, f"SELECT ?t WHERE {{ <{A}{target}> a ?t }}")}
    if A + "WorkItem" in types:
        status = current_status(post, target)
        if status is None:
            return UNKNOWN, f"{target}: no tracker status in the graph"
        return (RESOLVED if status == "closed" else UNRESOLVED), f"{target}: {status}"
    if A + "Blocker" in types:
        dates = select(post, f"SELECT ?d WHERE {{ <{A}{target}> <{A}resolvesOn> ?d }}")
        asks = select(post, f"SELECT ?q WHERE {{ <{A}{target}> <{A}resolutionQuery> ?q }}")
        if dates:
            raw = str(dates[0]["d"]).split("^^")[0].strip('"')
            try:
                when = dt.date.fromisoformat(raw[:10])
            except ValueError:
                return UNKNOWN, f"{target}: unreadable resolvesOn {raw!r}"
            return (RESOLVED if today >= when else UNRESOLVED), f"{target}: date {when}"
        if asks:
            ask = str(asks[0]["q"]).strip('"').encode().decode("unicode_escape")
            try:
                answer = post("/query", {"query": ask})
            except Exception as error:  # an ASK we could not run is not an answer
                return UNKNOWN, f"{target}: resolution query failed ({type(error).__name__})"
            if isinstance(answer.get("result"), bool):
                return (RESOLVED if answer["result"] else UNRESOLVED), f"{target}: ASK {answer['result']}"
            return UNKNOWN, f"{target}: resolution query gave no boolean"
        return UNKNOWN, f"{target}: a Blocker with no checkable resolution"
    return UNKNOWN, f"{target}: not a WorkItem or Blocker in the graph"


def verdict(states: list[str]) -> str:
    if states and all(s == RESOLVED for s in states):
        return UNBLOCKED
    if any(s == UNRESOLVED for s in states):
        return BLOCKED
    return UNKNOWN.upper()


def evaluate(post, *, item: str | None = None, today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    scope = f"<{A}{item}>" if item else "?w"
    # Declared by an agent on the WorkItem ...
    edges = select(post, f"SELECT {'?w ' if not item else ''}?t WHERE {{ {scope} <{A}blockedOn> ?t }}")
    by_item: dict[str, list[str]] = {}
    for row in edges:
        w = item or _local(row["w"])
        by_item.setdefault(w, []).append(_local(row["t"]))
    # ... and projected from the tracker onto the LATEST Observation only, so a
    # removed dependency (absent from the newest Observation) no longer blocks.
    projected = select(post, f"SELECT ?w ?obs ?t WHERE {{ ?w <{A}observes> ?obs . "
                             f"?obs <{A}observedBlockedOn> ?t }}")
    for row in projected:
        w = _local(row["w"])
        if item and w != item:
            continue
        if latest_observation(post, w) == _local(row["obs"]):
            by_item.setdefault(w, []).append(_local(row["t"]))
    out = []
    for w, targets in sorted(by_item.items()):
        if current_status(post, w) == "closed":
            continue
        judged = [blocker_state(post, t, today) for t in sorted(set(targets))]
        out.append({"item": w, "verdict": verdict([s for s, _ in judged]),
                    "blockers": [{"state": s, "why": why} for s, why in judged]})
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--item", help="one work item id (e.g. aegis-bgk9ho)")
    args = parser.parse_args(argv)
    post = lambda endpoint, body: planes._post(endpoint, body, client=CLIENT)  # noqa: E731
    print(json.dumps(evaluate(post, item=args.item), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
