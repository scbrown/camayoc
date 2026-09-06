"""The paper may not contradict the document it names as authoritative.

`paper.md` §6 opens *"From implemented-set.md, which is authoritative"* and then
makes its own scope claims. For fourteen days one of those claims said an aspect
was **NOT built** while the cited ledger said **Built** — a contradiction inside
one repo, between two files, one of which points at the other (aegis-ukg18c).

Nothing caught it, and no cross-repo watch would have: the ledger's own banner
says *"Re-run before drafting; do not carry a row forward on trust"*, and its
trigger is therefore the WRITER'S INTENT. A dependency moving fires it never,
and so does a sibling document being updated without the paper.

This test moves the trigger onto the artifact instead. It fails when the paper
denies an aspect the ledger marks built, so the next divergence is caught by
`just test` rather than by a reviewer who *"finds one unbuilt claim and stops
believing the built ones"* — the ledger's own stated fear.

Deliberately narrow. It checks ONE property, in one direction, on aspect names
taken from the ledger rather than hardcoded here — so an aspect renamed or added
is picked up without editing this file, and a false positive means the two
documents really do disagree.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs" / "design"
LEDGER = DOCS / "implemented-set.md"
PAPER = DOCS / "paper.md"

# `| 2 | Quarantined inference | ✅ **Built** (…) | evidence |`
ROW = re.compile(r"^\|\s*[\dab]+\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", re.M)

# The shapes a denial actually takes in this paper. Kept as an explicit list
# rather than a clever regex: a denial we do not recognise fails OPEN, and this
# test's job is to be trusted when it passes, so the list is auditable.
DENIALS = (
    "are not built",
    "is not built",
    "it is not built",
    "not built",
    "are NOT built",
)


def built_aspects() -> set[str]:
    """Aspect names the ledger marks as built (not partial, not planned)."""
    out = set()
    for name, state in ROW.findall(LEDGER.read_text(encoding="utf-8")):
        if name.lower() in {"d aspect", "---"}:
            continue
        if "built" in state.lower() and "not" not in state.lower():
            out.add(name.strip())
    return out


class PaperDoesNotContradictTheLedger(unittest.TestCase):
    def test_the_ledger_is_parseable_and_non_empty(self):
        """Control. Without this, an empty aspect set makes the real test vacuous
        — it would pass by having nothing to check, which is the failure mode
        this whole bead is about."""
        aspects = built_aspects()
        self.assertGreaterEqual(
            len(aspects),
            5,
            f"parsed only {len(aspects)} built aspects from {LEDGER.name}; the "
            "table shape changed and the check below is now vacuous",
        )
        self.assertIn("Quarantined inference", aspects)

    def test_the_paper_does_not_deny_an_aspect_the_ledger_calls_built(self):
        paper = PAPER.read_text(encoding="utf-8")
        offences = []
        for aspect in sorted(built_aspects()):
            for para in paper.split("\n\n"):
                if aspect.lower() not in para.lower():
                    continue
                low = para.lower()
                for denial in DENIALS:
                    if denial.lower() not in low:
                        continue
                    # A paragraph that RECORDS a corrected denial is not itself a
                    # denial. The correction has to be allowed to describe what
                    # it corrected, or fixing the bug re-triggers the test.
                    if "until 2026-" in low or "said the opposite" in low:
                        continue
                    offences.append((aspect, denial, para.strip()[:160]))
        self.assertEqual(
            offences,
            [],
            "paper.md denies an aspect that implemented-set.md — which paper.md "
            "itself names as authoritative — marks as Built:\n"
            + "\n".join(f"  {a!r} via {d!r}: {p}…" for a, d, p in offences),
        )
