#!/usr/bin/env python3
"""Per-question stored-query coverage for the competency suite — camayoc-102.

The competency suite sets its own rule: *every question must eventually run as
a named stored query* (quipu #79). This reports how far from that we are, per
question, and treats the shortfall as a result rather than a chore.

Three levels, deliberately kept apart, because they fail for different reasons
and collapsing them is the defect this repo keeps finding elsewhere:

    EXPRESSIBLE   the ontology carries the terms the question needs.
                  When it does not, that is a COMPETENCY GAP — the finding
                  camayoc-b6h describes, not a missing chore.
    STORED        a named stored query exists in queries/.
    EXECUTED      the query runs against the fixture graph and returns rows
                  a human agreed with (asserted in tests/test_competency_queries.py).

A question can be EXPRESSIBLE and not STORED (work to do), but never STORED
without being EXPRESSIBLE — which the self-check below enforces, because a
stored query naming a predicate the ontology does not define would return zero
rows forever and read as "nothing to report".

Usage:
    python3 scripts/query_coverage.py            # the report
    python3 scripts/query_coverage.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "queries"
ONTOLOGY = ROOT / "ontology" / "core.ttl"

#: Question -> the stored query that answers it, or None with the reason.
#:
#: Hand-maintained because the mapping is a judgment: only a human can say that
#: `camayoc_blockers_by_evidence_kind` answers Q10. What is NOT hand-maintained
#: is whether the named file exists or whether the terms exist — both are
#: checked below, so this table cannot quietly claim coverage it does not have.
SLICE = "verification-and-liveness"

COVERAGE: dict[int, dict] = {
    1: {"query": "camayoc_verification_falsifier"},
    2: {"query": "camayoc_verifications_without_falsifier"},
    3: {
        "query": None,
        "gap": "No term records WHEN a falsifier was last re-run. Q3 asks which "
               "'X is fixed' claims have a falsifier never re-run after a change; "
               "aegis:Verification has no verifiedAt, and there is no relation "
               "from a Verification to the change it followed.",
        "needs": ["verifiedAt", "verifies (Verification -> change)"],
    },
    4: {
        "query": None,
        "gap": "No term distinguishes a check PROVEN adversarial from one merely "
               "asserted to work. aegis:demonstratedBy exists but is defined on "
               "Blocker, not Verification. This is the same non-vacuity property "
               "camayoc-104 just established for the gate probes — the ontology "
               "cannot yet record it about anything else.",
        "needs": ["adversariallyProvenBy (Verification -> Verification)"],
    },
    5: {
        "query": None,
        "gap": "No term relates a check to the variable under test, so 'does the "
               "mechanism depend on what changed' cannot be asked. This question "
               "exists to protect valid adjacent-setting evidence from being "
               "discarded (incident forms A2 and A6), so the gap has a cost in "
               "both directions.",
        "needs": ["dependsOnVariable"],
    },
    6: {
        "query": None,
        "gap": "No Principal class and no session/heartbeat record, so 'is this "
               "principal running' has nothing to join against. Correctly NOT a "
               "stored fact — ingress rule 5 forbids storing judgments that decay "
               "— but the read-time join needs an observed liveness record to "
               "join TO, and none is modelled. This is the single largest gap and "
               "it blocks the four-beads-one-cause family the paper leads with.",
        "needs": ["Principal", "Session", "observed stop record (frm/item/item_status/ts)"],
    },
    7: {
        "query": None,
        "gap": "aegis:Blocker exists but no predicate relates a WorkItem to the "
               "WorkItem it is blocked on, so 'blocked on a dependency already "
               "closed' cannot be expressed. aegis:closedAt exists, so only the "
               "edge is missing.",
        "needs": ["blockedOn (WorkItem -> WorkItem)"],
    },
    8: {
        "query": None,
        "gap": "No Alert or Escalation class. Same missing liveness join as Q6, "
               "plus the subject class itself.",
        "needs": ["Alert", "Escalation", "Principal liveness record"],
    },
    9: {
        "query": None,
        "gap": "Only createdAt and closedAt are modelled, so elapsed time WITHOUT "
               "a state transition is not derivable — the intermediate transitions "
               "are not recorded as facts.",
        "needs": ["StateTransition", "transitionedAt"],
    },
    10: {"query": "camayoc_blockers_by_evidence_kind"},
    11: {"query": "camayoc_execution_path_for_mechanism"},
    12: {
        "query": None,
        "gap": "ExecutionPath carries executesArtifact and repositorySource as "
               "strings, but no digest on either, so 'differs between source and "
               "installed artifact' cannot be evaluated in the store. "
               "aegis:contentHash exists but is defined for Metric.",
        "needs": ["contentHash on ExecutionPath (both sides)"],
    },
    13: {"query": "camayoc_single_owner_execution_paths"},
}


def ontology_terms() -> set[str]:
    """Local names of every property and class the ontology defines."""
    text = ONTOLOGY.read_text()
    return set(re.findall(r"^aegis:(\w+)\s+a\s+(?:rdf:Property|rdfs:Class)", text, re.M))


def query_predicates(template: str) -> set[str]:
    """The aegis: predicates a stored query's template references."""
    return set(re.findall(r"aegis:(\w+)", template))


def load_queries() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted(QUERIES.glob("*.json"))}


def report() -> dict:
    terms = ontology_terms()
    stored = load_queries()

    rows = []
    for number in sorted(COVERAGE):
        entry = COVERAGE[number]
        name = entry.get("query")
        row = {"question": number, "query": name}

        if name is None:
            row["state"] = "GAP"
            row["gap"] = entry["gap"]
            row["needs"] = entry.get("needs", [])
        elif name not in stored:
            # The table claims a query that is not on disk. Loud, not silent.
            row["state"] = "MISSING"
            row["gap"] = f"{name}.json is named here but absent from queries/"
        else:
            undefined = sorted(query_predicates(stored[name]["template"]) - terms)
            if undefined:
                row["state"] = "UNGROUNDED"
                row["gap"] = (
                    f"references predicates the ontology does not define: {undefined}. "
                    "It would return zero rows forever and read as 'nothing to report'."
                )
            else:
                row["state"] = "STORED"
        rows.append(row)

    covered = sum(1 for r in rows if r["state"] == "STORED")
    total = len(rows)
    verdict = "Full" if covered == total else ("Empty" if covered == 0 else "Partial")

    return {
        "slice": SLICE,
        "covered": covered,
        "total": total,
        "verdict": verdict,
        "rows": rows,
        "stored_query_count": len(stored),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    result = report()
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"competency slice: {result['slice']}")
    print(
        f"stored-query coverage: {result['covered']}/{result['total']} "
        f"— {result['verdict']}"
    )
    print()
    for row in result["rows"]:
        if row["state"] == "STORED":
            print(f"  Q{row['question']:<3} STORED      {row['query']}")
        else:
            print(f"  Q{row['question']:<3} {row['state']:<11} {row['gap']}")
            for need in row.get("needs", []):
                print(f"           needs: {need}")
    print()
    print(
        "A question with no stored query is an ontology gap reported as itself, "
        "never answered from the nearest term."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
