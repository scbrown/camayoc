#!/usr/bin/env python3
"""Link every archived agent transcript to its Session in the observed plane.

    Principal  <--aegis:actor--  Session  --aegis:transcript-->  Artifact
                                     |
                                     +--aegis:declaredWorkItem-->  WorkItem   (st task boundaries)
                                                                  aegis:reference  "garage-hla:hla/agent-transcripts/<agent>/<file>"
                                                                  aegis:contentSha256

THE GAP THIS CLOSES (aegis-9lri74)
==================================

`aegis:Session` was only ever written by the cost path (publish_work_cost.py
inside the per-minute `st cost --sync`), which samples ACTIVE sessions. A
session that finished between samples never got a node. Measured 2026-09-25:
338 local session logs modified since 09-02, 7 with a Session node (~2%).

The transcript archive already holds every finished session: st-history-corpus
projects each harness log to `<corpus>/<agent>/<id>.md` and the publication
cron mirrors that tree to `garage-hla:hla/agent-transcripts/` (rsync, then
rclone sync, so the object key IS the relative path). This producer reads the
same local tree, so the pointer it writes names the published object.

A POINTER, NEVER THE CONTENT
============================

Only the frontmatter is parsed. The body is hashed and never read into a fact:
the Artifact carries the object key and the sha256 of the bytes published,
so a reader can fetch and verify it with the archive's own credentials.

SHARED TRIPLES WITH THE COST PRODUCER
=====================================

Both producers write `<session> a aegis:Session`, `aegis:actor`, `aegis:sourceKind`
and the label `"<harness> session <id>"` (the governed Session shape requires
exactly one label, so it must be the cost producer's BYTE-IDENTICAL string). quipu
retracts a replaced snapshot by logical (e, a, v), so a triple shared by two
sources survives only because EVERY replacing producer re-emits it in the
same transaction. Both do, on every snapshot. Nothing else is shared: every
transcript fact lives on the Artifact or on a predicate only this producer
writes.

DECLARED WORK ITEMS, NOT PROVEN ONES
====================================

`st agent stats --begin-task <bead>` records a paired, session-local task
boundary in st's stats.sqlite (`task_contexts`). Each paired start becomes
`aegis:declaredWorkItem`. The name is deliberate: st itself says a scope is a
declaration, not proof that it covers every action. A session with no
declaration gets no edge, which reads as UNKNOWN, never as "worked on nothing".

QUIESCENCE
==========

A live session's projection changes every corpus cycle. A session is linked
once its record has been unchanged for --quiet-minutes; a resumed session
changes digest and its snapshot is replaced, never duplicated.

Usage:
    python3 scripts/ingest_transcript_sessions.py --corpus <dir> --state <f>            # dry run
    python3 scripts/ingest_transcript_sessions.py --corpus <dir> --state <f> --post
    python3 scripts/ingest_transcript_sessions.py --corpus <dir> --state <f> --check-liveness
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import planes  # noqa: E402
from ingest_session_usage import BASE, ONTOLOGY, esc  # noqa: E402

REMOTE = "garage-hla:hla/agent-transcripts"
SCHEMA = "agent-transcript/v1"
AGENT = re.compile(r"[a-z][a-z0-9_]{0,31}")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
CLIENT = "camayoc-transcripts"
SHAPES = Path(__file__).resolve().parents[1] / "shapes/session-transcript.shapes.ttl"


def frontmatter(path: Path) -> dict | None:
    with path.open("rb") as handle:
        head = handle.read(2048).decode(errors="replace")
    if not head.startswith("---\n") or "\n---\n" not in head[4:]:
        return None
    block = head[4:].split("\n---\n", 1)[0]
    return dict(re.findall(r"^(\w+): (.*)$", block, re.M))


def session_id(meta: dict) -> str | None:
    """The id the harness itself records, so both producers mint one IRI.

    claude: the corpus id IS the log's sessionId. codex: the corpus id is the
    rollout stem, whose trailing UUID is session_meta.id — the value
    ingest_session_usage.read_codex keys the cost Session by.
    """
    raw = meta.get("id", "")
    if meta.get("harness") == "claude":
        return raw if UUID.fullmatch(raw) else None
    if meta.get("harness") == "codex" and raw.startswith("rollout-"):
        found = UUID.findall(raw)
        return found[-1] if found else None
    return None


def excluded(path: Path) -> set[str]:
    """The publisher's own rsync exclude list, as corpus-relative paths.

    A file on it has NO Garage object, so a pointer to it would name nothing.
    Its absence is refused rather than read as "nothing excluded": this
    producer cannot tell published from unpublished without it.
    """
    return {line.strip().lstrip("/") for line in path.read_text().splitlines() if line.strip()}


TASK = re.compile(r"[A-Za-z][A-Za-z0-9_]*-[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")


def declared_tasks(stats_db: Path | None) -> dict[str, list[str]]:
    """Paired task boundaries per session, read-only. None means not asked."""
    if stats_db is None:
        return {}
    with sqlite3.connect(f"file:{stats_db}?mode=ro", uri=True) as conn:
        rows = conn.execute("SELECT session, task FROM task_contexts WHERE paired_start = 1").fetchall()
    tasks: dict[str, set[str]] = {}
    for session, task in rows:
        if TASK.fullmatch(task or ""):
            tasks.setdefault(session, set()).add(task)
    return {session: sorted(found) for session, found in tasks.items()}


def digest(record: dict) -> str:
    # Transcript-only sessions keep the bare sha, so adding declarations
    # re-publishes only the sessions that have them.
    tasks = record.get("tasks") or []
    return record["sha256"] + (":" + ",".join(tasks) if tasks else "")


def scan(corpus: Path, quiet_seconds: float, now: float,
         unpublished: set[str] = frozenset(),
         tasks: dict[str, list[str]] | None = None) -> tuple[list[dict], dict]:
    records, stats = [], {"files": 0, "linked": 0, "active": 0, "skipped": {}}

    def skip(reason):
        stats["skipped"][reason] = stats["skipped"].get(reason, 0) + 1

    for path in sorted(corpus.glob("*/*.md")):
        stats["files"] += 1
        meta = frontmatter(path)
        if not meta or meta.get("schema") != SCHEMA:
            skip("not agent-transcript/v1")
            continue
        agent = path.parent.name
        if f"{agent}/{path.name}" in unpublished:
            skip("excluded from publication")
            continue
        if meta.get("agent") != agent or not AGENT.fullmatch(agent):
            # A scratch directory is not a crew principal; attributing its
            # session to one would be worse than leaving it unlinked.
            skip("agent not a crew principal")
            continue
        sid = session_id(meta)
        if not sid:
            skip("no harness session id")
            continue
        if now - path.stat().st_mtime < quiet_seconds:
            stats["active"] += 1
            continue
        data = path.read_bytes()
        records.append({
            "session": sid, "agent": agent, "harness": meta["harness"],
            "at": meta.get("timestamp", ""), "key": f"{REMOTE}/{agent}/{path.name}",
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "tasks": (tasks or {}).get(sid, []),
        })
        stats["linked"] += 1
    return records, stats


def iris(record: dict) -> tuple[str, str]:
    session = f"{BASE}session/{quote(record['session'], safe='')}"
    return session, f"{session}/transcript"


def turtle(record: dict) -> str:
    session, artifact = iris(record)
    o = ONTOLOGY
    out = [
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
        f"<{session}> a <{o}Session> ;",
        # Same string as ingest_session_usage.emit: one shared triple, not two labels.
        f'    rdfs:label "{esc(record["harness"])} session {esc(record["session"])}" ;',
        f'    <{o}sourceKind> "observed" ;',
        f"    <{o}actor> <{BASE}principal/{quote(record['agent'], safe='')}> ;",
        f'    <{o}sessionHarness> "{esc(record["harness"])}" ;',
        f"    <{o}transcript> <{artifact}> .",
        "",
        f"<{artifact}> a <{o}Artifact> ;",
        f'    rdfs:label "{esc(record["harness"])} transcript {esc(record["session"])} ({esc(record["agent"])})" ;',
        f'    <{o}reference> "{esc(record["key"])}" ;',
        f'    <{o}contentSha256> "{record["sha256"]}" ;',
        f"    <{o}contentBytes> {record['bytes']} ;",
        f'    <{o}sourceKind> "observed" ;',
        f"    <{o}transcriptOf> <{session}> .",
    ]
    for task in record.get("tasks") or []:
        out.append(f"<{session}> <{o}declaredWorkItem> <{o}{task}> .")
    if record["at"]:
        out.append(f'<{session}> <{o}lastActivityAt> "{esc(record["at"])}"^^xsd:dateTime .')
    return "\n".join(out) + "\n"


def body(record: dict, actor: str) -> dict:
    snapshot = f"camayoc-session-transcript:{record['harness']}:{record['session']}"
    return {"turtle": turtle(record), "actor": actor, "source": snapshot,
            "graph": planes.plane_for("observed"), "replace_snapshot": True,
            "snapshot": snapshot, "shapes": SHAPES.read_text()}


def query(sparql: str) -> list:
    rows = planes._post("/query", {"query": sparql, "graph": planes.plane_for("observed")},
                        client=CLIENT).get("rows")
    if not isinstance(rows, list):
        raise ValueError("INDETERMINATE: query returned no rows field")
    return rows


def read_back(record: dict) -> bool:
    _, artifact = iris(record)
    rows = query(f'SELECT ?h WHERE {{ <{artifact}> <{ONTOLOGY}contentSha256> ?h }}')
    return any(str(r.get("h", "")).strip('"') == record["sha256"] for r in rows)


def publish(records: list[dict], actor: str, state_path: Path, limit: int) -> dict:
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    marker = state_path.with_suffix(".pending.json")
    if marker.exists():
        # The previous write's outcome is unknown. Never blind-retry: an
        # operator reconciles the named snapshot by read-back first.
        raise ValueError(f"previous graph write indeterminate; reconcile {marker} before retry")
    pending = [r for r in records if state.get(r["session"]) != digest(r)]
    receipt = {"pending": len(pending), "posted": 0, "tx": []}
    for record in pending[:limit]:
        payload = body(record, actor)
        marker.write_text(json.dumps({"session": record["session"], "sha256": record["sha256"]}))
        started = time.monotonic()
        response = planes._post("/knot", payload, client=CLIENT)
        if response.get("conforms") is False:
            marker.unlink()  # an explicit refusal wrote nothing: determinate
            raise ValueError(f"graph refused transcript snapshot for {record['session']}: {response}")
        if not response.get("tx_id"):
            raise ValueError(f"graph refused transcript snapshot for {record['session']}: {response}")
        if not read_back(record):
            raise ValueError(f"snapshot accepted but read-back unproven for {record['session']}")
        state[record["session"]] = digest(record)
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, sort_keys=True))
        temporary.replace(state_path)
        marker.unlink()
        receipt["posted"] += 1
        receipt["tx"].append(response["tx_id"])
        time.sleep(max(0.0, 1.0 - (time.monotonic() - started)))
    receipt["remaining"] = len(pending) - receipt["posted"]
    return receipt


def liveness(records: list[dict], lag_seconds: float, now: float) -> tuple[int, str]:
    """OUTPUT, not process-up: is the newest due transcript linked in the graph?

    0 linked, 1 stale (a due transcript is absent), 2 UNKNOWN (control failed
    or nothing is due). A process probe cannot see the failure this exists
    for: the cost path stayed up while finished sessions never got a node.
    """
    control = query(f"SELECT ?s WHERE {{ ?s a ?t . FILTER(?t = <{ONTOLOGY}Session>) }} LIMIT 1")
    if not control:
        return 2, "UNKNOWN: control query found no Session in the observed plane"
    due = [r for r in records if r["at"] and
           now - datetime.datetime.fromisoformat(r["at"].replace("Z", "+00:00")).timestamp() >= lag_seconds]
    if not due:
        return 2, "UNKNOWN: no transcript old enough to be due"
    newest = max(due, key=lambda r: r["at"])
    _, artifact = iris(newest)
    rows = query(f'SELECT ?h WHERE {{ <{artifact}> <{ONTOLOGY}contentSha256> ?h }}')
    if not rows:
        return 1, f"STALE: newest due transcript {newest['key']} ({newest['at']}) has no Artifact"
    return 0, f"LIVE: newest due transcript {newest['key']} ({newest['at']}) is linked"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--state", type=Path, required=True)
    ap.add_argument("--exclude-file", type=Path,
                    default=Path.home() / ".local/state/aegis/snapshot-publication/exclude.txt",
                    help="the publication gate's rsync exclude list (required to exist)")
    ap.add_argument("--stats-db", type=Path,
                    help="st stats.sqlite; its paired task boundaries become declaredWorkItem edges")
    ap.add_argument("--actor", default="camayoc-transcripts")
    ap.add_argument("--quiet-minutes", type=float, default=60)
    ap.add_argument("--limit", type=int, default=40,
                    help="snapshots per run; a backfill is partitioned across runs")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--post", action="store_true")
    mode.add_argument("--check-liveness", action="store_true")
    ap.add_argument("--lag-minutes", type=float, default=180,
                    help="liveness: a transcript older than this must be linked")
    args = ap.parse_args()
    now = time.time()
    try:
        records, stats = scan(args.corpus, args.quiet_minutes * 60, now,
                              excluded(args.exclude_file), declared_tasks(args.stats_db))
        # THE DENOMINATOR, always: a run that linked a tenth of the archive
        # must not read like one that linked all of it.
        print(json.dumps({"scan": stats}), file=sys.stderr)
        if args.check_liveness:
            code, message = liveness(records, args.lag_minutes * 60, now)
            print(message)
            return code
        if args.post:
            print(json.dumps(publish(records, args.actor, args.state, args.limit), sort_keys=True))
            return 0
        for record in records[: args.limit]:
            print(turtle(record))
        return 0
    except (OSError, ValueError, planes.PlaneError) as exc:
        print(f"transcript linkage UNKNOWN: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
