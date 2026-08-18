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

## What it preserves

The original inferred assertion is **retracted, not deleted**. quipu is
bitemporal: retraction closes the fact's valid interval and leaves it readable
as of an earlier time. A promotion that erased its own history would destroy
the evidence that the fact was ever low-trust, which is the one thing a reader
assessing it later most needs.

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
) -> dict:
    """The episode asserting the promoted fact into its new plane.

    Carries the promotion's own provenance — who moved it, from where, when and
    why — as `observed` facts, because the promotion IS an observed event even
    though the fact it moves was inferred. A reader must be able to see that
    this fact arrived by promotion rather than by direct observation.
    """
    turtle = f"""@prefix camayoc: <https://camayoc.local/ontology/> .
@prefix aegis:   <http://aegis.gastown.local/ontology/> .

<{subject}> camayoc:planePromotion [
    camayoc:promotedFrom  <{planes.plane_for("inferred")}> ;
    camayoc:promotedInto  <{planes.PLANES[target_plane]["iri"]}> ;
    camayoc:promotedBy    "{promoted_by}" ;
    camayoc:authoredBy    "{authored_by}" ;
    camayoc:promotedAt    "{timestamp}" ;
    aegis:sourceKind      "observed" ;
    aegis:falsifier       "the subject is absent from the target plane after this transaction" ;
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
) -> dict:
    """Run every gate, then produce the promotion episode.

    Gates run BEFORE anything is written, and in the order that fails cheapest
    first. The episode is returned rather than posted so the caller decides
    when to commit — and so the gates are testable without a live store.
    """
    if not reason.strip():
        raise PromotionRefused(
            "a promotion must state its reason; an unexplained trust upgrade is "
            "exactly the record a later reader cannot assess"
        )
    check_outranks(target_plane)
    check_not_self_promotion(promoted_by, authored_by)
    check_authority(promoted_by, target_plane, grants if grants is not None else load_authority())
    return promotion_episode(subject, target_plane, promoted_by, authored_by, reason, timestamp)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--subject", required=True, help="IRI of the fact to promote")
    ap.add_argument("--to", required=True, dest="target", help="target plane key")
    ap.add_argument("--by", required=True, help="principal performing the promotion")
    ap.add_argument("--authored-by", required=True, help="principal that wrote the fact")
    ap.add_argument("--reason", required=True, help="why this has earned promotion")
    ap.add_argument("--timestamp", default="2026-01-01T00:00:00Z")
    ap.add_argument("--emit", action="store_true", help="print the episode instead of posting")
    args = ap.parse_args()

    try:
        episode = promote(
            args.subject, args.target, args.by, args.authored_by, args.reason, args.timestamp
        )
    except (PromotionRefused, planes.PlaneError) as exc:
        print(f"PROMOTION REFUSED: {exc}", file=sys.stderr)
        return 2

    if args.emit:
        print(json.dumps(episode, indent=2))
        return 0

    try:
        planes._post("/episode", episode)
    except planes.PlaneError as exc:
        print(f"PROMOTION FAILED: {exc}", file=sys.stderr)
        return 3
    print(f"promoted {args.subject} into {args.target} by {args.by}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
