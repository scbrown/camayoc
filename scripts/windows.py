#!/usr/bin/env python3
"""Time-windowed operational graphs — where workflow/run/ticket data lives.

The second dimension of ingress routing (`plane_for(source_kind, data_kind)`
in `scripts/planes.py`): `knowledge` goes to the static planes, and
`operational` — high-churn workflow state, shuttle's export — goes into one
graph PER TIME WINDOW so a completed window can be deep-frozen whole
(quipu `docs/design/graph-kinds-and-deep-freeze.md`). The graph is the unit
of pack, attach, label and authority; windowing below the graph forfeits
all four, which is why the window IS a graph.

The create-and-label-or-neither discipline is `planes.py`'s, verbatim: a
window registered but not labelled `operational` never earns a freeze, and
looks exactly like a graph someone forgot — worse than absent, because it is
unfalsifiable from the outside.

IRI scheme (pinned by tests/test_planes_2d.py — shuttle reimplements it and
the pin is what keeps the two from drifting):

    {WINDOW_NS}{family}/{YYYY-MM}
    e.g. https://camayoc.local/window/shuttle/runs/2026-08

Usage:
    python3 scripts/windows.py ensure shuttle/runs 2026-08
    python3 scripts/windows.py iri shuttle/runs 2026-08
"""

from __future__ import annotations

import argparse
import re
import sys

from planes import PLANE_NS, TRUST_CHAIN, PlaneError, _post

#: Windows live beside the planes, under the same parameterized namespace
#: root — never a hardcoded hostname (CLAUDE.md).
WINDOW_NS = PLANE_NS.replace("/plane/", "/window/")

#: The label every window gets at creation. `soleRecord` is honest: until a
#: freeze, the window graph is the only copy; the freeze itself relabels to
#: archive/backed.
WINDOW_LABEL = {
    "kind": "operational",
    "freshness": "fresh",
    "durability": "soleRecord",
}

_FAMILY = re.compile(r"^[a-z][a-z0-9/-]*[a-z0-9]$")
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def window_iri(family: str, yyyymm: str) -> str:
    """The window graph IRI for a family and month. Validates, never guesses.

    `family` names the producer's stream (`shuttle/runs` first); `yyyymm`
    is the month the RUN STARTED — a run's transitions all land in its
    start window, so freezing a window never splits a run.
    """
    if not _FAMILY.match(family):
        raise PlaneError(
            f"window family '{family}' must match {_FAMILY.pattern} — it is "
            "an IRI path segment, not free text"
        )
    if not _MONTH.match(yyyymm):
        raise PlaneError(f"window month '{yyyymm}' must be YYYY-MM")
    return f"{WINDOW_NS}{family}/{yyyymm}"


def ensure_window(family: str, yyyymm: str, timestamp: str) -> dict:
    """Register AND label the window — both, or the window is not usable.

    Idempotent like `ensure_planes`. Returns what happened so a caller can
    tell a fresh window from an existing one.
    """
    iri = window_iri(family, yyyymm)
    created = _post("/graph/create", {"graph": iri})
    labelled = _post(
        "/graph/label",
        {
            "graph": iri,
            "timestamp": timestamp,
            **WINDOW_LABEL,
            # Windows share the planes' provenance chain so their (absent)
            # trust composes rather than colliding; shuttle's facts carry
            # per-event signatures instead of a plane-level trust rank.
            "actor": "camayoc-windows",
        },
    )
    return {
        "iri": iri,
        "g": created.get("g"),
        "newly_created": created.get("created"),
        "label_tx": labelled.get("tx_id"),
        "chain": TRUST_CHAIN,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("ensure", help="register and label a window graph")
    e.add_argument("family")
    e.add_argument("month")
    e.add_argument("--timestamp", default="2026-01-01T00:00:00Z")
    i = sub.add_parser("iri", help="print the window IRI")
    i.add_argument("family")
    i.add_argument("month")
    args = ap.parse_args()

    try:
        if args.cmd == "ensure":
            r = ensure_window(args.family, args.month, args.timestamp)
            state = "created" if r["newly_created"] else "already registered"
            print(f"{r['iri']} {state} tx={r['label_tx']}")
        else:
            print(window_iri(args.family, args.month))
    except PlaneError as exc:
        print(f"WINDOW ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
