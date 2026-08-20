"""The golden-path stored queries must RUN and be able to return findings — camayoc-gp2.

Same discipline as test_competency_queries.py, from which the harness here is
deliberately copied rather than imported (each suite must stand alone against
its own fixture): each query gets a seeded positive finding and a control
negative, because a query that cannot return findings is a check that cannot
fail, and a query returning every row would pass a bare non-empty assertion.

Executed with rdflib rather than a live quipu, and skipped when it is absent.
These prove the QUERIES; the write-time gates (a GoldenPath without its
exemplar, an omission without its authority, a promotion without its
promoter) are proven separately by scripts/gate_probe.sh and
tests/test_gate_probe.py.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "queries"
FIXTURE = ROOT / "tests" / "fixtures" / "golden-paths.ttl"
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
    string, not as `str(None)` — absent and present-but-empty stay distinct.
    """
    template = stored(name)["template"]
    for key, value in params.items():
        template = template.replace("{" + key + "}", value)
    if "{" in template.split("WHERE")[0]:
        raise AssertionError(f"unsubstituted parameter in {name}")
    return [tuple("" if v is None else str(v) for v in row) for row in graph.query(template)]


@unittest.skipUnless(HAVE_RDFLIB, "rdflib not installed")
class GoldenPathQueryExecutionTests(unittest.TestCase):
    """Each query runs, and each returns the finding a human seeded for it."""

    @classmethod
    def setUpClass(cls):
        cls.graph = rdflib.Graph()
        cls.graph.parse(FIXTURE, format="turtle")

    # -- Q1 ----------------------------------------------------------------
    def test_q1_replays_the_deploy_trajectory_in_order(self):
        rows = run(self.graph, "camayoc_gp_trajectory_replay", trajectory=f"{EX}traj-deploy")
        self.assertEqual(6, len(rows), rows)
        self.assertEqual([str(i) for i in range(1, 7)], [r[1] for r in rows])
        self.assertIn("read the service spec", rows[0][2])
        self.assertIn("verify the deploy", rows[5][2])

    def test_q1_leaves_unrecorded_cells_empty_rather_than_invented(self):
        """Only step 2 enacts a Decision and only step 6 has a Verification —
        the other cells must be empty, not filled from the nearest term."""
        rows = run(self.graph, "camayoc_gp_trajectory_replay", trajectory=f"{EX}traj-deploy")
        decisions = [r[5] for r in rows]
        verifications = [r[6] for r in rows]
        self.assertEqual(1, sum(1 for d in decisions if d), decisions)
        self.assertEqual(1, sum(1 for v in verifications if v), verifications)

    # -- Q2 ----------------------------------------------------------------
    def test_q2_finds_the_trajectories_for_a_topic_with_outcomes(self):
        rows = run(self.graph, "camayoc_gp_trajectories_for_topic", topic="service-deploy")
        outcomes = {r[1].rsplit("/", 1)[-1]: r[2] for r in rows}
        self.assertEqual(
            {"wi-deploy": "done", "wi-abandoned": "abandoned",
             "wi-follow": "done", "wi-stray": "failed"},
            outcomes,
        )

    def test_q2_does_not_return_other_topics(self):
        rows = run(self.graph, "camayoc_gp_trajectories_for_topic", topic="service-deploy")
        self.assertNotIn("wi-hotfix", " ".join(r[1] for r in rows))

    # -- Q3 ----------------------------------------------------------------
    def test_q3_admits_only_the_verified_success(self):
        rows = run(self.graph, "camayoc_gp_admissible_exemplars")
        workitems = [r[0].rsplit("/", 1)[-1] for r in rows]
        self.assertEqual(["wi-deploy"], workitems, rows)

    def test_q3_excludes_the_done_but_unfalsifiable_and_the_abandoned(self):
        """wi-hotfix closed done but its check names no falsifier; wi-abandoned
        did not close done. Both are the controls Q3 exists to exclude."""
        rows = run(self.graph, "camayoc_gp_admissible_exemplars")
        joined = " ".join(r[0] for r in rows)
        self.assertNotIn("wi-hotfix", joined)
        self.assertNotIn("wi-abandoned", joined)

    # -- Q4 ----------------------------------------------------------------
    def test_q4_shows_the_unverified_stretch(self):
        rows = run(self.graph, "camayoc_gp_unverified_stretch", trajectory=f"{EX}traj-deploy")
        self.assertEqual(6, len(rows))
        unverified = [r for r in rows if not r[3]]
        self.assertEqual(5, len(unverified), rows)

    def test_q4_does_not_strip_the_verification_the_trajectory_has(self):
        rows = run(self.graph, "camayoc_gp_unverified_stretch", trajectory=f"{EX}traj-deploy")
        verified = [r for r in rows if r[3]]
        self.assertEqual(1, len(verified))
        self.assertIn("verify the deploy", verified[0][2])

    # -- Q6 ----------------------------------------------------------------
    def test_q6_returns_both_omissions_with_their_authorities(self):
        rows = run(self.graph, "camayoc_gp_omissions", path=f"{EX}gp-deploy")
        self.assertEqual(2, len(rows), rows)
        by_authority = {r[2]: r for r in rows}
        self.assertEqual({"cone-analysis", "human-decision"}, set(by_authority))
        human = by_authority["human-decision"]
        self.assertIn("decision-prune-read", human[3])
        self.assertIn("double-counts", human[4])

    def test_q6_leaves_the_mechanical_omission_without_a_ruling(self):
        """A cone-analysis cut has no human Decision behind it. Inventing one
        would erase the authority distinction the omission exists to carry."""
        rows = run(self.graph, "camayoc_gp_omissions", path=f"{EX}gp-deploy")
        cone = [r for r in rows if r[2] == "cone-analysis"][0]
        self.assertEqual("", cone[3])

    # -- Q7 ----------------------------------------------------------------
    def test_q7_preserves_the_dead_end_as_a_hazard(self):
        rows = run(self.graph, "camayoc_gp_dead_ends", path=f"{EX}gp-deploy")
        self.assertEqual(1, len(rows))
        self.assertIn("response cache", rows[0][1])

    def test_q7_returns_nothing_for_a_path_without_hazards(self):
        rows = run(self.graph, "camayoc_gp_dead_ends", path=f"{EX}gp-pending")
        self.assertEqual([], rows)

    # -- Q8 ----------------------------------------------------------------
    def test_q8_returns_the_promotion_history_in_order(self):
        rows = run(self.graph, "camayoc_gp_blessing_history", path=f"{EX}gp-deploy")
        self.assertEqual(["candidate", "advisory"], [r[1] for r in rows])
        self.assertTrue(all("stiwi" in r[2] for r in rows), rows)
        self.assertIn("backtest run 2026-08-04", rows[0][4])

    def test_q8_does_not_mix_in_another_paths_promotions(self):
        rows = run(self.graph, "camayoc_gp_blessing_history", path=f"{EX}gp-pending")
        self.assertEqual(1, len(rows))
        self.assertEqual("candidate", rows[0][1])

    # -- Q9 ----------------------------------------------------------------
    def test_q9_finds_the_superseded_path_and_its_winner(self):
        rows = run(self.graph, "camayoc_gp_superseded_paths")
        self.assertEqual(1, len(rows), rows)
        self.assertIn("legacy deploy", rows[0][1])
        self.assertIn("gp-deploy", rows[0][2])

    # -- Q10 ---------------------------------------------------------------
    def test_q10_queues_the_candidate_awaiting_promotion(self):
        rows = run(self.graph, "camayoc_gp_promotion_queue")
        self.assertEqual(1, len(rows), rows)
        self.assertIn("gp-pending", rows[0][0])

    def test_q10_excludes_the_promoted_and_the_superseded(self):
        """gp-deploy has an advisory promotion and gp-old lost to it; a queue
        containing either would page a human about settled work."""
        rows = run(self.graph, "camayoc_gp_promotion_queue")
        joined = " ".join(r[0] for r in rows)
        self.assertNotIn("gp-deploy", joined)
        self.assertNotIn("gp-old", joined)

    # -- Q11 ---------------------------------------------------------------
    def test_q11_finds_the_path_for_similar_work(self):
        rows = run(self.graph, "camayoc_gp_paths_for_similar_work", workitem=f"{EX}wi-new")
        self.assertEqual(1, len(rows), rows)
        self.assertIn("gp-deploy", rows[0][0])

    def test_q11_does_not_offer_paths_from_other_topics_or_superseded_ones(self):
        rows = run(self.graph, "camayoc_gp_paths_for_similar_work", workitem=f"{EX}wi-new")
        joined = " ".join(r[0] for r in rows)
        self.assertNotIn("gp-pending", joined)
        self.assertNotIn("gp-old", joined)

    # -- Q12 ---------------------------------------------------------------
    def test_q12_reports_the_deviator_with_its_deviation(self):
        rows = run(self.graph, "camayoc_gp_conformance", path=f"{EX}gp-deploy")
        self.assertEqual(2, len(rows), rows)
        stray = [r for r in rows if "wi-stray" in r[1]][0]
        self.assertIn("without running the suite", stray[3])

    def test_q12_leaves_the_conformer_without_an_invented_deviation(self):
        rows = run(self.graph, "camayoc_gp_conformance", path=f"{EX}gp-deploy")
        follow = [r for r in rows if "wi-follow" in r[1]][0]
        self.assertEqual("", follow[2])

    # -- Q13 ---------------------------------------------------------------
    def test_q13_returns_outcomes_and_deviations_for_the_rates(self):
        rows = run(self.graph, "camayoc_gp_backtest_outcomes", path=f"{EX}gp-deploy")
        self.assertEqual(2, len(rows), rows)
        by_wi = {r[1].rsplit("/", 1)[-1]: r for r in rows}
        self.assertEqual("done", by_wi["wi-follow"][2])
        self.assertEqual("", by_wi["wi-follow"][3])
        self.assertEqual("failed", by_wi["wi-stray"][2])
        self.assertTrue(by_wi["wi-stray"][3])


class GoldenPathCoverageTests(unittest.TestCase):
    """The golden-paths slice of the coverage report, checked like the first."""

    def test_every_stored_query_is_grounded_in_the_ontology(self):
        result = coverage.report("golden-paths")
        ungrounded = [r for r in result["rows"] if r["state"] == "UNGROUNDED"]
        self.assertEqual([], ungrounded, ungrounded)

    def test_no_question_claims_a_query_that_is_not_on_disk(self):
        result = coverage.report("golden-paths")
        missing = [r for r in result["rows"] if r["state"] == "MISSING"]
        self.assertEqual([], missing, missing)

    def test_coverage_is_partial_and_the_number_is_reported_honestly(self):
        """Pins the figure: 12 of 16, with Q5 waiting on quipu's cone command
        and Q14-Q16 deferred with the later ladder levels. If coverage changes
        — up or down — this fails and the number gets revisited deliberately."""
        result = coverage.report("golden-paths")
        self.assertEqual("Partial", result["verdict"])
        self.assertEqual(12, result["covered"])
        self.assertEqual(16, result["total"])
