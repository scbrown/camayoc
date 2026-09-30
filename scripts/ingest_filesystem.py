#!/usr/bin/env python3
"""Summarise filesystem exports as governed FileCollections, one snapshot per export.

The question this answers is "where is <thing> on the NAS" without crawling the
NAS: which export, which folder, and which folder holds any ``.z64`` file. The
graph gets one ``NFSExport`` per configured export and one ``FileCollection``
per folder down to a per-export depth. Each collection carries its WHOLE
SUBTREE's file count, byte count, newest mtime and extensions, so a query at
the top level still finds a file three folders down.

This is tier A of the design: folder aggregates only, never one node per file.

Behaviour:

* **Read-only.** The crawl uses ``os.scandir`` and ``lstat`` only. It opens no
  file, follows no symlink, and writes nothing under a crawled root.
* **Crawl first, write after.** Every export is crawled and its episode built
  before the first request reaches the store. Without ``--post`` nothing is
  written anywhere except ``--out``.
* **One keyed snapshot per export** (``replace_snapshot``). A folder that
  disappears is retracted, and a re-run over an unchanged tree carries
  byte-identical content. The episode holds no crawl timestamp for exactly
  that reason.
* **An empty or unmounted root is a refusal, not an empty snapshot.** An
  empty replace would retract every collection of that export. The same
  applies to a crawl that shrinks too far, and to an unreadable subtree
  (which would produce undercounts), unless ``--allow-errors`` is given.
* **Writer gates** (the store owner's conditions for this producer). A
  Prometheus probe of the store's memory skips the run at ``--skip-at`` and
  aborts between snapshots at ``--abort-at``. Snapshots are written
  sequentially at least ``MIN_PACE_S`` apart. The store's ``/version`` must
  not change during the run, i.e. never during a deploy. A probe that cannot
  answer is not a pass: the run does not write.

Exit codes: 0 done · 1 error or refusal · 2 a gate could not be evaluated
(nothing written) · 3 skipped, store memory at or above ``--skip-at`` (nothing
written) · 4 aborted mid-run (the snapshots written so far are reported).

The export table is a JSON file (``--config``), never built in, so no host or
path is hardcoded here::

    {"host": "nas", "exports": [
      {"path": "/pool/media", "mount": "/mnt/nas/media", "depth": 2,
       "description": "nas:/pool/media - the media union"},
      {"path": "/pool/raw", "mount": null, "reference_only": false,
       "description": "raw branch, covered by nas:/pool/media"}]}

* ``mount: null`` models the export without crawling it: a raw branch whose
  contents a union already covers, so they are not counted twice.
* ``reference_only: true`` means the export entity already exists in the
  graph, minted by another producer. It is linked to, never re-emitted, so
  this producer does not append a second label to it.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import hashlib
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import planes

SOURCE_KIND = "observed"
BASE_NS = "http://aegis.gastown.local/ontology/"
EXT_RE = re.compile(r"^\.[a-z0-9_+-]{1,16}$")
NO_EXT = "(none)"
OTHER_EXT = "(other)"
EXT_SUMMARY_TOP = 24
MIN_PACE_S = 30.0
DEFAULT_SKIP_AT = 4.0e9
DEFAULT_ABORT_AT = 5.0e9
DEFAULT_MAX_SHRINK = 0.5

PROM_URL_ENV = "CAMAYOC_PROM_URL"
PROM_PASSWORD_FILE_ENV = "CAMAYOC_PROM_PASSWORD_FILE"
MEMORY_QUERY_ENV = "CAMAYOC_STORE_MEMORY_QUERY"

EXIT_OK, EXIT_ERROR, EXIT_UNKNOWN, EXIT_SKIPPED, EXIT_ABORTED = 0, 1, 2, 3, 4


class FsExportError(RuntimeError):
    """A refusal: the crawl or its configuration cannot be written safely."""


class GateUnknown(RuntimeError):
    """A gate could not be evaluated. Never read as a pass."""


def sanitize(name: str) -> str:
    """Quipu's episode-name to IRI-local rule, so linked names land on the same IRI."""
    return "".join(c if c.isascii() and (c.isalnum() or c in "-_.") else "_" for c in name)


@dataclasses.dataclass
class Agg:
    files: int = 0
    bytes: int = 0
    newest: float | None = None
    exts: Counter = dataclasses.field(default_factory=Counter)

    def add_file(self, name: str, size: int, mtime: float) -> None:
        self.files += 1
        self.bytes += size
        if self.newest is None or mtime > self.newest:
            self.newest = mtime
        self.exts[extension_of(name)] += 1

    def merge(self, other: "Agg") -> None:
        self.files += other.files
        self.bytes += other.bytes
        if other.newest is not None and (self.newest is None or other.newest > self.newest):
            self.newest = other.newest
        self.exts.update(other.exts)


def extension_of(name: str) -> str:
    """Lower-cased extension with its dot; dotfiles and bare names have none."""
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        return NO_EXT
    ext = "." + ext.lower()
    return ext if EXT_RE.match(ext) else OTHER_EXT


@dataclasses.dataclass
class Crawl:
    collections: dict[str, Agg]          # relpath ("" = root) -> subtree aggregate
    errors: list[str]
    dirs_seen: int = 0


def crawl(root: str, depth: int) -> Crawl:
    """Aggregate every folder down to `depth` (root is depth 0). Read-only."""
    collections: dict[str, Agg] = {}
    errors: list[str] = []
    counter = [0]

    def walk(path: str, rel: str, level: int) -> Agg:
        counter[0] += 1
        agg = Agg()
        try:
            it = os.scandir(path)
        except OSError as e:
            errors.append(f"{rel or '.'}: {e.strerror or e}")
            return agg
        subdirs = []
        with it:
            for entry in it:
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError as e:
                    errors.append(f"{os.path.join(rel, entry.name)}: {e.strerror or e}")
                    continue
                if stat.S_ISDIR(st.st_mode):
                    subdirs.append(entry.name)
                elif stat.S_ISREG(st.st_mode):
                    agg.add_file(entry.name, st.st_size, st.st_mtime)
                # symlinks, sockets, devices: not files of this export
        for name in sorted(subdirs):
            child_rel = f"{rel}/{name}" if rel else name
            agg.merge(walk(os.path.join(path, name), child_rel, level + 1))
        if level <= depth:
            collections[rel] = agg
        return agg

    walk(root, "", 0)
    return Crawl(collections=collections, errors=errors, dirs_seen=counter[0])


def mtime_z(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ext_summary(exts: Counter) -> str:
    ranked = sorted(exts.items(), key=lambda kv: (-kv[1], kv[0]))
    head = " ".join(f"{e}={n}" for e, n in ranked[:EXT_SUMMARY_TOP])
    rest = len(ranked) - EXT_SUMMARY_TOP
    return head + (f" +{rest} more" if rest > 0 else "")


def export_entity(host: str, path: str) -> str:
    return sanitize(f"{host}:{path}")


def collection_name(export_ent: str, rel: str) -> str:
    """Stable, safe and still readable: slug of the path plus a digest of it."""
    digest = hashlib.sha256(f"{export_ent}\0{rel}".encode()).hexdigest()[:8]
    slug = sanitize(rel)[:48].strip("_.-") or "root"
    return f"fc-{export_ent}-{slug}-{digest}"


def snapshot_key(host: str, path: str) -> str:
    return f"fs-export:{host}:{path}"


def episode_for(host: str, export: dict, result: Crawl | None, *, actor: str) -> dict:
    """The keyed snapshot for one export. Deterministic for an unchanged tree."""
    path = export["path"]
    ent = export_entity(host, path)
    nodes, edges = [], []
    if not export.get("reference_only"):
        node = {"name": ent, "type": "NFSExport", "properties": {"sourceKind": SOURCE_KIND}}
        if export.get("description"):
            node["description"] = export["description"]
        nodes.append(node)
    for rel in sorted((result.collections if result else {})):
        agg = result.collections[rel]
        name = collection_name(ent, rel)
        props: dict = {
            "sourceKind": SOURCE_KIND,
            "relativePath": rel or ".",
            "fileCount": agg.files,
            "byteCount": agg.bytes,
            "hasExtension": sorted(e for e in agg.exts if EXT_RE.match(e)),
            "extensionCounts": ext_summary(agg.exts),
        }
        if agg.newest is not None:
            props["newestMtime"] = mtime_z(agg.newest)
        nodes.append({
            "name": name,
            "type": "FileCollection",
            "description": f"{host}:{path}" + (f"/{rel}" if rel else ""),
            "properties": props,
        })
        edges.append({"source": name, "target": ent, "relation": "inExport"})
        if rel:
            parent = rel.rpartition("/")[0]
            edges.append({"source": name, "target": collection_name(ent, parent),
                          "relation": "parentCollection"})
    return {
        "name": snapshot_key(host, path),
        "graph": planes.plane_for(SOURCE_KIND),
        "episode_body": f"Filesystem snapshot of {host}:{path}: "
                        f"{max(len(nodes) - (0 if export.get('reference_only') else 1), 0)} collections",
        "source": f"camayoc:ingest_filesystem:{host}:{path}",
        "actor": actor,
        "replace_snapshot": True,
        "nodes": nodes,
        "edges": sorted(edges, key=lambda e: (e["source"], e["relation"], e["target"])),
    }


def check_root(export: dict, *, require_mountpoint: bool) -> None:
    mount = export["mount"]
    if not os.path.isdir(mount):
        raise FsExportError(f"{export['path']}: crawl root {mount} is not a directory")
    if require_mountpoint and not os.path.ismount(mount):
        raise FsExportError(
            f"{export['path']}: {mount} is not a mountpoint. Crawling the empty "
            "directory under a failed mount would retract every collection.")
    with os.scandir(mount) as it:
        if next(it, None) is None:
            raise FsExportError(f"{export['path']}: {mount} is empty; refusing an empty snapshot")


# --- store gates ----------------------------------------------------------------

def prom_query(url: str, query: str, password_file: str | None) -> float:
    parsed = urllib.parse.urlparse(url)
    netloc = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
    target = urllib.parse.urlunparse(
        (parsed.scheme or "http", netloc, parsed.path.rstrip("/") + "/api/v1/query",
         "", urllib.parse.urlencode({"query": query}), ""))
    req = urllib.request.Request(target)
    if parsed.username:
        password = parsed.password or ""
        if password_file:
            password = Path(password_file).expanduser().read_text(encoding="utf-8").strip()
        cred = f"{parsed.username}:{password}"
        req.add_header("Authorization", "Basic " + base64.b64encode(cred.encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise GateUnknown(f"memory probe failed: {e}") from e
    result = data.get("data", {}).get("result", [])
    if len(result) != 1:
        raise GateUnknown(f"memory probe returned {len(result)} series, need exactly 1: {query}")
    return float(result[0]["value"][1])


def store_version() -> str:
    req = urllib.request.Request(f"{planes.SERVER}/version",
                                 headers={"X-Quipu-Client": "camayoc-ingress"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode().strip()
    except (urllib.error.URLError, OSError) as e:
        raise GateUnknown(f"/version unreachable: {e}") from e


def prior_collection_count(export_ent: str) -> int:
    q = ("SELECT (COUNT(?c) AS ?n) WHERE { ?c <%sinExport> <%s%s> }"
         % (BASE_NS, BASE_NS, export_ent))
    try:
        rows = planes._post("/query", {"query": q}, client="camayoc-ingress").get("rows", [])
    except planes.PlaneError as e:
        raise GateUnknown(f"prior count unavailable: {e}") from e
    if len(rows) != 1:
        raise GateUnknown(f"prior count query returned {len(rows)} rows")
    return int(str(rows[0].get("n", "0")).split("^^")[0].strip('"'))


@dataclasses.dataclass
class Gates:
    memory: callable
    version: callable
    prior_count: callable
    sleep: callable = time.sleep
    skip_at: float = DEFAULT_SKIP_AT
    abort_at: float = DEFAULT_ABORT_AT
    pace: float = MIN_PACE_S
    max_shrink: float = DEFAULT_MAX_SHRINK


def post_snapshots(bodies: list[dict], gates: Gates, post, log) -> int:
    """Write the snapshots one at a time under the store owner's gates."""
    try:
        mem = gates.memory()
        version = gates.version()
    except GateUnknown as e:
        log({"gate": "unknown", "error": str(e), "written": 0})
        return EXIT_UNKNOWN
    if mem >= gates.skip_at:
        log({"gate": "skip", "memory": mem, "skip_at": gates.skip_at, "written": 0})
        return EXIT_SKIPPED
    log({"gate": "start", "memory": mem, "version": version})
    written = []
    for i, body in enumerate(bodies):
        if i:
            gates.sleep(gates.pace)
        try:
            mem = gates.memory()
            now_version = gates.version()
            if body.get("_shrink_check"):
                ent, new = body["_shrink_check"]
                prior = gates.prior_count(ent)
                if prior and new < prior * gates.max_shrink:
                    log({"refused": body["name"], "prior_collections": prior,
                         "new_collections": new, "written": written})
                    return EXIT_ERROR
        except GateUnknown as e:
            log({"gate": "unknown", "error": str(e), "written": written})
            return EXIT_UNKNOWN
        if mem >= gates.abort_at:
            log({"gate": "abort", "memory": mem, "abort_at": gates.abort_at, "written": written})
            return EXIT_ABORTED
        if now_version != version:
            log({"gate": "abort", "reason": "store version changed mid-run",
                 "from": version, "to": now_version, "written": written})
            return EXIT_ABORTED
        wire = {k: v for k, v in body.items() if not k.startswith("_")}
        started = time.monotonic()
        try:
            result = post(wire)
        except Exception as e:  # noqa: BLE001 - reported, and the run stops
            log({"snapshot": body["name"], "error": str(e), "written": written,
                 "note": "a timeout or 5xx is INDETERMINATE: read back before re-running"})
            return EXIT_ERROR
        written.append(body["name"])
        log({"snapshot": body["name"], "outcome": result.get("outcome"),
             "count": result.get("count"), "seconds": round(time.monotonic() - started, 2),
             "memory": mem})
    return EXIT_OK


# --- CLI --------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text())
    if not isinstance(cfg.get("host"), str) or not isinstance(cfg.get("exports"), list):
        raise FsExportError("config needs a string 'host' and an 'exports' list")
    seen = set()
    for ex in cfg["exports"]:
        if not isinstance(ex.get("path"), str) or not ex["path"].startswith("/"):
            raise FsExportError(f"export path must be absolute: {ex!r}")
        if ex["path"] in seen:
            raise FsExportError(f"duplicate export {ex['path']}")
        seen.add(ex["path"])
        ex.setdefault("mount", None)
        ex.setdefault("depth", 1)
    return cfg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--actor", required=True)
    ap.add_argument("--only", action="append", default=[], help="export path; repeatable")
    ap.add_argument("--out", type=Path, help="write each episode JSON here (offline review)")
    ap.add_argument("--post", action="store_true", help="write the snapshots to the store")
    ap.add_argument("--allow-errors", action="store_true",
                    help="write exports whose crawl hit unreadable entries")
    ap.add_argument("--no-mountpoint-check", action="store_true", help="tests and local trees only")
    ap.add_argument("--skip-at", type=float, default=DEFAULT_SKIP_AT)
    ap.add_argument("--abort-at", type=float, default=DEFAULT_ABORT_AT)
    ap.add_argument("--pace", type=float, default=MIN_PACE_S)
    args = ap.parse_args(argv)

    def log(rec: dict) -> None:
        print(json.dumps(rec, sort_keys=True), flush=True)

    try:
        cfg = load_config(args.config)
    except (OSError, ValueError, FsExportError) as e:
        log({"error": f"config: {e}"})
        return EXIT_ERROR
    host = cfg["host"]
    exports = [e for e in cfg["exports"] if not args.only or e["path"] in args.only]
    if args.only and len(exports) != len(set(args.only)):
        log({"error": f"--only names an export not in the config: {sorted(args.only)}"})
        return EXIT_ERROR

    bodies, refused = [], False
    for ex in exports:
        result = None
        if ex["mount"]:
            try:
                check_root(ex, require_mountpoint=not args.no_mountpoint_check)
            except (OSError, FsExportError) as e:
                log({"export": ex["path"], "refused": str(e)})
                refused = True
                continue
            started = time.monotonic()
            result = crawl(ex["mount"], int(ex["depth"]))
            root = result.collections[""]
            log({"export": ex["path"], "collections": len(result.collections),
                 "files": root.files, "bytes": root.bytes, "dirs": result.dirs_seen,
                 "errors": len(result.errors), "error_sample": result.errors[:5],
                 "crawl_seconds": round(time.monotonic() - started, 1)})
            if result.errors and not args.allow_errors:
                log({"export": ex["path"], "refused": "unreadable entries would be written as undercounts"})
                refused = True
                continue
        body = episode_for(host, ex, result, actor=args.actor)
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / f"{sanitize(body['name'])}.json").write_text(
                json.dumps(body, sort_keys=True, indent=1) + "\n")
        if result is not None:
            body["_shrink_check"] = (export_entity(host, ex["path"]), len(result.collections))
        bodies.append(body)

    if refused:
        log({"summary": "refused", "written": 0,
             "note": "no snapshot is written while any export is refused"})
        return EXIT_ERROR
    if not args.post:
        log({"summary": "offline", "snapshots": len(bodies), "written": 0})
        return EXIT_OK
    if args.pace < MIN_PACE_S:
        log({"error": f"--pace {args.pace} is below the {MIN_PACE_S}s minimum between snapshots"})
        return EXIT_ERROR

    prom_url = os.environ.get(PROM_URL_ENV, "").strip()
    query = os.environ.get(MEMORY_QUERY_ENV, "").strip()

    def memory() -> float:
        if not prom_url or not query:
            raise GateUnknown(f"{PROM_URL_ENV} and {MEMORY_QUERY_ENV} must both be set")
        try:
            return prom_query(prom_url, query, os.environ.get(PROM_PASSWORD_FILE_ENV) or None)
        except OSError as e:
            raise GateUnknown(f"memory probe credential unreadable: {e}") from e

    gates = Gates(memory=memory, version=store_version, prior_count=prior_collection_count,
                  skip_at=args.skip_at, abort_at=args.abort_at, pace=args.pace)
    return post_snapshots(bodies, gates,
                          lambda b: planes._post("/episode", b, client="camayoc-ingress"), log)


if __name__ == "__main__":
    raise SystemExit(main())
