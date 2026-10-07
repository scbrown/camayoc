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
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import planes  # noqa: E402
from ingest_work_items import BASE_NS, WorkItemError, episode_for, work_kind  # noqa: E402

CLIENT = "camayoc-ingress"
#: seeds' schema.org model (aegis-bqgdr3) writes schema:identifier, not the
#: legacy predicate. One query per spelling, unioned here, never a join.
IDENTIFIER_QUERIES = tuple(
    f"SELECT ?w ?id WHERE {{ ?w <{iri}> ?id }}"
    for iri in (f"{BASE_NS}identifier", "https://schema.org/identifier")
)
#: One asserted-type query per spelling of WorkItem (aegis-9dpcta): the legacy
#: class and its Quechua twin. Instance IRIs never move, only the class does, so
#: a Quechua-typed item is the SAME identifier. Reading only the legacy class
#: would call it uncovered and re-post it through /episode, which writes the
#: legacy type: a double-typed record. Two queries, unioned here, never a join.
#: schema:Action is a seed under the schema.org model (aegis-bqgdr3).
WORKITEM_TYPES = (f"{BASE_NS}WorkItem", "https://scbrown.github.io/quechua/ns#WorkItem",
                  "https://schema.org/Action")
WORKITEM_QUERIES = tuple(
    f"SELECT ?w WHERE {{ ?w a ?t . FILTER(?t = <{iri}>) }}" for iri in WORKITEM_TYPES
)
#: quipu caps one result at 10,000 rows and says so with `truncated`. The
#: crew:records plane passed 10,000 WorkItems on 2026-09-25 and every run from
#: 15:40Z refused, correctly, on a truncated answer. So both reads page.
PAGE = 5000


def paged(post, query: str, scope: dict, name: str, graph) -> list[dict]:
    """Every row of `query`, in ORDER BY pages, refusing any truncated page."""
    rows: list[dict] = []
    var = query.split()[1]  # the first projected variable, a stable sort key
    for offset in range(0, 10_000_000, PAGE):
        result = post("/query", {"query": f"{query} ORDER BY {var} LIMIT {PAGE} OFFSET {offset}", **scope})
        if not isinstance(result.get("rows"), list) or result.get("truncated"):
            raise ValueError(f"{name} query unproven in {graph or 'default'} (truncated or malformed)")
        rows += result["rows"]
        if len(result["rows"]) < PAGE:
            return rows
    raise ValueError(f"{name} query did not end in {graph or 'default'}")


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


#: The seeds board graph(s) the tracker writes once a board is cut over to
#: seeds (aegis-wmeqa6 N1). seeds keeps each board in its OWN named graph, so a
#: seed is invisible to the default graph and to crew:records; after the flip,
#: without this the backfill would call every seed uncovered and re-post it as a
#: legacy WorkItem. Read explicitly by name, never by widening the default graph:
#: that would pull the quarantined crew:inferred plane into every read.
#:
#: OFF until the flip (aegis-67p0lj). Before it the board is a MIRROR of br, so
#: reading it re-reads beads the backfill already has, for zero coverage gain,
#: and it is a 730k-triple graph paged per store per tick. Turn it on at the flip
#: with CAMAYOC_BOARD_GRAPHS=<iri>[,<iri>...] (or --board-graph).
BOARD_GRAPHS_ENV = "CAMAYOC_BOARD_GRAPHS"


def default_board_graphs(environ=os.environ) -> tuple[str, ...]:
    return tuple(g.strip() for g in environ.get(BOARD_GRAPHS_ENV, "").split(",") if g.strip())


DEFAULT_BOARD_GRAPHS: tuple[str, ...] = ()


#: Where a WorkItem can live: the default graph (older ingests), the plane
#: camayoc routes observed tracker records into, and the seeds board graph(s).
#: A WorkItem in `crew:records` is invisible to a default-graph-only query, and
#: that is exactly why tonight's beads looked absent while the standing sync was
#: delivering them. A board graph is the same shape of blindness one plane over.
def graphs(board_graphs=DEFAULT_BOARD_GRAPHS) -> list[str | None]:
    inferred = planes.plane_for("inferred")
    if inferred in board_graphs:
        # Quarantined guesswork must never count as coverage: a bead "covered"
        # only by an inference would never be written as the record it is.
        raise ValueError(f"{inferred} is the inferred plane, not a board graph; refusing")
    out: list[str | None] = [None, planes.plane_for("observed")]
    return out + [g for g in board_graphs if g and g not in out]


def covered(post, board_graphs=DEFAULT_BOARD_GRAPHS) -> set[str]:
    """Identifiers that are WorkItems NOW, in any graph they are routed to,
    behind a control."""
    wi: set[str] = set()
    ids: dict[str, set[str]] = {}
    any_rows = False
    for graph in graphs(board_graphs):
        scope = {"graph": graph} if graph else {}
        workitems = [row for query in WORKITEM_QUERIES
                     for row in paged(post, query, scope, "WorkItem", graph)]
        pairs = [row for query in IDENTIFIER_QUERIES
                 for row in paged(post, query, scope, "identifier", graph)]
        any_rows = any_rows or bool(workitems)
        wi |= {_local(r["w"]) for r in workitems}
        for r in pairs:
            ids.setdefault(_local(r["w"]), set()).add(r["id"].strip('"'))
    if not any_rows:
        # CONTROL: a store with zero WorkItems is a broken instrument here, not
        # a reason to write 19k of them.
        raise ValueError("WorkItem control returned no rows; refusing")
    return {i for w, s in ids.items() if w in wi for i in s}


#: One coverage scan per tick, shared by every store's run (aegis-67p0lj). The
#: wrapper runs this once per store, and coverage is GLOBAL (every WorkItem in
#: every graph), so nine stores scanned the same ~24k identifiers nine times a
#: tick to check a few hundred beads, holding the quipu store for about half of
#: each tick. A stale set can only re-post a covered bead (an idempotent upsert)
#: or leave a missing one for the next run, so a short max age is safe.
COVERAGE_MAX_AGE = 300.0


def shared_covered(post, board_graphs, cache: Path | None, max_age: float,
                   now=time.time, refresh: bool = False) -> tuple[set[str], str, float]:
    """(coverage, source, scanned_at): the cached set if fresh for this scope, else a scan.

    `scanned_at` is when the underlying FULL scan ran, which is what the max age
    bounds. A cache reused or extended by confirmation keeps that time.
    """
    scope = sorted(board_graphs)
    if cache is not None and max_age > 0 and not refresh:
        try:
            data = json.loads(cache.read_text())
            fresh = now() - float(data["at"]) <= max_age
            if fresh and data["scope"] == scope and data["ids"]:
                return set(data["ids"]), "cache", float(data["at"])
        except (OSError, ValueError, KeyError, TypeError):
            pass  # unreadable or foreign cache: scan, never trust it
    scanned_at = now()
    found = covered(post, board_graphs)
    remember_coverage(cache, board_graphs, found, max_age, scanned_at)
    return found, "scan", scanned_at


def remember_coverage(cache: Path | None, board_graphs, ids: set[str], max_age: float,
                      scanned_at: float) -> None:
    """Persist coverage stamped with its FULL scan's time, never the time of writing:
    confirmation extends a set, it does not make the rest of it fresher."""
    if cache is None or max_age <= 0:
        return
    # Per-process temp name: two stores refreshing at once must not share one.
    tmp = cache.with_name(f"{cache.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"at": scanned_at, "scope": sorted(board_graphs), "ids": sorted(ids)}))
    tmp.replace(cache)


def confirmed(post, ids, board_graphs, chunk: int = 200) -> set[str]:
    """Of `ids`, those that now have an identifier in any coverage graph.

    After a write, re-scanning all ~30k identifiers to learn about the few this
    run wrote held the quipu store for most of a tick (aegis-67p0lj, 19:03Z: 26
    written, then a full re-read). Ask only about those ids: one bounded
    FILTER(... IN ...) per graph and spelling, still a READ, never the write
    response taken on trust.
    """
    found: set[str] = set()
    wanted = sorted(set(ids))
    for graph in graphs(board_graphs):
        scope = {"graph": graph} if graph else {}
        for start in range(0, len(wanted), chunk):
            batch = wanted[start:start + chunk]
            values = ", ".join(json.dumps(i) for i in batch)
            for query in IDENTIFIER_QUERIES:
                result = post("/query", {"query": f"{query[:-2]} . FILTER(?id IN ({values})) }}",
                                         **scope})
                if not isinstance(result.get("rows"), list) or result.get("truncated"):
                    raise ValueError(f"confirmation query unproven in {graph or 'default'}")
                found |= {r["id"].strip('"') for r in result["rows"]}
    return found & set(wanted)


def deps_key(record: dict) -> str:
    """The dependency set a write projects, in a stable comparable form."""
    return ",".join(sorted({str(x) for x in (record.get("blocked_on") or []) if str(x).strip()}))


def run(records, done: set[str], post, *, actor, source, rate, stop_after,
        limit=None, dry_run=False, clock=time.monotonic, sleep=time.sleep,
        max_slow=2, backoff=60.0, projected: dict | None = None) -> dict:
    # A covered bead with dependencies is re-projected too: its Observation must
    # carry observedBlockedOn (aegis-3b3nrb). But only when its dependency set
    # differs from the one this store last wrote successfully (`projected`,
    # id -> deps_key). Re-posting every covered bead with dependencies on every
    # tick was a graph no-op and NOT a server no-op: ~2.2 s of writer time each,
    # ~10.7k a day, 43% of quipu's wall time, and at 486 such beads in one
    # store it filled --max, so missing beads were never reached (aegis-ima1hq).
    # MISSING beads go first for the same reason: a re-projection must never
    # starve coverage.
    # A record whose dependencies could not be read is SKIPPED, never written
    # without them: that would record "blocks on nothing" (see attach_blocked_on).
    projected = {} if projected is None else projected
    newest_first = lambda r: r.get("created_at", "")  # noqa: E731
    eligible = [r for r in records if not r.get("dep_unknown")]
    missing = sorted((r for r in eligible if r.get("id") not in done), key=newest_first, reverse=True)
    stale = sorted((r for r in eligible if r.get("id") in done and r.get("blocked_on")
                    and projected.get(r["id"]) != deps_key(r)), key=newest_first, reverse=True)
    # Planned work (aegis-qx96wr) is re-projected ONCE to gain its kind and idle
    # limit, so an unassigned open Design/Plan/Directive -- which the standing sync
    # lane never follows -- is still findable and can lapse. Not closed ones: they
    # carry no live obligation, and re-posting them would be a burst for nothing.
    # Keyed "kind:<id>" in the same map; dependency keys are bare ids, so no clash.
    stale_ids = {r["id"] for r in stale}
    kinded = sorted((r for r in eligible if r.get("id") in done and r["id"] not in stale_ids
                     and r.get("status") != "closed" and work_kind(r)
                     and projected.get("kind:" + r["id"]) != work_kind(r)),
                    key=newest_first, reverse=True)
    queue = missing + stale + kinded
    if limit is not None:
        queue = queue[:limit]
    report = {"beads": len(records), "covered_before": len(done & {r["id"] for r in records}),
              "missing": len([r for r in records if r.get("id") not in done]),
              "reproject_pending": len(stale),
              "kind_pending": len(kinded),
              "attempted": 0, "written": 0, "indeterminate": 0, "invalid": 0,
              "stopped": None, "dry_run": dry_run}
    gap = 1.0 / rate if rate > 0 else 0.0
    latencies: list[float] = []
    slow_streak = 0
    for record in queue:
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
            report.setdefault("written_ids", []).append(record["id"])
            if record.get("blocked_on"):
                projected[record["id"]] = deps_key(record)
            if work_kind(record):
                projected["kind:" + record["id"]] = work_kind(record)
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
            # One slow write is a busy writer: back off and let it drain. Two in a
            # row is the shape of a stuck one: stop, and the next tick resumes.
            # (Measured 2026-09-24: isolated ~15 s stalls recur on quipu, so
            # stopping on the FIRST one held the backfill to ~18 writes a run.)
            slow_streak += 1
            report["slow_writes"] = report.get("slow_writes", 0) + 1
            if slow_streak >= max_slow:
                report["stopped"] = (f"writer-hold rule: {slow_streak} consecutive writes over "
                                     f"{stop_after}s, last {took:.1f}s on {record['id']}")
                break
            sleep(backoff)
            continue
        slow_streak = 0
        if gap:
            sleep(max(0.0, gap - took))
    if latencies:
        ordered = sorted(latencies)
        report["write_s"] = {"p50": round(ordered[len(ordered) // 2], 3),
                             "p95": round(ordered[int(len(ordered) * 0.95) - 1 if len(ordered) > 1 else 0], 3),
                             "max": round(ordered[-1], 3)}
    return report


def load_projected(path: Path) -> dict:
    """The last-written dependency sets. Unreadable means EMPTY: the safe
    direction is one extra re-projection of each bead, never a skipped one."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def load_deps_cache(path: Path) -> dict:
    """id -> [updated_at, blocked_on], keeping only well-formed entries. Missing
    or unreadable means EMPTY: that costs a full re-read, never a wrong set."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items()
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)
            and isinstance(v[1], list) and all(isinstance(x, str) for x in v[1])}


def save_projected(path: Path, projected: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(projected, sort_keys=True) + "\n")
    tmp.replace(path)


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
    parser.add_argument("--state", type=Path,
                        help="dependency sets last written per bead (default: beside --lock)")
    parser.add_argument("--board-graph", action="append", dest="board_graphs", metavar="IRI",
                        help="seeds board graph to read coverage from; repeatable. Default: none, "
                             f"or the comma list in ${BOARD_GRAPHS_ENV} (off until the flip)")
    parser.add_argument("--no-board-graphs", action="store_true",
                        help="read no board graph (default graph and crew:records only)")
    parser.add_argument("--coverage-cache", type=Path,
                        help="coverage shared across stores' runs (default: beside --lock, one "
                             "file for every store)")
    parser.add_argument("--coverage-max-age", type=float, default=COVERAGE_MAX_AGE,
                        help=f"seconds a shared coverage scan is reused (default {COVERAGE_MAX_AGE:g}; "
                             "0 scans every run)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.no_board_graphs and args.board_graphs:
        parser.error("--board-graph and --no-board-graphs are mutually exclusive")
    board_graphs = (() if args.no_board_graphs
                    else tuple(args.board_graphs) if args.board_graphs else default_board_graphs())
    state = args.state or args.lock.with_suffix(".projected.json")
    cache = None if args.dry_run else (
        args.coverage_cache or args.lock.parent / "camayoc-workitem-coverage.json")

    with args.lock.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "BUSY"}))
            return 0
        post = lambda endpoint, body: planes._post(endpoint, body, client=CLIENT)  # noqa: E731
        records = all_beads(args.db)
        # Dependencies are read per bead (one `br dep list` each). Uncached that
        # was ~1,000 reads a tick on the aegis store, a br read alive in 300 of
        # 300 sampled seconds and contending with the crew for the store lock
        # (aegis-ky3zpa). Reuse the standing sync's cache: re-read only beads
        # whose updated_at moved, since br bumps it on dep add/remove.
        from sync_work_items import attach_deps
        deps_path = args.lock.with_suffix(".deps.json")
        deps_cache = load_deps_cache(deps_path)
        attach_deps(records, args.db, deps_cache)
        dep_unknown = [r["id"] for r in records if r.get("dep_unknown")]
        if not args.dry_run:
            live = {r["id"] for r in records}
            save_projected(deps_path, {k: v for k, v in deps_cache.items() if k in live})
        done, done_source, scanned_at = shared_covered(post, board_graphs, cache,
                                                       args.coverage_max_age)
        projected = load_projected(state)
        report = run(records, done, post, actor=args.actor, source=args.source, rate=args.rate,
                     stop_after=args.stop_after, limit=args.max, dry_run=args.dry_run,
                     projected=projected)
        if not args.dry_run:
            save_projected(state, projected)
        if dep_unknown:
            report["dep_unknown"] = len(dep_unknown)
            report["dep_unknown_ids"] = dep_unknown[:20]
        if not args.dry_run:
            # Re-read coverage only if this run attempted a write. With nothing
            # attempted it cannot have changed, and the re-read is a full
            # coverage scan of every graph: one per store per tick, the larger
            # half of the backfill's request budget (aegis-wmeqa6). An attempted
            # write, landed or indeterminate, always re-reads.
            if report["attempted"]:
                touched = report.get("written_ids", []) + report.get("indeterminate_ids", [])
                after = done | confirmed(post, touched, board_graphs)
                report["covered_after_source"] = "confirmed"
                remember_coverage(cache, board_graphs, after, args.coverage_max_age, scanned_at)
            else:
                after = done
                report["covered_after_source"] = "unchanged"
            report["covered_after"] = len(after & {r["id"] for r in records})
            report["coverage_after"] = round(report["covered_after"] / max(1, len(records)), 4)
        report["covered_before_source"] = done_source
        report.pop("written_ids", None)  # an internal hand-off, not a report field
        print(json.dumps(report, sort_keys=True))
        return 3 if report["stopped"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
