#!/usr/bin/env python3
"""Authority-gated plane promotion — camayoc-mip.

Promotion is how a fact **earns** its way out of quarantine: a governed move
from `crew:inferred` into a plane that outranks it. It is deliberately not an
ingress feature (`docs/design/ingress.md` §4): ingress never upgrades its own
output, because a writer that can promote what it wrote has quarantine in name
only.

## The name

`shapes/code-entities.ttl` already uses "promotion" for an unrelated
bobbin-to-quipu ingest path. That name is established there, so this mechanism
is **plane promotion** throughout — the command is `promote-plane`, the
recorded fact is `camayoc:planePromotion`. Two different governed operations
sharing one word in one repo reads fine to whoever wrote it and confuses every
later reader.

## What it refuses, and why each refusal exists

- **No authority over the target plane.** Fails closed: an absent or unreadable
  authority file means *nobody* may promote, not everybody. A governance
  mechanism that defaults open is decoration.
- **Self-promotion.** The principal promoting must differ from the principal
  that wrote the fact. This is the rule `skills/camayoc/SKILL.md` states to
  agents in prose ("promotable later by someone with authority — never by you
  up-tagging it"); here it is enforced rather than requested.
- **Promotion into a plane that does not outrank the source.** A sideways or
  downward "promotion" is a category error, and one that would read in the
  audit record as if trust had been earned.
- **Promotion of something not actually in the source plane.** Otherwise the
  record asserts a move that never happened.

## The move rule (camayoc-913, resolved with quipu deep freeze)

**Assert in the target, CLOSE in the source, record the move.** The close is
a bitemporal retraction — quipu closes the valid interval, never deletes —
so the original stays visible as-of its write time in the inferred plane
(competency/workflow-and-archive.md Q13). The same rule governs deep freeze,
where the "close" is whole-graph relocation with the full-history pack as
the surviving record. The worry that closing erases the low-trust past was
the reason this stayed open; bitemporality answers it: valid-time replay
still shows the fact where and when it lived.

The close operates on the SOURCE EPISODE (`--source-episode`), because the
episode is the unit ingress actually writes into the plane and quipu's
`POST /episode/retract` is the graph-honest retraction surface (triple-level
`/retract` is ROOT-scoped). When the caller cannot name the source episode
the promotion still proceeds, the source interval stays open, and the
promotion record says so out loud (`camayoc:sourceLeftOpen true`) — an open
interval on the record beats a close that silently never happened.

Usage:
    python3 scripts/promote_plane.py \\
        --subject http://ex/fact/1 --to crew:records \\
        --by alice --authored-by claude --reason "corroborated by the deploy log"
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_planes():
    spec = importlib.util.spec_from_file_location("planes", ROOT / "planes.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    # Registered before exec: @dataclass resolves annotations through
    # sys.modules, and a module absent from it fails with an opaque
    # NoneType error rather than an import error.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


planes = _load_planes()

#: Where the authority grants live. A human-maintained file: who may promote
#: into which planes. Deliberately NOT derivable from anything an agent writes.
AUTHORITY_PATH = Path(
    os.environ.get("CAMAYOC_AUTHORITY", ROOT.parent / "config" / "plane-authority.json")
)

#: The plane facts are promoted OUT of. Promotion is only ever out of
#: quarantine; moving between the high-trust planes is a different operation
#: and is not this one.
SOURCE_PLANE = "crew:inferred"


class PromotionRefused(RuntimeError):
    """A promotion was refused. Always raised, never returned as a soft verdict —
    a refused promotion that returns a result object gets treated as a result."""


def load_authority() -> dict[str, list[str]]:
    """Principal -> planes they may promote into.

    Fails CLOSED. A missing, unreadable, or malformed file yields no grants,
    so every promotion is refused. The alternative — treating an unreadable
    grant file as unrestricted — is the failure mode that makes an authority
    check worthless.
    """
    try:
        raw = json.loads(AUTHORITY_PATH.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionRefused(
            f"authority file {AUTHORITY_PATH} could not be read ({exc}); refusing all "
            "promotion. This is 'could not look', and it fails closed on purpose."
        ) from exc
    if not isinstance(raw, dict):
        raise PromotionRefused(f"authority file {AUTHORITY_PATH} is not an object")
    return {k: list(v) for k, v in raw.items() if isinstance(v, list)}


def check_authority(principal: str, target_plane: str, grants: dict[str, list[str]]) -> None:
    if target_plane not in grants.get(principal, []):
        raise PromotionRefused(
            f"'{principal}' holds no authority over '{target_plane}'. "
            f"Grants live in {AUTHORITY_PATH} and are human-maintained."
        )


def check_not_self_promotion(promoted_by: str, authored_by: str) -> None:
    if promoted_by == authored_by:
        raise PromotionRefused(
            f"'{promoted_by}' wrote this fact and cannot promote it. Quarantine that "
            "the writer can leave on its own authority is quarantine in name only."
        )


def check_outranks(target_plane: str) -> None:
    if target_plane not in planes.PLANES:
        raise PromotionRefused(f"unknown target plane '{target_plane}'")
    source_rank = planes.PLANES[SOURCE_PLANE]["rank"]
    target_rank = planes.PLANES[target_plane]["rank"]
    if target_rank <= source_rank:
        raise PromotionRefused(
            f"'{target_plane}' (rank {target_rank}) does not outrank "
            f"'{SOURCE_PLANE}' (rank {source_rank}); a sideways or downward move is "
            "not a promotion and must not be recorded as one."
        )


def promotion_episode(
    subject: str,
    target_plane: str,
    promoted_by: str,
    authored_by: str,
    reason: str,
    timestamp: str,
    source_left_open: bool = True,
) -> dict:
    """The episode asserting the promoted fact into its new plane.

    Carries the promotion's own provenance — who moved it, from where, when and
    why — as `observed` facts, because the promotion IS an observed event even
    though the fact it moves was inferred. A reader must be able to see that
    this fact arrived by promotion rather than by direct observation.
    """
    turtle = f"""@prefix camayoc: <https://camayoc.local/ontology/> .
@prefix aegis:   <http://aegis.gastown.local/ontology/> .
@prefix prov:    <http://www.w3.org/ns/prov#> .

<{subject}> camayoc:planePromotion [
    camayoc:promotedFrom  <{planes.plane_for("inferred")}> ;
    camayoc:promotedInto  <{planes.PLANES[target_plane]["iri"]}> ;
    camayoc:promotedBy    "{promoted_by}" ;
    camayoc:authoredBy    "{authored_by}" ;
    camayoc:promotedAt    "{timestamp}" ;
    aegis:sourceKind      "observed" ;
    aegis:falsifier       "the subject is absent from the target plane after this transaction" ;
    prov:wasDerivedFrom   <{subject}> ;
    camayoc:sourceLeftOpen {"true" if source_left_open else "false"} ;
    camayoc:reason        "{reason}"
] .
"""
    return {
        "name": f"plane-promotion-{subject.rsplit('/', 1)[-1]}-{timestamp}",
        "graph": planes.PLANES[target_plane]["iri"],
        "episode_body": turtle,
        "source": "camayoc plane promotion",
        "actor": promoted_by,
        "nodes": [],
        "edges": [],
    }


def promote(
    subject: str,
    target_plane: str,
    promoted_by: str,
    authored_by: str,
    reason: str,
    timestamp: str,
    grants: dict[str, list[str]] | None = None,
    source_episode: str | None = None,
) -> tuple[dict, dict | None]:
    """Run every gate, then produce the promotion episode and the source close.

    Gates run BEFORE anything is written, and in the order that fails cheapest
    first. Returns `(promotion_episode, close_request)`; the close is a
    `POST /episode/retract` body for `source_episode` (the bitemporal close of
    the source interval — the move rule), or None when the caller could not
    name the source episode, in which case the promotion record carries
    `camayoc:sourceLeftOpen true`. Returned rather than posted so the caller
    decides when to commit — and so the gates are testable without a live
    store. Commit order is assert-then-close: a failed close leaves the fact
    readable in two planes at different trust (recoverable, visible), while
    close-then-failed-assert would lose the promoted fact entirely.
    """
    if not reason.strip():
        raise PromotionRefused(
            "a promotion must state its reason; an unexplained trust upgrade is "
            "exactly the record a later reader cannot assess"
        )
    check_outranks(target_plane)
    check_not_self_promotion(promoted_by, authored_by)
    check_authority(promoted_by, target_plane, grants if grants is not None else load_authority())
    episode = promotion_episode(
        subject, target_plane, promoted_by, authored_by, reason, timestamp,
        source_left_open=source_episode is None,
    )
    close = None
    if source_episode is not None:
        close = {
            "episode": source_episode,
            "timestamp": timestamp,
            "actor": promoted_by,
            # Entities the promoted fact still references must survive the
            # close: retraction of the carrier episode is an interval close,
            # not an identity purge.
            "on_orphan": "preserve",
        }
    return episode, close


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--subject", required=True, help="IRI of the fact to promote")
    ap.add_argument("--to", required=True, dest="target", help="target plane key")
    ap.add_argument("--by", required=True, help="principal performing the promotion")
    ap.add_argument("--authored-by", required=True, help="principal that wrote the fact")
    ap.add_argument("--reason", required=True, help="why this has earned promotion")
    ap.add_argument("--timestamp", default="2026-01-01T00:00:00Z")
    ap.add_argument(
        "--source-episode",
        help="name of the episode that carried the fact into crew:inferred; "
        "when given, its interval is CLOSED after the assert (the move rule)",
    )
    ap.add_argument("--emit", action="store_true", help="print the episode instead of posting")
    args = ap.parse_args()

    try:
        episode, close = promote(
            args.subject, args.target, args.by, args.authored_by, args.reason, args.timestamp,
            source_episode=args.source_episode,
        )
    except (PromotionRefused, planes.PlaneError) as exc:
        print(f"PROMOTION REFUSED: {exc}", file=sys.stderr)
        return 2

    if args.emit:
        print(json.dumps({"promotion": episode, "close": close}, indent=2))
        return 0

    try:
        planes._post("/episode", episode)
    except planes.PlaneError as exc:
        print(f"PROMOTION FAILED: {exc}", file=sys.stderr)
        return 3
    if close is not None:
        try:
            planes._post("/episode/retract", close)
        except planes.PlaneError as exc:
            # Assert landed, close did not: readable in two planes, at
            # different trust — visible and recoverable, and said out loud.
            print(
                f"PROMOTED but source close FAILED: {exc}. The fact is now "
                "readable in both planes; re-run the close with "
                f"POST /episode/retract {json.dumps(close)}",
                file=sys.stderr,
            )
            return 4
        print(f"promoted {args.subject} into {args.target} by {args.by}; source episode closed")
    else:
        print(
            f"promoted {args.subject} into {args.target} by {args.by}; "
            "source interval LEFT OPEN (no --source-episode)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
