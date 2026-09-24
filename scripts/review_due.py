#!/usr/bin/env python3
"""Which graph entities are due to be re-checked, and which we cannot tell (aegis-kxjack).

Stiwi 2026-09-24: "check on this after this time and quipu will emit an event"
("age not agent"). Any entity may declare a review age:

  aegis:reviewAfter  an ISO-8601 instant; DUE from then on.
  aegis:maxAge       an ISO-8601 duration (PnW or PnDTnHnM), anchored on the
                     latest aegis:verifiedAt of a Verification that
                     aegis:verifies the entity. No such verification means
                     UNKNOWN: an unanchored age is neither fresh nor due.

An entity is DUE when any declared age has passed, NOT_DUE when every declared
age is known and still ahead, and UNKNOWN otherwise. A known overdue age wins
over an unknown one: something already overdue does not become "cannot tell"
because a second age is unanchored.

Each verdict is the adapter record an emitter consumes, the same contract as
blocked_by.py: entity, verdict, due_at (the earliest known due instant),
evidence (a stable digest of what decided it: audit identity, NOT a dedupe
key), owner (aegis:ownedBy, or null) and the per-age basis. This script holds
no memory between runs; transitions and delivery belong to the emitter.

Reads only, with single-pattern or bound-subject queries (joins exceed quipu's
10 s budget live), across the default graph and the observed and declared
planes, never the inferred one.

    python3 scripts/review_due.py              # JSON: one verdict per aged entity
    python3 scripts/review_due.py --due-only   # only the DUE ones
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import planes  # noqa: E402
from blocked_by import A, CLIENT, _local, select  # noqa: E402

DUE, NOT_DUE, UNKNOWN = "DUE", "NOT_DUE", "UNKNOWN"
_DURATION = re.compile(r"^P(?:(\d+)W|(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?)$")


def parse_instant(raw: str) -> dt.datetime | None:
    """An ISO-8601 date or offset instant as an aware UTC datetime, else None.
    A bare date means the start of that day, UTC."""
    text = raw.split("^^")[0].strip().strip('"')
    try:
        if len(text) == 10:
            return dt.datetime.fromisoformat(text).replace(tzinfo=dt.timezone.utc)
        value = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.astimezone(dt.timezone.utc) if value.tzinfo else None


def parse_duration(raw: str) -> dt.timedelta | None:
    text = raw.split("^^")[0].strip().strip('"')
    m = _DURATION.match(text)
    if not m or text in ("P", "PT"):
        return None
    weeks, days, hours, minutes = (int(g) if g else 0 for g in m.groups())
    return dt.timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes)


def _values(post, entity: str, prop: str) -> list[str]:
    return [str(r["v"]) for r in select(post, f"SELECT ?v WHERE {{ <{A}{entity}> <{A}{prop}> ?v }}")]


def last_verified(post, entity: str) -> dt.datetime | None:
    """Latest verifiedAt over Verifications that verify this entity: two bound
    single-pattern steps, never a join."""
    latest = None
    for row in select(post, f"SELECT ?ver WHERE {{ ?ver <{A}verifies> <{A}{entity}> }}"):
        for raw in _values(post, _local(row["ver"]), "verifiedAt"):
            when = parse_instant(raw)
            if when and (latest is None or when > latest):
                latest = when
    return latest


def judge(post, entity: str, now: dt.datetime) -> dict:
    basis = []
    for raw in _values(post, entity, "reviewAfter"):
        when = parse_instant(raw)
        basis.append({"age": "reviewAfter", "value": raw.strip('"'),
                      "due_at": when.isoformat() if when else None,
                      "why": "declared instant" if when else "unreadable instant"})
    for raw in _values(post, entity, "maxAge"):
        span = parse_duration(raw)
        anchor = last_verified(post, entity) if span else None
        when = anchor + span if anchor and span else None
        why = ("unreadable duration" if span is None else
               "no Verification verifies it, so the age has no anchor" if anchor is None else
               f"last verified {anchor.isoformat()}")
        basis.append({"age": "maxAge", "value": raw.strip('"'),
                      "due_at": when.isoformat() if when else None, "why": why})
    known = [dt.datetime.fromisoformat(b["due_at"]) for b in basis if b["due_at"]]
    if any(t <= now for t in known):
        verdict = DUE
    elif known and len(known) == len(basis):
        verdict = NOT_DUE
    else:
        verdict = UNKNOWN
    owners = [_local(r["v"]) for r in select(post, f"SELECT ?v WHERE {{ <{A}{entity}> <{A}ownedBy> ?v }}")]
    ident = json.dumps([entity, sorted((b["age"], b["value"], b["due_at"] or "") for b in basis)],
                       separators=(",", ":"))
    return {"entity": entity, "verdict": verdict,
            "due_at": min(known).isoformat() if known else None,
            "evidence": "sha256:" + hashlib.sha256(ident.encode()).hexdigest(),
            "owner": sorted(owners)[0] if owners else None, "basis": basis}


def evaluate(post, *, now: dt.datetime | None = None) -> list[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    aged = set()
    for prop in ("reviewAfter", "maxAge"):
        for row in select(post, f"SELECT ?s WHERE {{ ?s <{A}{prop}> ?v }}"):
            aged.add(_local(row["s"]))
    return [judge(post, e, now) for e in sorted(aged)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--due-only", action="store_true")
    args = parser.parse_args(argv)
    post = lambda endpoint, body: planes._post(endpoint, body, client=CLIENT)  # noqa: E731
    rows = evaluate(post)
    if args.due_only:
        rows = [r for r in rows if r["verdict"] == DUE]
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
