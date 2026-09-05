#!/usr/bin/env python3
"""Pull a Quipu share bundle or `.qpack.db` into a Camayoc store — one verb.

Camayoc does not reimplement canonical RDF serialization, share-manifest
hashing, resolution, or quarantine (docs/design/certified-knowledge-packs.md).
This is a WRAPPER over `quipu import` / `quipu unpack`, and its whole value is
in the two things a bare shell-out gets wrong:

1. IT VERIFIES THE QUIPU IT FOUND. The installed CLI on a host can be many
   versions behind the running service — measured 2026-09-05 at 0.3.7 installed
   against 0.3.36 on main, and 0.3.7 has no `import`/`unpack`/`share`/`pack`
   verb at all. Shelling out blind surfaces `unrecognized subcommand`, which
   reads as "quipu cannot import a share" — false, and false in the direction
   that looks like the feature is broken (aegis-ltaypw.0 condition A).

2. A QUARANTINE IS A SUCCESS. Pull ALWAYS stages and never promotes; exit 0
   covers `quarantined` as well as `loaded`, and nonzero is reserved for a
   FAILED VERIFICATION or a tool that would not run. The reasoning is wu's on
   aegis-ltaypw and it is load-bearing: if staging exits nonzero, every wrapper
   downstream treats the correct outcome as a failure, and somebody eventually
   "fixes" it by auto-promoting — which is the exact silent vocabulary widening
   the quarantine exists to prevent.

The verdict's `next` is a LITERAL EXECUTABLE COMMAND, never a description of
one, and it is omitted rather than guessed when no command would work.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# `import`, `unpack` and `pack --verify` all exist from here on.
MIN_QUIPU = (0, 3, 30)
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class PullError(Exception):
    """A failure that must exit nonzero: bad verification, or an unusable tool."""


def quipu_version(binary: str) -> tuple[int, int, int]:
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PullError(f"cannot run {binary!r}: {exc}") from exc
    m = VERSION_RE.search(out.stdout or out.stderr or "")
    if not m:
        raise PullError(f"{binary!r} did not report a version: {(out.stdout or out.stderr).strip()!r}")
    return tuple(int(g) for g in m.groups())  # type: ignore[return-value]


def require_quipu(binary: str) -> tuple[int, int, int]:
    """Refuse with the version we NEED, rather than letting the caller meet
    `unrecognized subcommand` and conclude the feature does not exist."""
    found = quipu_version(binary)
    if found < MIN_QUIPU:
        need = ".".join(str(p) for p in MIN_QUIPU)
        have = ".".join(str(p) for p in found)
        raise PullError(
            f"quipu {have} at {shutil.which(binary) or binary} is too old to pull a share: "
            f"share/pack/import/unpack need >= {need}. This is a HOST SKEW, not a missing "
            f"feature — the running service may be far ahead of the installed CLI. "
            f"Pass --quipu-bin </path/to/newer/quipu>."
        )
    return found


def classify(source: str) -> str:
    p = Path(source)
    if source.startswith(("http://", "https://")):
        return "url"
    if p.is_dir():
        if not (p / "manifest.json").is_file():
            raise PullError(f"{source} is a directory but has no manifest.json — not a share bundle")
        return "share"
    if p.is_file():
        return "pack"
    raise PullError(f"{source}: no such share directory, pack file, or URL")


def fetch(url: str, into: Path) -> Path:
    dest = into / Path(url).name
    try:
        with urllib.request.urlopen(url, timeout=120) as r, dest.open("wb") as fh:
            shutil.copyfileobj(r, fh)
    except Exception as exc:  # noqa: BLE001 — any fetch failure is a verification failure
        raise PullError(f"fetching {url}: {exc}") from exc
    return dest


def run(cmd: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def verify_pack(binary: str, path: Path) -> None:
    rc, out, err = run([binary, "pack", "--verify", str(path)])
    if rc != 0:
        raise PullError(f"pack verification FAILED for {path}: {(err or out).strip()}")


def adopt_shapes(binary: str, shapes: Path, name: str, db: str) -> dict:
    """Load the bundle's own shapes as a named set, provenance in the name.

    Deliberately a separate explicit act (wu's ruling): adopting a publisher's
    vocabulary is a decision, not a side effect of fetching their bytes.
    """
    if not shapes.is_file() or shapes.stat().st_size == 0:
        return {"adopted": False, "reason": "the bundle carries no shapes.ttl content to adopt"}
    rc, out, err = run([binary, "shapes", "load", name, str(shapes), "--db", db])
    if rc != 0:
        raise PullError(f"adopting bundle shapes as {name!r} failed: {(err or out).strip()}")
    return {"adopted": True, "shape_set": name}


def parse_json(text: str) -> dict:
    try:
        return json.loads(text[text.index("{"):])
    except (ValueError, json.JSONDecodeError):
        return {}


def pull(source: str, db: str, binary: str, do_adopt: bool) -> dict:
    require_quipu(binary)
    kind = classify(source)
    tmp: tempfile.TemporaryDirectory | None = None
    if kind == "url":
        tmp = tempfile.TemporaryDirectory()
        local = fetch(source, Path(tmp.name))
        kind = "share" if local.is_dir() else "pack"
        path = local
    else:
        path = Path(source)

    try:
        if kind == "pack":
            verify_pack(binary, path)                      # hash check BEFORE loading
            rc, out, err = run([binary, "unpack", str(path), "--db", db])
            if rc != 0:
                raise PullError(f"unpack failed: {(err or out).strip()}")
            return {"outcome": "loaded", "kind": "pack", "source": source,
                    "verified": True, "detail": out.strip().splitlines()[:6], "next": None,
                    "next_reason": "a pack is attached directly; there is nothing to promote"}

        manifest = json.loads((path / "manifest.json").read_text())
        adoption = {"adopted": False, "reason": "not requested"}
        if do_adopt:
            adoption = adopt_shapes(binary, path / "shapes.ttl",
                                    f"share:{manifest.get('share_id', 'unknown')}", db)

        rc, out, err = run([binary, "import", str(path), "--db", db])
        if rc != 0:
            raise PullError(f"import failed: {(err or out).strip()}")
        v = parse_json(out)
        outcome = v.get("outcome", "unknown")
        blockers = (v.get("promotion") or {}).get("blockers") or v.get("blockers") or []
        share_id = v.get("share_id") or manifest.get("share_id")

        verdict = {
            "outcome": outcome, "kind": "share", "source": source, "verified": True,
            "share_id": share_id, "graph_hash": v.get("graph_hash"),
            "staging_graph": v.get("staging_graph"),
            "triples": v.get("triples"), "blockers": blockers,
            "unmatched": (v.get("resolution") or {}).get("unmatched", []),
            "shapes": adoption,
        }
        verdict.update(next_step(verdict, path, db, binary))
        return verdict
    finally:
        if tmp is not None:
            tmp.cleanup()


def next_step(v: dict, path: Path, db: str, binary: str) -> dict:
    """The literal command to run next — or an honest absence.

    Never emit an invocation that would not work: a discovery tool that hands
    you an action contradicting its own finding is worse than one that offers
    none (wu, citing aegis-sosiaa / quipu #151).

    `binary` is threaded through for the reason the version guard exists. On a
    host whose PATH `quipu` is too old, the caller reaches this code ONLY by
    passing --quipu-bin — so emitting a literal `quipu` hands them a command
    that fails `unrecognized subcommand`, in exactly the situation the guard
    was written to detect. The suggestion has to name the binary that worked.
    """
    if v["outcome"] == "loaded" or not v["blockers"]:
        if v.get("share_id"):
            return {"next": f"{binary} import promote {v['share_id']} --db {db}"}
        return {"next": None, "next_reason": "nothing staged to promote"}

    if "off_vocabulary" in v["blockers"]:
        shapes = path / "shapes.ttl"
        if v["shapes"].get("adopted"):
            return {"next": f"{binary} import promote {v['share_id']} --db {db}"}
        if not shapes.is_file() or shapes.stat().st_size == 0:
            return {
                "next": None,
                "next_reason": (
                    "the bundle ships an EMPTY shapes.ttl, so --adopt-shapes would adopt "
                    "nothing and promotion would still be blocked. Govern these types in "
                    "this store first, or ask the publisher to share with shapes."
                ),
            }
        return {"next": f"{Path(__file__).name} {v['source']} --db {db} "
                        f"--quipu-bin {binary} --adopt-shapes"}

    return {"next": None,
            "next_reason": f"blocked on {v['blockers']}, which this verb has no automatic remedy for"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="pull_share.py",
        description="Pull a Quipu share bundle, .qpack.db, or release URL into a Camayoc store. "
                    "Always stages; never promotes.")
    ap.add_argument("source", help="share directory, .qpack.db file, or URL")
    ap.add_argument("--db", required=True, help="target Camayoc/Quipu store")
    ap.add_argument("--quipu-bin", default="quipu")
    ap.add_argument("--adopt-shapes", action="store_true",
                    help="also load the bundle's shapes.ttl as an attached named shape set, so "
                         "promotion passes for exactly the types the publisher governs. A "
                         "separate, explicit act: without it nothing about your vocabulary changes.")
    ap.add_argument("--json", action="store_true", help="emit the verdict as JSON")
    a = ap.parse_args(argv)

    try:
        verdict = pull(a.source, a.db, a.quipu_bin, a.adopt_shapes)
    except PullError as exc:
        print(f"pull refused: {exc}", file=sys.stderr)
        return 2

    if a.json:
        print(json.dumps(verdict, indent=2))
    else:
        print(f"{verdict['outcome']}: {verdict['kind']} from {verdict['source']}")
        if verdict.get("triples"):
            print(f"  triples: {verdict['triples']}")
        if verdict.get("blockers"):
            print(f"  blockers: {verdict['blockers']}")
        if verdict.get("staging_graph"):
            print(f"  staged in: {verdict['staging_graph']}")
        if verdict.get("next"):
            print(f"  next: {verdict['next']}")
        elif verdict.get("next_reason"):
            print(f"  next: none — {verdict['next_reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
