#!/usr/bin/env python3
"""Parse harness session logs into the §D cost vocabulary as Turtle.

    Principal  <--aegis:actor--  Session  <--aegis:inSession--  UsageRecord

THE GAP THIS CLOSES
===================

`docs/design/incident-corpus.md` §5 item 3 asks for agent-hour/agent-token
normalisation "available from the cost-accounting slice (competency §D, Q17)
— both harnesses already write complete per-session token accounting to local
disk, so agent-hours are a deterministic-parser fact and need no new
plumbing." `camayoc-e29` minted the vocabulary and the stored queries
(Q16–Q21) and proved them against a fixture. Nothing turned a live window's
records into that vocabulary, so every one of those queries answered only
about the fixture.

DETERMINISTIC, WHICH IS THE WHOLE POINT
=======================================

Ingress rule 3: a parser can produce these from a record, so a parser does,
and they enter as `observed` with no model in the loop. Run it twice over the
same logs and you get byte-identical Turtle.

THE UNIT OF CONSUMPTION IS THE REQUEST, NOT THE LOG ENTRY
=========================================================

MEASURED, NOT REASONED. The claude harness writes one JSONL entry per content
block of an assistant turn — thinking, text, and each tool call — and **every
one of them repeats the same `usage` object for the whole request**. Measured
against a real 2026-08-24 session log: 237 entries carrying usage, 92 distinct
`requestId`s, and the usage object identical across every entry sharing a
requestId. Summing per entry reports 39,467,766 tokens where the session
consumed 15,653,391 — a 2.5x overcount, in the flattering direction for
anyone reporting throughput and the punishing one for anyone reporting spend.

So the record is keyed by `requestId` and the first entry for each wins. An
entry carrying usage but **no** requestId cannot be deduplicated against its
siblings and is therefore ABSTAINED — counted in the summary, never emitted.
A dropped request understates a total visibly; a triple-counted one corrupts
every rate built on it.

ABSTAIN, NEVER GUESS — WHICH IS WHY CODEX IS NOT PARSED HERE
============================================================

competency/verification-and-liveness.md §D names two harnesses. Only the
claude layout was verifiable against a real on-disk record when this was
written; no `~/.codex/sessions/**/rollout-*.jsonl` was available to measure.
Its field names are recorded in the competency suite as prose, and a parser
written from prose is a guess wearing a parser's clothes — the requestId
finding above is exactly what prose does not tell you. Codex files are
therefore counted as UNRECOGNISED in the denominator and emit nothing. Adding
the reader is a small change (`READERS` below) once a real rollout file can
be measured; inventing it now would put wrong integers into the graph tagged
`observed`.

Q19 IS WHY EVERY SESSION IS EMITTED
===================================

`aegis:Session` is written for every recognised log, whether or not any usage
survived. "Which sessions carry NO usage record?" needs the session stored
independently of its records, so that a missing measurement reads UNKNOWN
rather than aggregating as zero. A parser that emitted only sessions it could
cost would make that question unanswerable by construction.

ONE QUANTITY, NOT THE BREAKDOWN
===============================

`aegis:tokensConsumed` is total consumption: input + cache-creation +
cache-read + output. The per-harness breakdown stays unmodelled because no §D
question needs it and competency-before-classes says the finer terms wait for
a question that does. Consumption only — never remaining quota, which comes
from a different source and whose conflation with consumption cost this crew
a closed investigation (§D's own note).

Usage:
    python3 scripts/ingest_session_usage.py ~/.claude/projects/<slug> \\
        --principal strider > usage.ttl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

BASE = "http://aegis.gastown.local/cost/"
ONTOLOGY = "http://aegis.gastown.local/ontology/"


def _total(usage: dict) -> int | None:
    """Total tokens for one request, or None if the record is not countable.

    Only the top-level fields are summed. The claude `usage` object also
    carries an `iterations` list that RESTATES the same counts; adding both
    double-counts every request. A record missing the mandatory halves is not
    a zero — it is unknown, and returns None so the caller abstains.
    """
    try:
        inp = usage["input_tokens"]
        out = usage["output_tokens"]
    except (KeyError, TypeError):
        return None
    extra = 0
    for key in ("cache_creation_input_tokens", "cache_read_input_tokens"):
        value = usage.get(key, 0)
        if not isinstance(value, int):
            return None
        extra += value
    if not isinstance(inp, int) or not isinstance(out, int):
        return None
    return inp + out + extra


def read_claude(path: Path) -> tuple[str, list[dict], int] | None:
    """The claude harness layout: ~/.claude/projects/<slug>/<session>.jsonl.

    Returns (session id, requests, abstained) or None if the file is not this
    format.
    Recognition is by SHAPE — a line carrying both `sessionId` and a
    `message.usage` — not by filename, because the same suffix is used by
    every other JSONL producer on the machine, this repo's own tracker
    included.
    """
    session_id = None
    requests: dict[str, dict] = {}
    unkeyed = 0
    uncountable = 0
    recognised = False

    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or "sessionId" not in entry:
            continue
        recognised = True
        session_id = session_id or entry.get("sessionId")
        usage = (entry.get("message") or {}).get("usage")
        if not isinstance(usage, dict):
            continue
        key = entry.get("requestId")
        if not key:
            # Cannot be deduplicated against its siblings. See the module note.
            unkeyed += 1
            continue
        if key in requests:
            continue
        total = _total(usage)
        if total is None:
            uncountable += 1
            continue
        stamp = entry.get("timestamp")
        if not stamp:
            uncountable += 1
            continue
        requests[key] = {"id": key, "tokens": total, "at": stamp}

    if not recognised or not session_id:
        return None
    ordered = sorted(requests.values(), key=lambda r: (r["at"], r["id"]))
    return session_id, ordered, unkeyed + uncountable


#: format name -> (reader, provider). Adding a harness means adding a reader
#: that was verified against one of its real files — never one written from a
#: description of the format.
READERS = {"claude": (read_claude, "anthropic")}


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def emit(session_id: str, principal: str, provider: str, fmt: str,
         records: list[dict], out: list[str]) -> int:
    session = f"{BASE}session/{quote(session_id, safe='')}"
    out.append(f"<{session}>")
    out.append(f"    a <{ONTOLOGY}Session> ;")
    out.append(f'    rdfs:label "{esc(fmt)} session {esc(session_id)}" ;')
    out.append(f'    <{ONTOLOGY}sourceKind> "observed" ;')
    out.append(f"    <{ONTOLOGY}actor> <{BASE}principal/{quote(principal, safe='')}> .")
    out.append("")
    written = 0
    for record in records:
        iri = f"{session}/usage/{quote(record['id'], safe='')}"
        out.append(f"<{iri}>")
        out.append(f"    a <{ONTOLOGY}UsageRecord> ;")
        out.append(
            f'    rdfs:label "{esc(record["id"])}: {record["tokens"]} tokens" ;'
        )
        out.append(f'    <{ONTOLOGY}sourceKind> "observed" ;')
        out.append(f"    <{ONTOLOGY}inSession> <{session}> ;")
        out.append(f'    <{ONTOLOGY}provider> "{esc(provider)}" ;')
        out.append(f'    <{ONTOLOGY}tokensConsumed> {record["tokens"]} ;')
        out.append(f'    <{ONTOLOGY}observedAt> "{esc(record["at"])}" .')
        out.append("")
        written += 1
    return written


def session_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(p for p in root.rglob("*.jsonl") if p.is_file()))
        else:
            print(f"  ! {root}: no such file or directory — skipped", file=sys.stderr)
    return files


def ingest(paths: list[Path], principal: str, provider: str | None,
           out: list[str]) -> dict[str, int]:
    stats = {"files": 0, "sessions": 0, "empty": 0,
             "records": 0, "tokens": 0, "abstained": 0, "unrecognised": 0}
    for path in paths:
        stats["files"] += 1
        for fmt, (reader, default_provider) in READERS.items():
            parsed = reader(path)
            if parsed is None:
                continue
            session_id, records, abstained = parsed
            stats["sessions"] += 1
            stats["abstained"] += abstained
            written = emit(session_id, principal, provider or default_provider,
                           fmt, records, out)
            stats["records"] += written
            stats["tokens"] += sum(r["tokens"] for r in records)
            if not written:
                # Q19's population. Emitted, and counted, precisely because a
                # session with no accounting must read UNKNOWN, not zero.
                stats["empty"] += 1
            break
        else:
            stats["unrecognised"] += 1
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("roots", nargs="+", type=Path,
                    help="session log files, or directories searched for *.jsonl")
    ap.add_argument("--principal", required=True,
                    help="the crew principal whose harness wrote these logs. "
                         "REQUIRED because the harness record does not name it: "
                         "it records a session, not who the crew calls the agent "
                         "that ran it. A wrong value attributes real consumption "
                         "to the wrong principal, which Q17 and Q18 then report "
                         "with a straight face.")
    ap.add_argument("--provider",
                    help="override the provider recorded on each UsageRecord. "
                         "Defaults to the harness's own vendor. Set it when the "
                         "harness was proxied elsewhere — the on-disk record does "
                         "not distinguish that, and consumption billed by one "
                         "provider must not be reported under another's name.")
    args = ap.parse_args()

    out = ["@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .", ""]
    stats = ingest(session_files(args.roots), args.principal, args.provider, out)
    print("\n".join(out))

    # THE DENOMINATOR, on stderr, always — the same rule ingest_git_provenance
    # follows. A cost ingest that reported only what it counted would let a run
    # covering a tenth of the logs look like one covering all of them, and a
    # thin total is indistinguishable from a cheap week.
    print(f"\n{stats['sessions']} session(s) from {stats['files']} file(s): "
          f"{stats['records']} usage record(s), {stats['tokens']} token(s) "
          f"attributed to {args.principal}", file=sys.stderr)
    if stats["empty"]:
        print(f"NOTE: {stats['empty']} session(s) carried NO usage record and were "
              f"emitted anyway. That is Q19's population: they must read UNKNOWN, "
              f"never zero.", file=sys.stderr)
    if stats["abstained"]:
        print(f"NOTE: {stats['abstained']} usage entr(ies) were skipped — no "
              f"requestId to deduplicate by, or an incomplete count. The total "
              f"above is a FLOOR, not a measurement.", file=sys.stderr)
    if stats["unrecognised"]:
        print(f"NOTE: {stats['unrecognised']} file(s) matched no reader in "
              f"{sorted(READERS)} and emitted nothing. Codex rollouts land here "
              f"on purpose: no real rollout file was available to verify a reader "
              f"against, and a parser written from a format description is a "
              f"guess. Their consumption is ABSENT from the total above, not "
              f"zero.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
