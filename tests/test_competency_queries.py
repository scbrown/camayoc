"""The stored queries must RUN, and must be able to return findings — camayoc-102.

`camayoc-102` asks for three things per question: does a stored query exist,
does it return, and does it return something a human agrees with. This file
covers the second and third; `scripts/query_coverage.py` covers the first.

The load-bearing discipline is the competency suite's own:

    each query needs a seeded positive finding and a control negative; an empty
    result without those arms is not proof that the fleet is healthy.

That is the section-A defect one level up — a query that cannot return findings
is a check that cannot fail. So every test here asserts a specific non-empty
result against a deliberately seeded fixture, and where the query is a
"find the bad ones" query, it also asserts that the healthy rows are NOT
returned. A query returning every row would otherwise pass a bare non-empty
assertion.

Executed with rdflib rather than a live quipu, and the tests skip when it is
absent. Testing against a real store would prove the store; these prove the
QUERIES, which is what camayoc-102 is about. `tests/test_metrics_slice.py`
covers the real-server path when a `quipu-server` binary is available.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "queries"
FIXTURE = ROOT / "tests" / "fixtures" / "verification-liveness.ttl"
EX = "http://camayoc.test/fixture/"

try:
    import rdflib

    HAVE_RDFLIB = True
except ImportError:  # pragma: no cover - environment-dependent
    HAVE_RDFLIB = False


def load_coverage_script():
    spec = importlib.util.spec_from_file_location(
        "query_coverage", ROOT / "scripts" / "query_coverage.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


coverage = load_coverage_script()


def stored(name: str) -> dict:
    return json.loads((QUERIES / f"{name}.json").read_text())


def run(graph, name: str, **params):
    """Execute a stored query's template, substituting `{param}` placeholders.

    An unbound OPTIONAL comes back as `None` and is rendered as the empty
    string, not as `str(None)` — which would put the literal text "None" in a
    result cell and read as a value. That is the same confusion between absent
    and present-but-empty that this slice exists to police, so it would be a
    poor thing for the test harness to introduce.
    """
    template = stored(name)["template"]
    for key, value in params.items():
        template = template.replace("{" + key + "}", value)
    if "{" in template.split("WHERE")[0]:
        raise AssertionError(f"unsubstituted parameter in {name}")
    return [tuple("" if v is None else str(v) for v in row) for row in graph.query(template)]


@unittest.skipUnless(HAVE_RDFLIB, "rdflib not installed")
class CompetencyQueryExecutionTests(unittest.TestCase):
    """Each query runs, and each returns the finding a human seeded for it."""

    @classmethod
    def setUpClass(cls):
        cls.graph = rdflib.Graph()
        cls.graph.parse(FIXTURE, format="turtle")

    # -- Q1 ----------------------------------------------------------------
    def test_q1_returns_the_falsifier_for_a_verification(self):
        rows = run(
            self.graph,
            "camayoc_verification_falsifier",
            verification=f"{EX}verification-byte-identity",
        )
        self.assertEqual(1, len(rows), rows)
        self.assertIn("differing sha256", rows[0][2])

    def test_q1_returns_nothing_for_a_verification_with_no_falsifier(self):
        """The control arm. Q1 must not invent a falsifier for a node lacking one."""
        rows = run(
            self.graph,
            "camayoc_verification_falsifier",
            verification=f"{EX}verification-legacy-belt-and-braces",
        )
        self.assertEqual([], rows)

    # -- Q2 ----------------------------------------------------------------
    def test_q2_finds_the_verifications_carrying_no_falsifier(self):
        """The positive finding the suite's acceptance criterion demands for Q2.

        Note what this query can and cannot see, because it bears on the paper.
        A Verification without a falsifier CANNOT be written through a gated
        ingress — the M1 shape refuses it. So Q2's population is exactly the
        store's pre-gate legacy, and against a store that has always been gated
        it correctly returns nothing. The fixture seeds two pre-gate rows so the
        query is proven able to find them.
        """
        rows = run(self.graph, "camayoc_verifications_without_falsifier")
        labels = [r[1] for r in rows]
        self.assertEqual(2, len(rows), rows)
        self.assertTrue(any("belt-and-braces" in label for label in labels), labels)
        self.assertTrue(any("grep -c" in label for label in labels), labels)

    def test_q2_excludes_the_verifications_that_do_carry_a_falsifier(self):
        """The discriminating arm: a query returning every Verification would
        pass the test above and be useless."""
        rows = run(self.graph, "camayoc_verifications_without_falsifier")
        labels = " ".join(r[1] for r in rows)
        self.assertNotIn("byte-identity", labels)
        self.assertNotIn("schema comparison", labels)

    # -- Q10 ---------------------------------------------------------------
    def test_q10_separates_stated_from_built_blockers(self):
        rows = run(self.graph, "camayoc_blockers_by_evidence_kind")
        kinds = {r[2] for r in rows}
        self.assertEqual({"stated", "built"}, kinds, rows)
        built = [r for r in rows if r[2] == "built"]
        self.assertEqual(1, len(built))
        self.assertTrue(built[0][3], "a built blocker should carry its demonstration")

    def test_q10_leaves_a_stated_blocker_without_a_demonstration(self):
        """A stated blocker is a claim. If the query filled in a demonstration
        for it, the distinction the question exists for would be gone."""
        rows = run(self.graph, "camayoc_blockers_by_evidence_kind")
        stated_rows = [r for r in rows if r[2] == "stated"]
        self.assertEqual(1, len(stated_rows))
        self.assertEqual("", stated_rows[0][3] or "")

    # -- Q11 ---------------------------------------------------------------
    def test_q11_returns_the_full_execution_path(self):
        rows = run(
            self.graph,
            "camayoc_execution_path_for_mechanism",
            mechanism=f"{EX}path-home-working-tree",
        )
        self.assertEqual(1, len(rows), rows)
        _, _, artifact, source, refreshed, _ = rows[0]
        self.assertIn("/home/strider/", artifact)
        self.assertIn("scbrown/camayoc", source)
        self.assertIn("git pull", refreshed)

    # -- Q13 ---------------------------------------------------------------
    def test_q13_finds_the_single_principal_owned_path(self):
        rows = run(self.graph, "camayoc_single_owner_execution_paths")
        labels = " ".join(r[1] for r in rows)
        self.assertIn("individual working tree", labels)

    def test_q13_does_not_return_paths_with_no_owner_recorded(self):
        """The shared read-only checkout records no owner and must not appear;
        a query that returned every ExecutionPath would report the healthy one
        as risk."""
        rows = run(self.graph, "camayoc_single_owner_execution_paths")
        labels = " ".join(r[1] for r in rows)
        self.assertNotIn("shared read-only checkout", labels)


class CoverageReportTests(unittest.TestCase):
    """The coverage report is itself checked, since it is the paper's number."""

    def test_every_stored_query_is_grounded_in_the_ontology(self):
        """A stored query naming a predicate the ontology does not define would
        return zero rows forever and read as 'nothing to report' — the exact
        failure this repo keeps finding. UNGROUNDED must be empty."""
        result = coverage.report()
        ungrounded = [r for r in result["rows"] if r["state"] == "UNGROUNDED"]
        self.assertEqual([], ungrounded, ungrounded)

    def test_no_question_claims_a_query_that_is_not_on_disk(self):
        result = coverage.report()
        missing = [r for r in result["rows"] if r["state"] == "MISSING"]
        self.assertEqual([], missing, missing)

    def test_coverage_is_partial_and_the_number_is_reported_honestly(self):
        """Pins the figure the paper cites. If coverage changes — up or down —
        this fails and the paper's number gets revisited deliberately."""
        result = coverage.report()
        self.assertEqual("Partial", result["verdict"])
        self.assertEqual(5, result["covered"])
        self.assertEqual(13, result["total"])

    def test_every_gap_names_what_the_ontology_would_need(self):
        """A gap reported without the missing terms is a complaint, not a
        finding — it gives whoever picks it up nothing to act on."""
        result = coverage.report()
        for row in result["rows"]:
            if row["state"] == "GAP":
                with self.subTest(question=row["question"]):
                    self.assertTrue(row["gap"].strip())
                    self.assertTrue(
                        row["needs"], f"Q{row['question']} names no required terms"
                    )


if __name__ == "__main__":
    sys.exit(unittest.main())
