"""The workflow-and-archive stored queries must RUN and be able to fail — camayoc-rkb.

Third suite in the same shape as `test_competency_queries.py` and
`test_golden_path_queries.py`, and deliberately a copy of their harness rather
than an import of it: each suite has to stand alone against its own fixture,
so a change made for one slice cannot silently move another slice's answers.

WHAT IS DIFFERENT HERE, AND WHY IT IS THE POINT. This slice's fixture is a
TriG **dataset**, not a graph. The questions are about where facts live as
much as what they say — a run belongs to the window of the month it started, a
frozen window composes back in explicitly, the keys that verify signatures
live in an identity graph that is never frozen. So the queries carry explicit
`FROM` clauses and the tests assert BOTH arms of that:

    the query scoped to the right graphs returns the finding, AND
    the query scoped to the wrong ones does not.

`test_a_window_scoped_query_reads_nothing_from_the_default_graph` is the
load-bearing one. rdflib's Dataset does not union its contexts by default, so
a query that forgot its FROM returns zero rows — the same "nothing to report"
that a real store would answer with the wrong month's data. Pinning it means a
future edit that drops a FROM fails here instead of quietly changing scope.

Q13 is not tested against hand-written fixture triples. It runs against the
episode body `scripts/promote_plane.py` actually produces, parsed into the
dataset — a replay across a real promotion rather than against a fixture
tuned to match the query. Q14's freeze/thaw half has no stored query and the
reason is asserted rather than assumed (`FreezeAndThawReplayTests`).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "queries"
FIXTURE = ROOT / "tests" / "fixtures" / "workflow-archive.trig"

EX = "http://camayoc.test/fixture/"
DEFINITIONS = "http://camayoc.test/plane/crew/records"
HOT = "http://camayoc.test/window/shuttle/runs/2026-08"
FROZEN = "http://camayoc.test/window/shuttle/runs/2026-07"
IDENTITY = "http://camayoc.test/graph/identity"

from rdflib_guard import HAVE_RDFLIB, requires_rdflib  # noqa: F401

if HAVE_RDFLIB:  # the suites below reference `rdflib` directly
    import rdflib


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


coverage = load("query_coverage", "scripts/query_coverage.py")
promote_plane = load("promote_plane", "scripts/promote_plane.py")


def stored(name: str) -> dict:
    return json.loads((QUERIES / f"{name}.json").read_text())


def run(dataset, name: str, **params):
    """Execute a stored query's template against a DATASET, substituting params.

    Unbound OPTIONALs render as the empty string, not `str(None)` — absent and
    present-but-empty must stay distinguishable, which is most of what this
    slice is about.
    """
    template = stored(name)["template"]
    for key, value in params.items():
        template = template.replace("{" + key + "}", value)
    if "{" in template.split("WHERE")[0]:
        raise AssertionError(f"unsubstituted parameter in {name}")
    return [
        tuple("" if v is None else str(v) for v in row) for row in dataset.query(template)
    ]


def fixture_dataset():
    dataset = rdflib.Dataset()
    dataset.parse(FIXTURE, format="trig")
    return dataset


@requires_rdflib
class WorkflowQueryExecutionTests(unittest.TestCase):
    """Q1-Q5, Q7, Q8: each runs, and each returns what a human seeded for it."""

    @classmethod
    def setUpClass(cls):
        cls.dataset = fixture_dataset()

    # -- window scoping, which every query below depends on ----------------
    def test_a_window_scoped_query_reads_nothing_from_the_default_graph(self):
        """The dataset does not union its graphs. A query that lost its FROM
        answers 'nothing to report' — which is why the FROM is in the stored
        template and not left to the caller."""
        template = stored("camayoc_wf_runs_in_window")["template"]
        unscoped = template.replace("FROM <{window}> ", "").replace(
            "<{definition}>", f"<{EX}wf-release>"
        )
        self.assertEqual([], list(self.dataset.query(unscoped)))

    # -- Q1 ----------------------------------------------------------------
    def test_q1_lists_the_release_runs_in_the_hot_window_with_their_states(self):
        rows = run(
            self.dataset, "camayoc_wf_runs_in_window",
            window=HOT, definition=f"{EX}wf-release",
        )
        self.assertEqual(2, len(rows), rows)
        self.assertEqual(
            [("run-a", "published"), ("run-b", "testing")],
            [(r[0].rsplit("/", 1)[-1], r[2]) for r in rows],
        )

    def test_q1_does_not_return_runs_of_another_definition(self):
        """ex:run-c is a hotfix run in the same window. A Q1 that returned it
        would be returning every run and passing a bare non-empty assertion."""
        rows = run(
            self.dataset, "camayoc_wf_runs_in_window",
            window=HOT, definition=f"{EX}wf-release",
        )
        self.assertNotIn("run-c", " ".join(r[0] for r in rows))

    def test_q1_does_not_reach_into_the_frozen_window(self):
        """The archived run is a run of the same definition. Only the window
        keeps it out, which is the whole reason the window is a graph."""
        rows = run(
            self.dataset, "camayoc_wf_runs_in_window",
            window=HOT, definition=f"{EX}wf-release",
        )
        self.assertNotIn("run-z", " ".join(r[0] for r in rows))

    def test_q1_reads_the_frozen_window_when_asked_to(self):
        """A freeze archives the window without unbinding its IRI. If this
        returned nothing, the archive would be write-only."""
        rows = run(
            self.dataset, "camayoc_wf_runs_in_window",
            window=FROZEN, definition=f"{EX}wf-release",
        )
        self.assertEqual(1, len(rows), rows)
        self.assertIn("run-z", rows[0][0])
        self.assertEqual("failed", rows[0][2])

    # -- Q2 ----------------------------------------------------------------
    def test_q2_reports_the_state_the_run_was_in_at_that_instant(self):
        rows = run(
            self.dataset, "camayoc_wf_run_state_as_of",
            window=HOT, run=f"{EX}run-a", instant="2026-08-02T09:30:00Z",
        )
        self.assertEqual(1, len(rows), rows)
        self.assertEqual("building", rows[0][0])

    def test_q2_moves_with_the_instant_rather_than_returning_the_latest(self):
        """Three instants, three answers. A query that ignored its instant and
        returned the current state would pass the test above."""
        answers = {
            instant: run(
                self.dataset, "camayoc_wf_run_state_as_of",
                window=HOT, run=f"{EX}run-a", instant=instant,
            )[0][0]
            for instant in (
                "2026-08-02T09:00:00Z", "2026-08-02T11:59:59Z", "2026-08-02T23:00:00Z",
            )
        }
        self.assertEqual(
            {"2026-08-02T09:00:00Z": "building",
             "2026-08-02T11:59:59Z": "testing",
             "2026-08-02T23:00:00Z": "published"},
            answers,
        )

    def test_q2_returns_nothing_before_the_first_transition(self):
        """The control, and the honest answer: the run's state before anything
        transitioned it was never recorded. Returning an invented 'queued'
        would be answering from the nearest term."""
        rows = run(
            self.dataset, "camayoc_wf_run_state_as_of",
            window=HOT, run=f"{EX}run-a", instant="2026-08-01T00:00:00Z",
        )
        self.assertEqual([], rows)

    # -- Q3 ----------------------------------------------------------------
    def test_q3_replays_the_whole_transition_history_in_order(self):
        rows = run(
            self.dataset, "camayoc_wf_transition_history",
            window=HOT, definitions=DEFINITIONS, run=f"{EX}run-a",
        )
        self.assertEqual(3, len(rows), rows)
        self.assertEqual(
            [("queued", "building"), ("building", "testing"), ("testing", "published")],
            [(r[4], r[5]) for r in rows],
        )
        self.assertEqual(
            ["build the artifact", "run the suite", "publish the release"],
            [r[3] for r in rows],
        )

    def test_q3_carries_the_performer_of_each_transition(self):
        """Including the one performed by an agent with no registered key —
        Q3 reports who acted, Q7 reports whether that can be checked."""
        rows = run(
            self.dataset, "camayoc_wf_transition_history",
            window=HOT, definitions=DEFINITIONS, run=f"{EX}run-a",
        )
        self.assertEqual("agent-nokey", rows[-1][6].rsplit("/", 1)[-1])

    def test_q3_does_not_mix_in_another_runs_transitions(self):
        rows = run(
            self.dataset, "camayoc_wf_transition_history",
            window=HOT, definitions=DEFINITIONS, run=f"{EX}run-b",
        )
        self.assertEqual(2, len(rows), rows)
        self.assertTrue(all("t-b" in r[0] for r in rows), rows)

    # -- Q4 ----------------------------------------------------------------
    def test_q4_separates_the_completed_runs_from_the_open_one(self):
        rows = run(self.dataset, "camayoc_wf_window_closeout", window=HOT)
        by_run = {r[0].rsplit("/", 1)[-1]: r for r in rows}
        self.assertEqual({"run-a", "run-b", "run-c"}, set(by_run))
        self.assertEqual("completed", by_run["run-a"][3])
        self.assertEqual("succeeded", by_run["run-a"][4])
        self.assertEqual("open", by_run["run-b"][3])

    def test_q4_leaves_the_open_runs_outcome_empty_rather_than_guessing(self):
        """aegis:outcome's own rule: absence means open. An open run reported
        with an invented outcome is a decaying judgment stored as a fact."""
        rows = run(self.dataset, "camayoc_wf_window_closeout", window=HOT)
        open_row = [r for r in rows if r[3] == "open"][0]
        self.assertEqual("", open_row[4])
        self.assertEqual("", open_row[5])
        self.assertEqual("testing", open_row[2])

    def test_q4_reports_a_failed_run_as_completed_with_its_outcome(self):
        """Completed is not succeeded. The frozen window's run failed, and a
        closeout that counted it as open would misreport freezability."""
        rows = run(self.dataset, "camayoc_wf_window_closeout", window=FROZEN)
        self.assertEqual(1, len(rows), rows)
        self.assertEqual("completed", rows[0][3])
        self.assertEqual("failed", rows[0][4])

    # -- Q5 ----------------------------------------------------------------
    def test_q5_shows_the_declared_step_the_run_never_took(self):
        rows = run(
            self.dataset, "camayoc_wf_declared_vs_traversed",
            definitions=DEFINITIONS, window=HOT,
            definition=f"{EX}wf-release", run=f"{EX}run-a",
        )
        self.assertEqual(4, len(rows), rows)
        self.assertEqual(["1", "2", "3", "4"], [r[2] for r in rows])
        skipped = [r for r in rows if not r[3]]
        self.assertEqual(1, len(skipped), rows)
        self.assertEqual("sign the artifact", skipped[0][1])

    def test_q5_does_not_backfill_the_skipped_step_from_the_declaration(self):
        """The declaration says the step exists; only the transition log says
        it happened. Filling the traversal time in from the former is exactly
        the confusion between prescriptive and observed this slice polices."""
        rows = run(
            self.dataset, "camayoc_wf_declared_vs_traversed",
            definitions=DEFINITIONS, window=HOT,
            definition=f"{EX}wf-release", run=f"{EX}run-a",
        )
        sign = [r for r in rows if "sign" in r[1]][0]
        self.assertEqual("", sign[3])
        self.assertEqual("", sign[4])

    def test_q5_needs_both_graphs_and_says_so_by_returning_nothing_without_one(self):
        """Composing the knowledge plane with the window is not decoration:
        the definition outlives the window and is not frozen with it."""
        template = stored("camayoc_wf_declared_vs_traversed")["template"]
        without_definitions = (
            template.replace("FROM <{definitions}> ", "")
            .replace("{window}", HOT)
            .replace("{definition}", f"{EX}wf-release")
            .replace("{run}", f"{EX}run-a")
        )
        self.assertEqual([], list(self.dataset.query(without_definitions)))

    def test_q5_reports_a_run_that_walked_every_declared_step(self):
        rows = run(
            self.dataset, "camayoc_wf_declared_vs_traversed",
            definitions=DEFINITIONS, window=HOT,
            definition=f"{EX}wf-hotfix", run=f"{EX}run-c",
        )
        self.assertEqual(2, len(rows), rows)
        self.assertTrue(all(r[3] for r in rows), rows)

    # -- Q7 ----------------------------------------------------------------
    def test_q7_finds_both_kinds_of_unverifiable_transition_and_keeps_them_apart(self):
        rows = run(
            self.dataset, "camayoc_wf_unverifiable_transitions",
            window=HOT, identity=IDENTITY,
        )
        found = {r[0].rsplit("/", 1)[-1]: r[5] for r in rows}
        self.assertEqual(
            {"t-a3": "signed by an agent with no verifier registration",
             "t-b2": "no signature at all"},
            found,
        )

    def test_q7_does_not_flag_a_signed_transition_with_a_registered_key(self):
        """The control that matters: five of the seven transitions in the hot
        window are properly signed by a registered agent. A query returning
        all of them would pass a bare non-empty assertion."""
        rows = run(
            self.dataset, "camayoc_wf_unverifiable_transitions",
            window=HOT, identity=IDENTITY,
        )
        joined = " ".join(r[0] for r in rows)
        for clean in ("t-a1", "t-a2", "t-b1", "t-c1", "t-c2"):
            self.assertNotIn(clean, joined)

    def test_q7_without_the_identity_graph_condemns_every_transition(self):
        """The failure mode this composition prevents. Drop the identity graph
        and no registration is reachable, so every signed transition reads as
        unregistered — 'could not look' rendered as 'no key exists', which is
        the same wrong answer the plane router refuses to give."""
        template = stored("camayoc_wf_unverifiable_transitions")["template"]
        blinded = template.replace("FROM <{identity}> ", "").replace("{window}", HOT)
        self.assertEqual(7, len(list(self.dataset.query(blinded))), "all seven, not the two")

    def test_q7_reaches_the_frozen_window_because_the_keys_were_not_frozen(self):
        """The archive's transitions stay checkable precisely because the
        identity graph is dataKind identity and never goes into the pack."""
        rows = run(
            self.dataset, "camayoc_wf_unverifiable_transitions",
            window=FROZEN, identity=IDENTITY,
        )
        self.assertEqual([], rows)

    # -- Q8 ----------------------------------------------------------------
    def test_q8_composes_the_hot_and_frozen_windows_for_one_agent(self):
        rows = run(
            self.dataset, "camayoc_wf_agent_activity_across_windows",
            window=HOT, archive=FROZEN, principal=f"{EX}agent-shuttle",
            **{"from": "2026-07-01T00:00:00Z", "to": "2026-09-01T00:00:00Z"},
        )
        self.assertEqual(8, len(rows), rows)
        self.assertTrue(any("t-z" in r[0] for r in rows), "the archive half is missing")

    def test_q8_is_quietly_short_without_the_archive(self):
        """The finding the question exists for: omitting the frozen window
        does not error, it under-answers. Six instead of eight, with nothing
        to say a window was left out."""
        template = stored("camayoc_wf_agent_activity_across_windows")["template"]
        hot_only = (
            template.replace("FROM <{archive}> ", "")
            .replace("{window}", HOT)
            .replace("{principal}", f"{EX}agent-shuttle")
            .replace("{from}", "2026-07-01T00:00:00Z")
            .replace("{to}", "2026-09-01T00:00:00Z")
        )
        self.assertEqual(6, len(list(self.dataset.query(hot_only))))

    def test_q8_honours_its_time_range(self):
        rows = run(
            self.dataset, "camayoc_wf_agent_activity_across_windows",
            window=HOT, archive=FROZEN, principal=f"{EX}agent-shuttle",
            **{"from": "2026-08-10T00:00:00Z", "to": "2026-08-31T23:59:59Z"},
        )
        self.assertEqual(["t-b1", "t-b2"], [r[0].rsplit("/", 1)[-1] for r in rows])

    def test_q8_does_not_return_another_agents_transitions(self):
        rows = run(
            self.dataset, "camayoc_wf_agent_activity_across_windows",
            window=HOT, archive=FROZEN, principal=f"{EX}agent-nokey",
            **{"from": "2026-07-01T00:00:00Z", "to": "2026-09-01T00:00:00Z"},
        )
        self.assertEqual(["t-a3"], [r[0].rsplit("/", 1)[-1] for r in rows])


@requires_rdflib
class PromotionReplayTests(unittest.TestCase):
    """Q13 replayed across a real promotion, not against tuned fixture triples.

    The record under test is whatever `scripts/promote_plane.py` emits today.
    If the script's vocabulary drifts from the stored query's, this fails —
    which is the only way a query over a script's output stays true.
    """

    GRANTS = {"alice": ["crew:records"]}
    FACT = "http://camayoc.test/fixture/fact-cache-thrash"

    def replay(self, source_episode):
        episode, close = promote_plane.promote(
            subject=self.FACT,
            target_plane="crew:records",
            promoted_by="alice",
            authored_by="claude",
            reason="corroborated by two independent deploy logs",
            timestamp="2026-08-20T10:00:00Z",
            grants=self.GRANTS,
            source_episode=source_episode,
        )
        dataset = rdflib.Dataset()
        dataset.get_context(rdflib.URIRef(episode["graph"])).parse(
            data=episode["episode_body"], format="turtle"
        )
        return dataset, episode, close

    def test_q13_reports_a_closed_source_interval_after_a_real_promotion(self):
        dataset, episode, close = self.replay("episode-inferred-77")
        self.assertIsNotNone(close, "a named source episode must produce a close")
        rows = run(dataset, "camayoc_wf_plane_promotion_record", fact=self.FACT)
        self.assertEqual(1, len(rows), rows)
        plane, _record, promoted_from, promoted_into, left_open = rows[0]
        self.assertEqual(episode["graph"], plane)
        self.assertTrue(promoted_from.endswith("crew/inferred"), promoted_from)
        self.assertTrue(promoted_into.endswith("crew/records"), promoted_into)
        self.assertEqual("false", left_open)

    def test_q13_reports_an_open_source_interval_when_the_close_did_not_happen(self):
        """The arm that makes the query worth storing. Without --source-episode
        the promotion still happens and the record says the source was left
        open; a query that could not distinguish the two would certify a move
        that was actually a copy-up."""
        dataset, _episode, close = self.replay(None)
        self.assertIsNone(close)
        rows = run(dataset, "camayoc_wf_plane_promotion_record", fact=self.FACT)
        self.assertEqual("true", rows[0][4])

    def test_q13_returns_nothing_for_a_fact_that_was_never_promoted(self):
        dataset, _episode, _close = self.replay("episode-inferred-77")
        rows = run(
            dataset, "camayoc_wf_plane_promotion_record",
            fact="http://camayoc.test/fixture/fact-never-promoted",
        )
        self.assertEqual([], rows)

    def test_q13_finds_the_record_without_being_told_which_plane_holds_it(self):
        """GRAPH ?plane, not a FROM parameter: a caller asking whether a fact
        was promoted does not yet know where it was promoted TO."""
        dataset, episode, _close = self.replay("episode-inferred-77")
        template = stored("camayoc_wf_plane_promotion_record")["template"]
        self.assertNotIn("FROM", template)
        rows = run(dataset, "camayoc_wf_plane_promotion_record", fact=self.FACT)
        self.assertEqual(episode["graph"], rows[0][0])


@requires_rdflib
class FreezeAndThawReplayTests(unittest.TestCase):
    """Q14, and the half of the freeze/thaw cycle camayoc can actually replay.

    A freeze must preserve two things, and only one of them is a graph fact.
    What IS replayable here — the frozen window keeps its IRI, so its runs stay
    queryable and their signatures stay checkable — is asserted. What is NOT is
    asserted too, as a recorded gap rather than a silence: the thaw record is a
    `frozen_packs` row with `thawed_at`, a store table, and no stored query can
    reach it. Pinning the gap keeps 'nobody wrote the query' from being mistaken
    for 'the question is answered'.
    """

    @classmethod
    def setUpClass(cls):
        cls.dataset = fixture_dataset()

    def test_freezing_a_window_does_not_unbind_its_iri(self):
        rows = run(
            self.dataset, "camayoc_wf_transition_history",
            window=FROZEN, definitions=DEFINITIONS, run=f"{EX}run-z",
        )
        self.assertEqual(2, len(rows), rows)
        self.assertEqual("failed", rows[-1][5])

    def test_no_stored_query_claims_to_answer_the_thaw_question(self):
        result = coverage.report("workflow-and-archive")
        row = [r for r in result["rows"] if r["question"] == 14][0]
        self.assertEqual("GAP", row["state"])
        self.assertIn("frozen_packs", row["gap"])
        self.assertTrue(row["needs"])


class WorkflowCoverageTests(unittest.TestCase):
    """The slice's coverage figure, checked the way the other two slices are."""

    def test_every_stored_query_is_grounded_in_the_ontology(self):
        result = coverage.report("workflow-and-archive")
        ungrounded = [r for r in result["rows"] if r["state"] == "UNGROUNDED"]
        self.assertEqual([], ungrounded, ungrounded)

    def test_no_question_claims_a_query_that_is_not_on_disk(self):
        result = coverage.report("workflow-and-archive")
        missing = [r for r in result["rows"] if r["state"] == "MISSING"]
        self.assertEqual([], missing, missing)

    def test_reused_quipu_terms_count_as_grounded_and_typos_still_do_not(self):
        """The grounding check learned to read `rdfs:isDefinedBy`, and that
        must not have turned into 'anything unrecognised passes'. Q7's query
        reuses three quipu-owned terms; a fourth, invented one must still be
        caught."""
        terms = coverage.ontology_terms()
        self.assertLessEqual(
            {"signature", "VerifierRegistration", "verifier"}, terms["aegis"]
        )
        self.assertNotIn("verifierRegistrationn", terms["aegis"])
        self.assertNotIn("planePromotion", terms["aegis"])

    def test_coverage_is_partial_and_the_number_is_reported_honestly(self):
        """Pins the figure: 8 of 14. The six that remain are one boundary and
        a real one — graph kinds, freeze state, thaw records and composed
        dataset labels are quipu meta-graph and store-table properties served
        by GET /graphs, not triples SPARQL can reach (Q9-Q12, Q14) — plus Q6,
        which asks whether a signature VERIFIES and no SPARQL query can say."""
        result = coverage.report("workflow-and-archive")
        self.assertEqual("Partial", result["verdict"])
        self.assertEqual(8, result["covered"])
        self.assertEqual(14, result["total"])
        self.assertEqual(0, result["unwritten"])
        self.assertEqual(6, result["gaps"])


if __name__ == "__main__":
    unittest.main()
