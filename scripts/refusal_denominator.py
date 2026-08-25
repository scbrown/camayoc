#!/usr/bin/env python3
"""Report the refused-write denominator §4.2 says the incident corpus lacks.

    accepted Verifications   <-- the graph, via a stored query
    refused writes           <-- quipu's durable write.refused event stream
    the share                <-- computed HERE, at read time, and never stored

THE GAP THIS CLOSES, AND THE ONE IT DOES NOT
============================================

`docs/design/incident-corpus.md` §4.2 is a section about a missing
denominator: the corpus counts the verifications that got through and has no
count of the ones that were turned away, so "how often does the gate fire" has
never had an answer. §5 item 1 says the source now exists — quipu main
`71440ff` records every gate refusal as a durable `write.refused` event with
graph/actor/source/reason/refused_datums, served by
`GET /events?types=write.refused`. This is the reporter that consumes it.

It does NOT close §5 item 2, and is written so it cannot be mistaken for
having done so. See THREE FLOORS below.

A REPORTER, NOT AN INGEST — AND THAT IS A RULE, NOT A SCOPE CUT
===============================================================

Nothing here writes to the graph. A refusal *rate* is a ratio between two
populations that both keep moving, which makes it a judgment computed at read
time, not a fact true at write time — camayoc's fourth convention, applied to
camayoc. Storing "the refusal rate was 4%" would store something that starts
decaying the moment the next write lands. So this prints, and the graph stays
out of it.

That is also why no vocabulary is minted here. §5 item 2's A1-A7 form
taxonomy is deliberately NOT built: no competency question asks for per-form
refusal counts, and competency-before-classes does not lapse because a
blocking dependency cleared.

THREE FLOORS, AND THE REPORT NAMES ALL THREE EVERY TIME
=======================================================

The refusal share this prints is a FLOOR in three independent ways, and each
one is a property of the source rather than of this script:

1. **`speculate` refusals are excluded from the stream.** A write refused
   inside a speculation never reaches the event log, by quipu's design. Real
   refusals are therefore at least what is counted here.

2. **The refused fact BODIES are not stored.** The stream answers *how many
   and why*, never *what was rejected*. So a per-form breakdown cannot be
   recovered from this source at all — not by a cleverer query, not later.
   The `reason` field names the GATE that refused (shacl | policy | authority
   | owl | placement), not the shape that failed, so even
   "refused for a missing falsifier" is not directly countable: the shacl
   total is an UPPER bound on it and is reported as one. Any narrowing this
   script does is an operator-supplied `--reason-contains` filter, reported as
   the operator's filter and never as an inferred classification.

3. **The two populations do not share a time origin.** This is the subtle one
   and it is §4.2's own defect at a new scale. Refusals are counted from a
   stream that began when quipu started recording `write.refused`; accepted
   Verifications are counted from the resident graph, which contains
   everything ever written — including the pre-gate legacy population that
   `camayoc_verifications_without_falsifier` exists to find. Dividing a
   prospective stream count by a retrospective store snapshot inflates the
   denominator, which understates the share. Reported, not smoothed over.

COULD NOT LOOK IS NOT ZERO
==========================

`scripts/gate_probe.sh`'s discipline, because the failure is identical: an
unreachable store, or a quipu predating the event stream, must never be
rendered as "no refusals". Both exit 3 with the reason named. A store that
answers with zero refusals exits 0 and says zero.

Usage:
    python3 scripts/refusal_denominator.py
    python3 scripts/refusal_denominator.py --json
    python3 scripts/refusal_denominator.py --events-file saved-events.json \\
        --accepted 128
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

SERVER = os.environ.get("QUIPU_SERVER", "http://localhost:3030").rstrip("/")
AUTH = os.environ.get("QUIPU_AUTH_TOKEN")

#: The stored query that counts the accepted population. Named rather than
#: inlined as SPARQL so the denominator is auditable in `queries/` like every
#: other question this repo asks of the store.
ACCEPTED_QUERY = "camayoc_verification_population"

#: The gate classes quipu records in `reason`. Listed so an UNRECOGNISED
#: reason is visible as unrecognised instead of being silently bucketed —
#: a new gate class must show up as a new row, not vanish into "other".
KNOWN_GATES = ("shacl", "policy", "authority", "owl", "placement")

#: The gate whose refusals CONTAIN the missing-falsifier ones. It does not
#: identify them: the shape that failed is not in the record.
SHAPE_GATE = "shacl"

#: Keys the event payload might carry a timestamp under. Tried in order; if
#: none is present the time range reads UNKNOWN rather than being invented,
#: because a range invented from ingest order would look like evidence.
TIME_KEYS = ("at", "time", "timestamp", "observed_at", "observedAt", "created_at")


class CouldNotLook(RuntimeError):
    """No answer came back. Not evidence that there were no refusals."""


def _request(path: str, payload: dict | None = None) -> dict | list:
    request = urllib.request.Request(
        f"{SERVER}{path}",
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    if AUTH:
        request.add_header("Authorization", f"Bearer {AUTH}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise CouldNotLook(
                f"{path} returned 404 — this quipu predates the write.refused "
                "event stream (quipu main 71440ff). That is 'cannot tell', not "
                "'no refusals'."
            ) from exc
        raise CouldNotLook(f"{path} failed: HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise CouldNotLook(f"{path} unreachable: {exc} — this is not evidence") from exc
    except ValueError as exc:
        raise CouldNotLook(f"{path} returned a body that is not JSON: {exc}") from exc


def events_from_payload(payload) -> list[dict]:
    """The event list, whatever envelope it arrived in — or an abstention.

    Tolerant about the envelope and strict about the outcome: an unrecognised
    shape raises rather than returning `[]`, because an empty list here would
    print as "0 refusals" and be indistinguishable from a healthy store.
    """
    if isinstance(payload, list):
        candidate = payload
    elif isinstance(payload, dict):
        for key in ("events", "items", "results", "data"):
            if isinstance(payload.get(key), list):
                candidate = payload[key]
                break
        else:
            raise CouldNotLook(
                f"no event list in the response (keys: {sorted(payload)}). "
                "Refusing to read that as zero refusals."
            )
    else:
        raise CouldNotLook(f"unexpected response type {type(payload).__name__}")
    return [e for e in candidate if isinstance(e, dict)]


def fetch_refusals() -> list[dict]:
    query = urllib.parse.urlencode({"types": "write.refused"})
    return events_from_payload(_request(f"/events?{query}"))


def fetch_accepted() -> int:
    """The accepted Verification population, via the named stored query."""
    answer = _request("/ask", {"name": ACCEPTED_QUERY, "params": {}})
    if not isinstance(answer, dict) or "count" not in answer:
        raise CouldNotLook(
            f"/ask {ACCEPTED_QUERY} returned no count "
            f"(keys: {sorted(answer) if isinstance(answer, dict) else answer!r}). "
            "An accepted population that could not be read is not an accepted "
            "population of zero."
        )
    count = answer["count"]
    if not isinstance(count, int):
        raise CouldNotLook(f"/ask {ACCEPTED_QUERY} returned a non-integer count: {count!r}")
    return count


def event_time(event: dict) -> str | None:
    for key in TIME_KEYS:
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def summarise(events: list[dict], reason_contains: str | None = None) -> dict:
    """Counts, verbatim groupings, and the observed time range.

    No event is classified beyond the fields it carries. `reason` is grouped
    by its literal value; a value outside KNOWN_GATES is reported as
    unrecognised rather than folded into a bucket.
    """
    selected = events
    if reason_contains:
        selected = [
            e for e in events if reason_contains.lower() in str(e.get("reason", "")).lower()
        ]

    reasons = Counter(str(e.get("reason", "")) or "(no reason recorded)" for e in selected)
    graphs = Counter(str(e.get("graph", "")) or "(no graph recorded)" for e in selected)
    actors = Counter(str(e.get("actor", "")) or "(no actor recorded)" for e in selected)
    sources = Counter(str(e.get("source", "")) or "(no source recorded)" for e in selected)

    stamps = sorted(t for t in (event_time(e) for e in selected) if t)
    untimed = len(selected) - len(stamps)

    datums = 0
    datums_missing = 0
    for event in selected:
        value = event.get("refused_datums")
        if isinstance(value, int):
            datums += value
        elif isinstance(value, list):
            datums += len(value)
        else:
            datums_missing += 1

    return {
        "refused": len(selected),
        "refused_before_filter": len(events),
        "reason_filter": reason_contains,
        "by_reason": dict(reasons.most_common()),
        "by_graph": dict(graphs.most_common()),
        "by_actor": dict(actors.most_common()),
        "by_source": dict(sources.most_common()),
        "unrecognised_reasons": sorted(r for r in reasons if r not in KNOWN_GATES),
        # An upper bound on the missing-falsifier count, never the count.
        "shape_gate_refusals": reasons.get(SHAPE_GATE, 0),
        "refused_datums": datums,
        "events_without_datum_count": datums_missing,
        "first_seen": stamps[0] if stamps else None,
        "last_seen": stamps[-1] if stamps else None,
        "events_without_a_timestamp": untimed,
    }


def rate(accepted: int, refused: int) -> float | None:
    """The refused share of all attempted writes, or None when undefined.

    None, not 0.0, when there is nothing to divide: a store with no accepted
    verifications and no refusals has no rate, and printing 0% would state a
    measurement nobody made.
    """
    total = accepted + refused
    return None if total == 0 else refused / total


def render(summary: dict, accepted: int | None) -> list[str]:
    lines = ["REFUSED-WRITE DENOMINATOR (docs/design/incident-corpus.md §4.2, §5.1)", ""]
    lines.append(f"  refused writes in the stream : {summary['refused']}")
    if summary["reason_filter"]:
        lines.append(
            f"    (narrowed from {summary['refused_before_filter']} by the "
            f"OPERATOR-supplied filter --reason-contains "
            f"{summary['reason_filter']!r}; this is the operator's "
            f"classification, not one this stream records)"
        )
    if accepted is None:
        lines.append("  accepted Verifications      : UNKNOWN (not read)")
    else:
        lines.append(f"  accepted Verifications      : {accepted}")
    share = None if accepted is None else rate(accepted, summary["refused"])
    if share is None:
        lines.append("  refused share               : UNDEFINED — nothing to divide")
    else:
        lines.append(f"  refused share               : {share:.2%}  (A FLOOR — see below)")
    lines.append("")

    lines.append("  by reason (the GATE that refused, verbatim):")
    for reason, count in summary["by_reason"].items() or ():
        mark = "  <- not a known gate class" if reason in summary["unrecognised_reasons"] else ""
        lines.append(f"    {count:>6}  {reason}{mark}")
    if not summary["by_reason"]:
        lines.append("         0  (no refusals recorded)")
    lines.append("")

    for title, key in (("by graph", "by_graph"), ("by actor", "by_actor"),
                       ("by source", "by_source")):
        if summary[key]:
            lines.append(f"  {title}:")
            for name, count in summary[key].items():
                lines.append(f"    {count:>6}  {name}")
            lines.append("")

    window = (
        f"{summary['first_seen']} .. {summary['last_seen']}"
        if summary["first_seen"] else "UNKNOWN — no event carried a timestamp field"
    )
    lines.append(f"  observed stream window      : {window}")
    if summary["events_without_a_timestamp"]:
        lines.append(
            f"    ({summary['events_without_a_timestamp']} event(s) carried no "
            "timestamp and are outside that window rather than inside it)"
        )
    lines.append(
        f"  refused datums (where recorded): {summary['refused_datums']}"
        + (f", {summary['events_without_datum_count']} event(s) recorded none"
           if summary["events_without_datum_count"] else "")
    )
    lines.append("")
    lines.extend(caveats(summary))
    return lines


def caveats(summary: dict) -> list[str]:
    """Printed every run. Not a footnote and not conditional on a flag."""
    return [
        "  THIS SHARE IS A FLOOR, THREE TIMES OVER:",
        "  1. speculate refusals are excluded from the stream by design, so the",
        "     real refusal count is at least the one above.",
        "  2. the refused fact BODIES are not stored. The stream answers how many",
        "     and why, never what was rejected — so a per-form (A1-A7) breakdown",
        "     cannot be recovered from this source by any query. `reason` names",
        "     the GATE, not the shape: the "
        f"{summary['shape_gate_refusals']} {SHAPE_GATE} refusal(s) above are an",
        "     UPPER bound on 'refused for a missing falsifier', not a count of it.",
        "  3. the two populations have different time origins. Refusals are a",
        "     prospective stream that began when quipu started recording them;",
        "     accepted Verifications are the resident graph, which includes every",
        "     pre-gate write ever made. The denominator is therefore too large and",
        "     the share too small.",
        "",
        "  No vocabulary was minted to produce this report, and none should be to",
        "  improve it. §5 item 2's A1-A7 form taxonomy stays deferred until a",
        "  competency question asks for per-form counts.",
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--events-file", type=Path,
                    help="read the write.refused payload from a saved JSON file "
                         "instead of the store. The same report over an exported "
                         "stream — and the only way to run this without a live "
                         "quipu.")
    ap.add_argument("--accepted", type=int,
                    help="supply the accepted Verification count instead of "
                         "asking the store for it. Only meaningful with "
                         "--events-file; a hand-supplied denominator is the "
                         "caller's claim, not a measurement.")
    ap.add_argument("--reason-contains",
                    help="narrow to refusals whose reason contains this text. "
                         "Reported as YOUR filter: this stream records the gate "
                         "that refused, not the shape that failed, so any finer "
                         "classification is a claim about your deployment's "
                         "reason strings and not something camayoc inferred.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    try:
        if args.events_file:
            events = events_from_payload(json.loads(args.events_file.read_text()))
        else:
            events = fetch_refusals()
        accepted = args.accepted
        if accepted is None and not args.events_file:
            accepted = fetch_accepted()
    except CouldNotLook as exc:
        # Exit 3, gate_probe.sh's code for the same distinction: no answer came
        # back, which is not an answer of zero.
        print(f"COULD NOT LOOK: {exc}", file=sys.stderr)
        print("Reporting nothing rather than reporting zero.", file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print(f"COULD NOT LOOK: {args.events_file}: {exc}", file=sys.stderr)
        return 3

    summary = summarise(events, args.reason_contains)
    summary["accepted"] = accepted
    summary["refused_share"] = None if accepted is None else rate(accepted, summary["refused"])

    if args.json:
        summary["floors"] = [
            "speculate refusals excluded from the stream",
            "refused fact bodies not stored: no per-form breakdown is recoverable, "
            "and `reason` names the gate rather than the failing shape",
            "prospective refusal stream divided by a retrospective accepted "
            "population: the denominator is too large",
        ]
        print(json.dumps(summary, indent=2))
        return 0

    print("\n".join(render(summary, accepted)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
