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

    # -- Q3 ----------------------------------------------------------------
    def test_q3_finds_the_claim_whose_falsifier_predates_the_change(self):
        """The config rewrite is dated 2026-08-10; the stale verification ran
        2026-08-01 and was never re-run after."""
        rows = run(
            self.graph,
            "camayoc_falsifiers_not_rerun",
            changedAt="2026-08-10T00:00:00Z",
        )
        labels = [r[1] for r in rows]
        self.assertTrue(any("verified once" in label for label in labels), rows)

    def test_q3_excludes_the_verification_rerun_after_the_change(self):
        """The discriminating arm: a re-run falsifier is current, and a query
        returning every dated verification would report diligence as staleness."""
        rows = run(
            self.graph,
            "camayoc_falsifiers_not_rerun",
            changedAt="2026-08-10T00:00:00Z",
        )
        labels = " ".join(r[1] for r in rows)
        self.assertNotIn("re-verified", labels)

    # -- Q4 ----------------------------------------------------------------
    def test_q4_reports_the_sabotage_proven_check_with_its_proof(self):
        rows = run(self.graph, "camayoc_adversarially_proven_checks")
        proven = [r for r in rows if "sabotage-proven" in r[1]]
        self.assertEqual(1, len(proven), rows)
        self.assertIn("verification-sabotage-run", proven[0][2])

    def test_q4_leaves_an_asserted_check_without_a_proof(self):
        """A check nobody sabotaged must come back with the proof column
        unbound — filling one in would erase the distinction Q4 exists for."""
        rows = run(self.graph, "camayoc_adversarially_proven_checks")
        asserted = [r for r in rows if "asserted to work" in r[1]]
        self.assertEqual(1, len(asserted), rows)
        self.assertEqual("", asserted[0][2])

    # -- Q5 ----------------------------------------------------------------
    def test_q5_returns_the_variables_a_check_depends_on(self):
        rows = run(
            self.graph,
            "camayoc_check_variable_dependence",
            check=f"{EX}check-adjacent-setting",
        )
        variables = [r[2] for r in rows]
        self.assertEqual(
            ["shacl-validate-on-write", "store-base-namespace"], sorted(variables)
        )

    def test_q5_returns_nothing_for_a_check_with_no_recorded_dependence(self):
        """UNKNOWN, not 'independent': an empty result means no dependence is
        recorded, and the query must not manufacture a verdict from absence."""
        rows = run(
            self.graph,
            "camayoc_check_variable_dependence",
            check=f"{EX}verification-byte-identity",
        )
        self.assertEqual([], rows)

    # -- Q7 ----------------------------------------------------------------
    def test_q7_finds_the_item_blocked_on_a_closed_dependency(self):
        rows = run(self.graph, "camayoc_blocked_on_closed_dependency")
        self.assertEqual(1, len(rows), rows)
        self.assertIn("P1 waiting on the schema migration", rows[0][1])
        self.assertIn("2026-08-05", rows[0][4])

    def test_q7_excludes_live_blocks_and_stale_edges_on_closed_items(self):
        """Two controls: a dependency still open is a real block, and a closed
        item's leftover blockedOn edge blocks nothing."""
        rows = run(self.graph, "camayoc_blocked_on_closed_dependency")
        labels = " ".join(r[1] for r in rows)
        self.assertNotIn("quipu refusal log", labels)
        self.assertNotIn("already-shipped", labels)

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

    # -- Q12 ---------------------------------------------------------------
    def test_q12_finds_the_path_whose_digests_differ(self):
        rows = run(self.graph, "camayoc_drifted_execution_paths")
        self.assertEqual(1, len(rows), rows)
        self.assertIn("six weeks stale", rows[0][1])
        self.assertNotEqual(rows[0][2], rows[0][3])

    def test_q12_excludes_matching_digests_and_undigested_paths(self):
        """Two controls: equal digests are observed agreement, and a path with
        no digest is UNKNOWN — neither may be reported as drift."""
        rows = run(self.graph, "camayoc_drifted_execution_paths")
        labels = " ".join(r[1] for r in rows)
        self.assertNotIn("matching source", labels)
        self.assertNotIn("shared read-only checkout", labels)
        self.assertNotIn("individual working tree", labels)

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

    # -- §D (Q16-Q21): cost accounting -------------------------------------
    # The suite's own acceptance: Q16 and Q18 run against a fixture whose
    # expected answer is known INDEPENDENTLY — the totals the harness files
    # print are stated in the fixture header, and these tests assert the
    # parsed sums reproduce exactly those numbers. A usage reader checkable
    # only against itself is the section-A defect in an accountant's hat.

    def test_q16_sums_a_work_items_cost_across_principals(self):
        """The guard fix was touched by two principals in two sessions;
        the rollout files print 41000 and 9000 — the query must say 50000."""
        rows = run(
            self.graph,
            "camayoc_work_item_token_cost",
            workitem=f"{EX}item-guard-fix",
        )
        self.assertEqual(1, len(rows), rows)
        self.assertEqual("50000", rows[0][1])

    def test_q16_returns_no_row_for_an_item_with_no_attributed_usage(self):
        """UNKNOWN, never zero: an unmeasured item must not read as free."""
        rows = run(
            self.graph,
            "camayoc_work_item_token_cost",
            workitem=f"{EX}item-blocked-on-open",
        )
        self.assertEqual([], rows)

    def test_q17_windows_a_principals_consumption_by_provider(self):
        """strider on 2026-08-14: the codex 41000 only. The 08-16 record is
        outside the window, and gonzo's codex leg belongs to gonzo."""
        rows = run(
            self.graph,
            "camayoc_principal_consumption_by_provider",
            principal=f"{EX}principal-strider",
            **{"from": "2026-08-14T00:00:00Z", "to": "2026-08-15T00:00:00Z"},
        )
        self.assertEqual([("codex", "41000")], rows)

    def test_q18_returns_both_legs_of_work_per_token(self):
        """strider closed 2 items and the rollouts print 41000 + 3000 = 44000.
        The ratio is the reader's — the query hands over the two measured legs."""
        rows = run(
            self.graph,
            "camayoc_work_per_token",
            principal=f"{EX}principal-strider",
        )
        self.assertEqual([("2", "44000")], rows)

    def test_q18_does_not_credit_a_principal_with_anothers_closes(self):
        """gonzo consumed 21000 and closed nothing — the count must be 0 with
        the consumption still visible, not a row borrowed from strider."""
        rows = run(
            self.graph,
            "camayoc_work_per_token",
            principal=f"{EX}principal-gonzo",
        )
        self.assertEqual([("0", "21000")], rows)

    def test_q19_finds_the_session_with_no_usage_record(self):
        rows = run(self.graph, "camayoc_sessions_without_usage")
        self.assertEqual(1, len(rows), rows)
        self.assertIn("no accounting written", rows[0][1])

    def test_q19_excludes_sessions_that_do_carry_records(self):
        """A query returning every Session would report the measured ones as
        unmeasured — the same defect as returning zero, inverted."""
        rows = run(self.graph, "camayoc_sessions_without_usage")
        labels = " ".join(r[1] for r in rows)
        self.assertNotIn("codex rollout", labels)
        self.assertNotIn("gonzo", labels)

    def test_q20_sums_the_window_per_provider_with_no_ceiling_involved(self):
        """The 08-14 day: claude 9000; codex 41000 + 7000 = 48000. The 08-15
        boundary record and the 08-16 record are outside the half-open window.
        No quota term exists to consult — rate needs consumption alone."""
        rows = run(
            self.graph,
            "camayoc_provider_burn_window",
            **{"from": "2026-08-14T00:00:00Z", "to": "2026-08-15T00:00:00Z"},
        )
        self.assertEqual([("claude", "9000"), ("codex", "48000")], rows)

    def test_q21_costs_a_decision_through_its_work_item(self):
        """The rollback was decided in the guard fix, whose attributed usage
        is 50000 — the same independent expectation Q16 pins."""
        rows = run(
            self.graph,
            "camayoc_decision_cost",
            decision=f"{EX}decision-rollback",
        )
        self.assertEqual(1, len(rows), rows)
        self.assertEqual("50000", rows[0][1])

    def test_q21_returns_no_row_for_a_decision_with_unmeasured_work(self):
        """UNKNOWN, never zero: no attributed usage means no cost claim."""
        rows = run(
            self.graph,
            "camayoc_decision_cost",
            decision=f"{EX}decision-unmeasured",
        )
        self.assertEqual([], rows)


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
        this fails and the paper's number gets revisited deliberately.

        19, not 13: the suite's §D (cost accounting, Q16-21 — there is no
        Q14/Q15) was uncounted until 2026-08-22, which understated the
        denominator exactly the way incident-corpus.md §4.2 warns about.
        16 covered since 2026-08-22: camayoc-89e landed the five single-edge
        mints (Q3/Q4/Q5/Q7/Q12) and camayoc-e29 the §D cost vocabulary
        (Q16-Q21). The three that remain — Q6, Q8, Q9 — all need the
        Principal/liveness modelling, which is a design, not an edge."""
        result = coverage.report()
        self.assertEqual("Partial", result["verdict"])
        self.assertEqual(16, result["covered"])
        self.assertEqual(19, result["total"])

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
