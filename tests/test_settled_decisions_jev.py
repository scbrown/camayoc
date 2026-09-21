"""The Jev arm of the settled-decision check (aegis-4hhqoe.2).

What is pinned, and why each one has a way of going wrong quietly:
  * NOULS, not a choice — a proposal may collide with TWO settled decisions or
    with none, and a choice can express neither;
  * the verdict shape is IDENTICAL to the lexical arm, so no consumer branches;
  * `no_corpus` survives on this arm too — scoring against zero decisions is
    not "no collision";
  * NO lexical fallback: no client -> raise, never a lexical number wearing a
    Jev method string;
  * the episode records the verdict's OWN method (it used to hardcode the
    lexical constant, which would have labelled every Jev verdict a lie);
  * batching covers >50 decisions and loses none of them;
  * usage is summed ACROSS batches, not taken from the last one.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import settled_decisions as sd  # noqa: E402


def corpus(n=3):
    return [sd.SettledDecision(iri=f"urn:d{i}", text=f"decision {i}", decided_by="stiwi")
            for i in range(n)]


class FakeClient:
    """Plays Jev. `by_index` maps a DECISION's global index -> probability.

    Keyed off the decision text carried in each question, NOT off the question
    id. Question ids are batch-local (q0..qN within each request), so keying on
    them would silently address the wrong decision in every batch after the
    first — which is exactly the binding this fake exists to test.
    """

    def __init__(self, by_index=None, default=0.05):
        self.by_index = by_index or {}
        self.default = default
        self.requests: list[dict] = []

    def ask(self, state, questions):
        self.requests.append({"state": state, "questions": questions})
        answers = {}
        for qid, q in questions.items():
            idx = int(re.search(r"The settled decision: decision (\d+)",
                                q["instructions"]).group(1))
            answers[qid] = {"noul": self.by_index.get(idx, self.default)}
        return {"answers": answers, "model": "jev-1.13.0",
                "usage": {"input_tokens": 10, "output_tokens": 2},
                "request": {}}


class ShapeMatchesTheLexicalArm(unittest.TestCase):
    def test_same_keys_so_no_consumer_has_to_branch(self):
        lex = sd.check("x", corpus())
        jv = sd.check_jev("x", corpus(), FakeClient())
        self.assertTrue(set(lex).issubset(set(jv)), set(lex) - set(jv))

    def test_it_declares_itself_semantic_and_names_its_method(self):
        v = sd.check_jev("x", corpus(), FakeClient())
        self.assertTrue(v["semantic"])
        self.assertEqual(v["method"], "jev-latest-noul-v1")
        self.assertNotEqual(v["method"], sd.METHOD)

    def test_no_corpus_is_not_clear_on_this_arm_either(self):
        v = sd.check_jev("x", [], FakeClient())
        self.assertEqual(v["outcome"], "no_corpus")
        self.assertEqual(v["method"], "jev-latest-noul-v1")


class OutcomesFollowTheProbabilities(unittest.TestCase):
    def test_all_low_is_clear(self):
        v = sd.check_jev("x", corpus(), FakeClient(default=0.02))
        self.assertEqual(v["outcome"], "clear")
        self.assertEqual(v["matches"], [])

    def test_mid_is_advisory(self):
        v = sd.check_jev("x", corpus(), FakeClient({1: 0.62}))
        self.assertEqual(v["outcome"], "advisory")
        self.assertEqual([m["iri"] for m in v["matches"]], ["urn:d1"])

    def test_high_is_escalate(self):
        v = sd.check_jev("x", corpus(), FakeClient({2: 0.93}))
        self.assertEqual(v["outcome"], "escalate")
        self.assertEqual(v["matches"][0]["level"], "escalate")

    def test_TWO_simultaneous_collisions_are_both_reported(self):
        # The reason this arm uses nouls and not a choice. A choice would have
        # forced one winner and hidden the second.
        v = sd.check_jev("x", corpus(4), FakeClient({0: 0.91, 3: 0.88}))
        self.assertEqual(sorted(m["iri"] for m in v["matches"]), ["urn:d0", "urn:d3"])

    def test_matches_are_ordered_strongest_first(self):
        v = sd.check_jev("x", corpus(4), FakeClient({0: 0.55, 3: 0.97}))
        self.assertEqual([m["iri"] for m in v["matches"]], ["urn:d3", "urn:d0"])


class NoSilentFallback(unittest.TestCase):
    def test_no_client_raises_rather_than_scoring_lexically(self):
        with self.assertRaises(ValueError):
            sd.check_jev("x", corpus(), None)


class Batching(unittest.TestCase):
    def test_more_than_one_batch_is_issued_and_nothing_is_dropped(self):
        n = sd.MAX_NOULS_PER_REQUEST * 2 + 7
        c = FakeClient()
        v = sd.check_jev("x", corpus(n), c)
        self.assertEqual(len(c.requests), 3)
        self.assertEqual(v["corpus_size"], n)
        # every decision was actually asked about exactly once
        asked = sum(len(r["questions"]) for r in c.requests)
        self.assertEqual(asked, n)

    def test_usage_is_summed_across_batches_not_taken_from_the_last(self):
        n = sd.MAX_NOULS_PER_REQUEST * 2 + 1   # 3 batches
        v = sd.check_jev("x", corpus(n), FakeClient())
        self.assertEqual(v["usage"]["input_tokens"], 30)

    def test_a_match_in_a_LATER_batch_is_still_found(self):
        n = sd.MAX_NOULS_PER_REQUEST + 5
        v = sd.check_jev("x", corpus(n), FakeClient({n - 1: 0.96}))
        self.assertEqual(v["outcome"], "escalate")
        self.assertEqual(v["matches"][0]["iri"], f"urn:d{n - 1}")


class TheQuestionIsHonest(unittest.TestCase):
    def test_each_noul_carries_its_own_settled_decision(self):
        c = FakeClient()
        sd.check_jev("proposal text", corpus(2), c)
        qs = c.requests[0]["questions"]
        self.assertEqual(c.requests[0]["state"], "proposal text")
        texts = [q["instructions"] for q in qs.values()]
        self.assertTrue(any("decision 0" in t for t in texts))
        self.assertTrue(any("decision 1" in t for t in texts))

    def test_the_abstain_direction_is_stated_in_the_question(self):
        c = FakeClient()
        sd.check_jev("x", corpus(1), c)
        instructions = next(iter(c.requests[0]["questions"].values()))["instructions"]
        self.assertIn("answer no", instructions.lower())

    def test_the_verdict_carries_the_instructions_it_asked(self):
        v = sd.check_jev("x", corpus(), FakeClient())
        self.assertIn("DUPLICATE", v["instructions"])


class TheEpisodeDoesNotLieAboutItsMethod(unittest.TestCase):
    """Regression: verdict_episode interpolated the module-level lexical METHOD
    constant, so a Jev verdict would have been recorded as lexical-jaccard-v1 —
    the exact 'verdict whose method is a lie' this module's docstring forbids."""

    def test_jev_verdict_records_the_jev_method(self):
        v = sd.check_jev("x", corpus(), FakeClient())
        ep = sd.verdict_episode("x", v, "wu", "2026-09-21T00:00:00Z")
        self.assertIn('camayoc:method        "jev-latest-noul-v1"', ep["episode_body"])
        self.assertNotIn("lexical-jaccard-v1", ep["episode_body"].split("camayoc:verdict")[0])

    def test_lexical_verdict_still_records_the_lexical_method(self):
        v = sd.check("x", corpus())
        ep = sd.verdict_episode("x", v, "wu", "2026-09-21T00:00:00Z")
        self.assertIn('camayoc:method        "lexical-jaccard-v1"', ep["episode_body"])

    def test_either_arm_lands_in_the_inferred_plane(self):
        for v in (sd.check("x", corpus()), sd.check_jev("x", corpus(), FakeClient())):
            ep = sd.verdict_episode("x", v, "wu", "2026-09-21T00:00:00Z")
            self.assertIn("inferred", ep["episode_body"])


class ThresholdsAreNotSharedBetweenArms(unittest.TestCase):
    def test_the_jev_defaults_are_distinct_from_the_jaccard_ones(self):
        # A Jaccard overlap and a probability are different scales; reusing the
        # numbers would apply a lexical calibration to a model score.
        self.assertNotEqual((sd.JEV_ADVISORY, sd.JEV_ESCALATE), (sd.ADVISORY, sd.ESCALATE))

    def test_the_verdict_reports_the_thresholds_it_used(self):
        v = sd.check_jev("x", corpus(), FakeClient(), advisory=0.3, escalate=0.7)
        self.assertEqual((v["advisory_threshold"], v["escalate_threshold"]), (0.3, 0.7))


if __name__ == "__main__":
    unittest.main()
