#!/usr/bin/env python3
"""Settled-decision collision check — camayoc-7lt.

Before an agent's `Decision` episode lands, compare it against the standing
human decisions in `crew:declared`. A match above threshold surfaces
"duplicates or conflicts with a settled decision" **as advisory, before the
write**. Convention memory made checkable: the store notices re-litigation.

## Posture

Stage-1: identify and inform. This never blocks a write and never edits a
decision. It returns a verdict a caller may print, escalate on, or ignore.

## Method honesty, inherited from `competency.py` deliberately

The scorer is **lexical, not semantic**, and every verdict says so. That is not
a placeholder apology — it is this repo's own rule turned on its own tooling: a
lexical match must never be presented as a semantic one, exactly as an inferred
fact must never masquerade as an observed one. Every verdict carries `method`,
`semantic: false`, the thresholds used, the corpus size and a corpus watermark,
so a reader can re-score and disagree.

Changing the algorithm MUST change `METHOD`. A verdict whose method is a lie is
worse than no verdict.

## Why the recorded verdict lands in the inferred plane

If this check's output is ever written back, it is a model-adjacent judgment
about a human's decision and belongs in `crew:inferred` — low trust, promotable
by someone with authority. Writing a collision verdict into `crew:declared`
alongside the human decision it is commenting on would be precisely the
masquerade camayoc exists to prevent, and it is what made this bead wait for
the planes.

Usage:
    python3 scripts/settled_decisions.py "we should switch to trunk-based dev" \\
        --declared decisions.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    # Registered before exec: @dataclass resolves annotations through
    # sys.modules, and a module absent from it fails with an opaque
    # NoneType error rather than an import error.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


competency = _load("competency")
planes = _load("planes")

#: Reusing competency's tokenizer and scorer rather than writing a second one.
#: Two similarity implementations in one repo drift, and the drift is invisible
#: because both keep returning plausible numbers.
METHOD = "lexical-jaccard-v1"

#: Uncalibrated, and every verdict carries the value used. Set higher than
#: competency's FLOOR because the cost of a false collision is different: a
#: spurious ontology gap files a bead, a spurious collision tells someone their
#: new decision was already settled, which is a claim about a person.
ADVISORY = 0.20
ESCALATE = 0.45


@dataclass(frozen=True)
class SettledDecision:
    """One standing human decision from `crew:declared`."""

    iri: str
    text: str
    decided_by: str


def load_declared(path: Path) -> list[SettledDecision]:
    """Standing decisions, as exported from `crew:declared`.

    Read from a file rather than queried live so this is testable and so the
    corpus is pinned by a watermark. A live query would make every verdict
    unreproducible.
    """
    raw = json.loads(path.read_text())
    return [
        SettledDecision(
            iri=d["iri"], text=d["text"], decided_by=d.get("decided_by", "unknown")
        )
        for d in raw
    ]


def watermark(corpus: list[SettledDecision]) -> str:
    """Digest over the corpus scored against, so a verdict is tied to it."""
    h = hashlib.sha256()
    for d in sorted(corpus, key=lambda x: x.iri):
        h.update(d.iri.encode())
        h.update(b"\0")
        h.update(d.text.encode())
        h.update(b"\n")
    return f"sha256:{h.hexdigest()[:16]}"


def score(proposed: str, settled: SettledDecision) -> float:
    left = competency.tokenize(proposed)
    right = competency.tokenize(settled.text)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def check(
    proposed: str,
    corpus: list[SettledDecision],
    advisory: float = ADVISORY,
    escalate: float = ESCALATE,
) -> dict:
    """Score a proposed decision against the settled ones.

    Outcomes are kept apart: `no_corpus` is NOT `clear`. Scoring a proposed
    decision against zero settled ones produces no matches and would otherwise
    render exactly like a clean result — the same collapse the gate probe, the
    coverage reporter and the bead advisory all had to unpick.
    """
    if not corpus:
        return {
            "outcome": "no_corpus",
            "matches": [],
            "method": METHOD,
            "semantic": False,
            "advisory_threshold": advisory,
            "escalate_threshold": escalate,
            "corpus_size": 0,
            "corpus_watermark": watermark(corpus),
            "note": "No settled decisions were available, so nothing was compared. "
                    "This is not 'no collision'.",
        }

    scored = sorted(
        ((score(proposed, d), d) for d in corpus), key=lambda p: p[0], reverse=True
    )
    matches = [
        {
            "iri": d.iri,
            "decided_by": d.decided_by,
            "text": d.text,
            "score": round(s, 4),
            "level": "escalate" if s >= escalate else "advisory",
        }
        for s, d in scored
        if s >= advisory
    ]
    outcome = "clear"
    if any(m["level"] == "escalate" for m in matches):
        outcome = "escalate"
    elif matches:
        outcome = "advisory"

    return {
        "outcome": outcome,
        "matches": matches,
        "method": METHOD,
        "semantic": False,
        "advisory_threshold": advisory,
        "escalate_threshold": escalate,
        "corpus_size": len(corpus),
        "corpus_watermark": watermark(corpus),
    }


def verdict_episode(proposed: str, verdict: dict, actor: str, timestamp: str) -> dict:
    """The episode recording this verdict, routed to the INFERRED plane.

    A model-adjacent judgment about a human's decision is `inferred`, full
    stop. Recording it in `crew:declared` beside the decision it comments on
    would make a machine's opinion indistinguishable from the human's
    statement — the exact masquerade the planes exist to prevent.
    """
    body = json.dumps(verdict, sort_keys=True).replace('"', '\\"')
    turtle = f"""@prefix camayoc: <https://camayoc.local/ontology/> .
@prefix aegis:   <http://aegis.gastown.local/ontology/> .

[] a camayoc:SettledDecisionCheck ;
    camayoc:proposedText  "{proposed.replace('"', chr(92) + chr(34))}" ;
    camayoc:verdict       "{body}" ;
    camayoc:method        "{METHOD}" ;
    aegis:sourceKind      "inferred" ;
    aegis:falsifier       "a human re-scores the proposal against the same corpus watermark and disagrees with the outcome" ;
    camayoc:checkedAt     "{timestamp}" .
"""
    return {
        "name": f"settled-decision-check-{timestamp}",
        "graph": planes.plane_for("inferred"),
        "episode_body": turtle,
        "source": "camayoc settled-decision check",
        "actor": actor,
        "nodes": [],
        "edges": [],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("proposed", help="the decision text about to be recorded")
    ap.add_argument("--declared", type=Path, required=True,
                    help="JSON export of standing decisions from crew:declared")
    ap.add_argument("--advisory", type=float, default=ADVISORY)
    ap.add_argument("--escalate", type=float, default=ESCALATE)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    verdict = check(args.proposed, load_declared(args.declared), args.advisory, args.escalate)

    if args.json:
        print(json.dumps(verdict, indent=2))
        return 0

    if verdict["outcome"] == "no_corpus":
        print("NO CORPUS — no settled decisions were available, so nothing was compared.")
        print("  This is not 'no collision'.")
    elif verdict["outcome"] == "clear":
        print(f"CLEAR — {verdict['corpus_size']} settled decision(s) scored, "
              f"none at or above {verdict['advisory_threshold']:.2f}.")
    else:
        print(f"{verdict['outcome'].upper()} — this may duplicate or conflict with "
              f"a settled decision:")
        for m in verdict["matches"]:
            print(f"  {m['score']:.3f}  [{m['level']}]  {m['iri']}  (decided by {m['decided_by']})")
            print(f"          {m['text']}")
        print("\nAdvisory only — the write is never blocked.")

    print(f"\nbasis: method={verdict['method']} semantic={verdict['semantic']} "
          f"advisory={verdict['advisory_threshold']} escalate={verdict['escalate_threshold']} "
          f"corpus={verdict['corpus_size']} watermark={verdict['corpus_watermark']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
