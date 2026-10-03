"""Incremental adapter protocol: bounded changed subjects, not population scans.

The consumer persists /changes records before acknowledgement. Deleted edges carry
old_value, so their former owners are still invalidated. No graph writes here.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time

import blocked_by as bb
import planes

BLOCKER = {"blockerKind", "prRef", "tool", "minVersion", "repoRef", "resolvesOn", "resolutionQuery"}
OBS = {"observedAt", "observedStatus", "observedValue", "observedBlockedOn"}
WORK = {"blockedOn", "observes", "closedAt"}
REVIEW = {"reviewAfter", "maxAge", "ownedBy", "verifies", "verifiedAt"}


def description(kind):
    props = WORK | OBS | BLOCKER if kind == "blocked" else REVIEW
    return {"version": 1, "attributes": sorted({iri for p in props for iri in bb.term_iris(p)}),
            "graphs": [g or "ROOT" for g in bb.graphs()],
            "types": bb.term_iris("WorkItem") + bb.term_iris("Blocker") if kind == "blocked" else []}


def local(iri):
    """Only instance IRIs in the configured namespace are adapter keys."""
    if not isinstance(iri, str) or not iri.startswith(bb.A):
        return None
    name = iri[len(bb.A):]
    if not name or any(c in name for c in '<>"{}\\\n\r\t '):
        raise ValueError("unsafe entity IRI")
    return name


def values(post, subject, prop, reverse=False):
    p = bb.pattern("?v", prop, f"<{bb.A}{subject}>") if reverse else bb.pattern(f"<{bb.A}{subject}>", prop, "?v")
    return [bb._local(str(r["v"])) for r in bb.select(post, f"SELECT ?v WHERE {{ {p} }}")]


def targets(post, kind, changes, items):
    out = set(items)
    subjects = set()
    for change in changes:
        entity = local(change["entity"])
        if entity is None:
            continue
        prop = change.get("attribute", "").rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        if kind == "blocked":
            if prop in OBS:
                subjects.update(values(post, entity, "observes", reverse=True))
            else:
                subjects.add(entity)
        else:
            if prop in {"verifies", "verifiedAt"}:
                out.update(values(post, entity, "verifies"))
                if prop == "verifies":
                    for field in ("value", "old_value"):
                        value = change.get(field)
                        name = local(value.get("ref")) if isinstance(value, dict) else None
                        if name:
                            out.add(name)
            else:
                out.add(entity)
    if kind == "blocked":
        out.update(subjects)
        for subject in sorted(subjects):
            out.update(values(post, subject, "blockedOn", reverse=True))
            for obs in values(post, subject, "observedBlockedOn", reverse=True):
                out.update(values(post, obs, "observes", reverse=True))
    return sorted(out)


def next_check(post, kind, record, now):
    """Wall-clock dependencies are persisted as deadlines by the consumer.

    External tools and arbitrary ASK expressions cannot supply a finite graph
    dependency set. Only those items retain a bounded 15-minute check.
    """
    deadlines = []
    if kind == "review":
        from review_due import parse_instant
        if record["verdict"] != "DUE":
            for basis in record["basis"]:
                when = parse_instant(basis["due_at"]) if basis["due_at"] else None
                if when and when.timestamp() > now:
                    deadlines.append(when.timestamp())
    else:
        for blocker in record["blockers"]:
            target = blocker["target"]
            if values(post, target, "resolutionQuery") or values(post, target, "blockerKind"):
                deadlines.append(now + 900)
            for raw in values(post, target, "resolvesOn"):
                try:
                    day = dt.date.fromisoformat(raw.strip('"')[:10])
                    when = dt.datetime.combine(day, dt.time(), dt.timezone.utc).timestamp()
                    if when > now:
                        deadlines.append(when)
                except ValueError:
                    pass
    return min(deadlines) if deadlines else None


def evaluate(kind, post, request):
    import review_due as rd
    transport, cache = post, {}
    def post(endpoint, body):
        key = (endpoint, json.dumps(body, sort_keys=True))
        if key not in cache:
            cache[key] = transport(endpoint, body)
        return cache[key]
    now = float(request["now"])
    instant = dt.datetime.fromtimestamp(now, dt.timezone.utc)
    if request.get("discover"):
        if kind == "review":
            names = {bb._local(r["s"]) for prop in ("reviewAfter", "maxAge")
                     for r in bb.select(post, f"SELECT ?s WHERE {{ {bb.pattern('?s', prop, '?v')} }}")}
        else:
            names = {bb._local(r["w"]) for r in bb.select(post,
                     f"SELECT ?w WHERE {{ {bb.pattern('?w', 'blockedOn', '?d')} }}")}
            observations = {bb._local(r["o"]) for r in bb.select(post,
                            f"SELECT ?o WHERE {{ {bb.pattern('?o', 'observedBlockedOn', '?d')} }}")}
            if observations:
                names.update(bb._local(r["w"]) for r in bb.select(post,
                             f"SELECT ?w ?o WHERE {{ {bb.pattern('?w', 'observes', '?o')} }}")
                             if bb._local(r["o"]) in observations)
        return {"version": 1, "items": sorted(names)}
    if "route" in request:
        return {"version": 1, "items": targets(post, kind, request["route"], [])}
    full = request.get("full", False)
    key = "item" if kind == "blocked" else "entity"
    scope = None if full else targets(post, kind, request.get("changes", []), request.get("items", []))
    if full:
        records = bb.evaluate(post, today=instant.date()) if kind == "blocked" else rd.evaluate(post, now=instant)
    elif kind == "blocked":
        records = [r for item in scope for r in bb.evaluate(post, item=item, today=instant.date(), batch_history=True)]
    else:
        records = [rd.judge(post, item, instant) for item in scope]
        records = [r for r in records if r["basis"]]
    return {"version": 1, "scope": scope, "records": records,
            "next_checks": {r[key]: next_check(post, kind, r, now) for r in records}}


def main(kind, describe=False):
    if describe:
        print(json.dumps(description(kind)))
    else:
        request = json.load(sys.stdin)
        last_read = 0.0
        def post(endpoint, body):
            nonlocal last_read
            # At most eight reads/second, including catalogue reconciliation.
            time.sleep(max(0, last_read + 0.125 - time.monotonic()))
            last_read = time.monotonic()
            return planes._post(endpoint, body, client=bb.CLIENT)
        print(json.dumps(evaluate(kind, post, request)))
    return 0
