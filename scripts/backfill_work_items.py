#!/usr/bin/env python3
"""Make EVERY tracker bead a WorkItem with its identifier, not only current work.

`sync_work_items.py` delivers *current* work (in progress, or assigned and
open/blocked), one record per tick, by design. Closed beads never became
WorkItems, so the grounding set covered 9% of beads, and a rule checking
bead references against it would call most real references fabricated
(aegis-jrobfn).

This fills that gap without a second mapping: every body comes from
`ingest_work_items.episode_for`, the same function the standing sync uses.
The WorkItem node is byte-identical across versions and the mutable fields
live in a versioned Observation, so re-posting a bead is a true upsert.

Coverage is recomputed from the GRAPH on every run (two single-pattern
queries; their join times out), so the tool resumes by construction and a
bead minted after the last run is simply "missing" on the next one.

Load discipline (quipu has one writer):
  * one short transaction per bead, paced by --rate;
  * a single write slower than --stop-after seconds stops the run: that is
    the writer-hold shape, and pushing on is how a store gets wedged;
  * a write whose response is lost is NOT retried in the same run. The next
    run's coverage query decides. A retry would be safe anyway (the body is
    byte-identical), but not re-posting is safer still.

    python3 scripts/backfill_work_items.py --db <beads.db> --actor tracker-workitems \\
        --source br:beads_aegis --dry-run
    python3 scripts/backfill_work_items.py --db <beads.db> --actor tracker-workitems \\
        --source br:beads_aegis --rate 3
"""
from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import planes  # noqa: E402
from ingest_work_items import BASE_NS, WorkItemError, episode_for  # noqa: E402

CLIENT = "camayoc-ingress"
IDENTIFIER_QUERY = f"SELECT ?w ?id WHERE {{ ?w <{BASE_NS}identifier> ?id }}"
WORKITEM_QUERY = f"SELECT ?w WHERE {{ ?w a ?t . FILTER(?t = <{BASE_NS}WorkItem>) }}"


def all_beads(db: Path, run=subprocess.run) -> list[dict]:
    """Every bead, any status. A truncated listing is refused, never used."""
    out = run(["br", "--db", str(db), "list", "--all", "--limit", "0", "--json"],
              check=True, capture_output=True, text=True, timeout=60)
    payload = json.loads(out.stdout)
    records = payload["issues"] if isinstance(payload, dict) else payload
    if isinstance(payload, dict) and (payload.get("has_more") is not False
                                      or payload.get("total") != len(records)):
        raise ValueError("tracker listing is incomplete; refusing to backfill from it")
    return records


def _local(term: str) -> str:
    for prefix in (BASE_NS, "aegis:"):
        if term.startswith(prefix):
            return term[len(prefix):]
    return term


#: Where a WorkItem can live: the default graph (older ingests) and the plane
#: camayoc routes observed tracker records into. A WorkItem in `crew:records`
#: is invisible to a default-graph-only query, and that is exactly why
#: tonight's beads looked absent while the standing sync was delivering them.
def graphs() -> list[str | None]:
    return [None, planes.plane_for("observed")]


def covered(post) -> set[str]:
    """Identifiers that are WorkItems NOW, in any graph they are routed to,
    behind a control."""
    wi: set[str] = set()
    ids: dict[str, set[str]] = {}
    any_rows = False
    for graph in graphs():
        scope = {"graph": graph} if graph else {}
        workitems = post("/query", {"query": WORKITEM_QUERY, **scope})
        pairs = post("/query", {"query": IDENTIFIER_QUERY, **scope})
        for name, result in (("WorkItem", workitems), ("identifier", pairs)):
            if not isinstance(result.get("rows"), list) or result.get("truncated"):
                raise ValueError(f"{name} query unproven in {graph or 'default'} (truncated or malformed)")
        any_rows = any_rows or bool(workitems["rows"])
        wi |= {_local(r["w"]) for r in workitems["rows"]}
        for r in pairs["rows"]:
            ids.setdefault(_local(r["w"]), set()).add(r["id"].strip('"'))
    if not any_rows:
        # CONTROL: a store with zero WorkItems is a broken instrument here, not
        # a reason to write 19k of them.
        raise ValueError("WorkItem control returned no rows; refusing")
    return {i for w, s in ids.items() if w in wi for i in s}


def run(records, done: set[str], post, *, actor, source, rate, stop_after,
        limit=None, dry_run=False, clock=time.monotonic, sleep=time.sleep) -> dict:
    missing = [r for r in records if r.get("id") not in done]
    missing.sort(key=lambda r: r.get("created_at", ""), reverse=True)  # newest first
    if limit is not None:
        missing = missing[:limit]
    report = {"beads": len(records), "covered_before": len(done & {r["id"] for r in records}),
              "missing": len([r for r in records if r.get("id") not in done]),
              "attempted": 0, "written": 0, "indeterminate": 0, "invalid": 0,
              "stopped": None, "dry_run": dry_run}
    gap = 1.0 / rate if rate > 0 else 0.0
    latencies: list[float] = []
    for record in missing:
        try:
            body = episode_for(record, actor=actor, source=source)
        except WorkItemError:
            report["invalid"] += 1
            continue
        if dry_run:
            report["attempted"] += 1
            continue
        report["attempted"] += 1
        started = clock()
        try:
            post("/episode", body)
            report["written"] += 1
        except (planes.PlaneError, TimeoutError, OSError) as error:
            # Lost response, 502, timeout: the write may have LANDED. Leave it
            # to the next run's coverage query; never re-post blind.
            report["indeterminate"] += 1
            report.setdefault("indeterminate_ids", []).append(record["id"])
            if "404" in str(error):
                report["stopped"] = f"no plane routing: {error}"
                break
        took = clock() - started
        latencies.append(took)
        if took > stop_after:
            report["stopped"] = (f"writer-hold rule: one write took {took:.1f}s "
                                 f"(> {stop_after}s) on {record['id']}")
            break
        if gap:
            sleep(max(0.0, gap - took))
    if latencies:
        ordered = sorted(latencies)
        report["write_s"] = {"p50": round(ordered[len(ordered) // 2], 3),
                             "p95": round(ordered[int(len(ordered) * 0.95) - 1 if len(ordered) > 1 else 0], 3),
                             "max": round(ordered[-1], 3)}
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--rate", type=float, default=3.0, help="writes per second (default 3)")
    parser.add_argument("--stop-after", type=float, default=5.0,
                        help="stop if one write takes longer than this (writer-hold rule)")
    parser.add_argument("--max", type=int, help="at most this many writes this run")
    parser.add_argument("--lock", type=Path, default=Path("/tmp/camayoc-workitem-backfill.lock"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    with args.lock.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "BUSY"}))
            return 0
        post = lambda endpoint, body: planes._post(endpoint, body, client=CLIENT)  # noqa: E731
        records = all_beads(args.db)
        done = covered(post)
        report = run(records, done, post, actor=args.actor, source=args.source, rate=args.rate,
                     stop_after=args.stop_after, limit=args.max, dry_run=args.dry_run)
        if not args.dry_run:
            after = covered(post)
            report["covered_after"] = len(after & {r["id"] for r in records})
            report["coverage_after"] = round(report["covered_after"] / max(1, len(records)), 4)
        print(json.dumps(report, sort_keys=True))
        return 3 if report["stopped"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
