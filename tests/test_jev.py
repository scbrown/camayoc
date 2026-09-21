"""Jev client + JevScorer — the promises that must hold before any verdict is trusted.

No network. A fake transport plays the API. What is pinned:
  * no key -> JevUnavailable, never a silent lexical answer under a Jev label;
  * the request carries the state and every option verbatim (a verdict must
    show its question);
  * the scorer's method/semantic labels come from the SAME object that scored;
  * when "none-of-these" wins, coverage is Empty (NO COVERAGE) no matter how
    high another option's probability is — Jev cannot abstain, so we do it for it;
  * one Choice call per asked question, not one per suite entry.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import competency  # noqa: E402
import jev  # noqa: E402


def q(id_, text, source):
    return competency.Question(id=id_, number=int(id_.split("#")[1]), text=text,
                               section="s", source=source, line=1, parameters=[])


def suite():
    return [
        q("a#1", "What did we decide about X, and why?", "a"),
        q("a#2", "Which decisions were made under work item W?", "a"),
        q("b#1", "Which metrics are reachable for subject S?", "b"),
    ]


class FakeTransport:
    def __init__(self, choice: str, probs: dict, confidence: float = 0.8):
        self.calls: list[dict] = []
        self.choice, self.probs, self.confidence = choice, probs, confidence

    def __call__(self, body, key):
        self.calls.append(body)
        qid = next(iter(body["questions"]))
        return {"model": "jev-latest", "answers": {qid: {"type": "choice", "choice": self.choice,
                "probabilities": self.probs, "confidence": self.confidence}},
                "usage": {"input_tokens": 10, "output_tokens": 0}}


class ClientTests(unittest.TestCase):
    def test_no_key_is_loud_not_lexical(self):
        os.environ.pop("TYPESAFE_API_KEY", None)
        with self.assertRaises(jev.JevUnavailable):
            jev.JevClient()

    def test_choice_limits_and_none_option(self):
        q = jev.JevClient.choice_q("pick", {"x": "X"}, none_text="nothing fits")
        self.assertEqual(set(q["criteria"]), {"x", jev.NONE_OPTION})
        with self.assertRaises(ValueError):
            jev.JevClient.choice_q("pick", {str(i): "o" for i in range(256)})

    def test_request_carries_state_and_options_verbatim(self):
        t = FakeTransport("x", {"x": 0.9, jev.NONE_OPTION: 0.1})
        c = jev.JevClient(api_key="k", transport=t)
        out = c.choice("the state", "which?", {"x": "option X"}, none_text="none")
        self.assertEqual(t.calls[0]["state"], "the state")
        self.assertEqual(t.calls[0]["questions"]["q"]["criteria"]["x"], "option X")
        self.assertEqual(out["choice"], "x")
        self.assertEqual(out["request"], t.calls[0])


class ScorerTests(unittest.TestCase):
    def test_labels_come_from_the_scorer_that_ran(self):
        t = FakeTransport("a#1", {"a#1": 0.7, "a#2": 0.2, "b#1": 0.05, jev.NONE_OPTION: 0.05})
        s = competency.JevScorer(jev.JevClient(api_key="k", transport=t))
        v = competency.assess("what did we decide about X", suite(), scorer=s)
        self.assertEqual(v["method"], competency.JEV_METHOD)
        self.assertTrue(v["semantic"])
        self.assertEqual(v["matches"][0]["id"], "a#1")
        self.assertAlmostEqual(v["best_score"], 0.7)
        self.assertEqual(v["jev"]["confidence"], 0.8)
        self.assertEqual(v["jev"]["none_probability"], 0.05)

    def test_one_call_per_asked_question(self):
        t = FakeTransport("a#1", {"a#1": 0.7, "a#2": 0.2, "b#1": 0.05, jev.NONE_OPTION: 0.05})
        s = competency.JevScorer(jev.JevClient(api_key="k", transport=t))
        competency.assess("what did we decide about X", suite(), scorer=s)
        self.assertEqual(len(t.calls), 1)
        self.assertEqual(len(t.calls[0]["questions"]["coverage"]["criteria"]), 4)

    def test_none_winning_is_no_coverage_even_with_a_high_runner_up(self):
        t = FakeTransport(jev.NONE_OPTION, {"a#1": 0.45, "a#2": 0.05, "b#1": 0.02, jev.NONE_OPTION: 0.48})
        s = competency.JevScorer(jev.JevClient(api_key="k", transport=t))
        v = competency.assess("how do I bake bread", suite(), scorer=s, floor=0.12, full=0.34)
        self.assertEqual(v["coverage"], "Empty")
        self.assertTrue(v["gap"])
        self.assertTrue(v["jev"]["abstained"])

    def test_the_verdict_shows_its_question(self):
        t = FakeTransport("a#1", {"a#1": 0.9, "a#2": 0.05, "b#1": 0.02, jev.NONE_OPTION: 0.03})
        s = competency.JevScorer(jev.JevClient(api_key="k", transport=t))
        v = competency.assess("decide X", suite(), scorer=s)
        self.assertIn("instructions", v["jev"])
        self.assertEqual(v["jev"]["model"], "jev-latest")


if __name__ == "__main__":
    unittest.main()
