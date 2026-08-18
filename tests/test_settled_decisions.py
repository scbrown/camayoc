"""Settled-decision collision check — camayoc-7lt."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sd = load("settled_decisions")

CORPUS = [
    sd.SettledDecision(
        iri="http://ex/d/trunk",
        text="We use trunk-based development with short-lived branches",
        decided_by="stiwi",
    ),
    sd.SettledDecision(
        iri="http://ex/d/rust",
        text="Backend services are written in Rust",
        decided_by="ian",
    ),
]


class OutcomeTests(unittest.TestCase):
    def test_a_near_duplicate_of_a_settled_decision_is_surfaced(self):
        v = sd.check("we use trunk based development with short lived branches", CORPUS)
        self.assertIn(v["outcome"], ("advisory", "escalate"))
        self.assertEqual("http://ex/d/trunk", v["matches"][0]["iri"])

    def test_an_unrelated_proposal_is_clear(self):
        """The control. Without it, every collision test could pass because
        everything collides."""
        v = sd.check("adopt a four day working week for the support rota", CORPUS)
        self.assertEqual("clear", v["outcome"])
        self.assertEqual([], v["matches"])

    def test_no_corpus_is_not_the_same_outcome_as_clear(self):
        """Scoring against zero settled decisions produces no matches and would
        otherwise render exactly like a clean result."""
        v = sd.check("anything at all", [])
        self.assertEqual("no_corpus", v["outcome"])
        self.assertNotEqual("clear", v["outcome"])
        self.assertIn("not 'no collision'", v["note"])

    def test_the_match_names_who_decided_it(self):
        """A collision the reader cannot attribute is not actionable — the
        point is to send them to the person who settled it."""
        v = sd.check("trunk based development with short lived branches", CORPUS)
        self.assertEqual("stiwi", v["matches"][0]["decided_by"])

    def test_a_strong_match_escalates_and_a_weak_one_only_advises(self):
        weak = sd.check("development branches", CORPUS, advisory=0.05, escalate=0.99)
        self.assertEqual("advisory", weak["outcome"])
        strong = sd.check(
            "We use trunk-based development with short-lived branches",
            CORPUS,
            advisory=0.05,
            escalate=0.10,
        )
        self.assertEqual("escalate", strong["outcome"])


class VerdictShapeTests(unittest.TestCase):
    """The falsifiability discipline the bead requires, and that its sibling
    camayoc-b6h established."""

    def test_every_verdict_carries_its_method_and_denies_being_semantic(self):
        for v in (sd.check("x", CORPUS), sd.check("x", [])):
            self.assertEqual(sd.METHOD, v["method"])
            self.assertIs(False, v["semantic"])

    def test_the_method_label_claims_no_meaning_awareness(self):
        """The inverse of camayoc's own rule that inferred facts never
        masquerade: a lexical matcher must not be labelled as understanding."""
        for word in ("semantic", "meaning", "embedding", "understand", "concept"):
            self.assertNotIn(word, sd.METHOD.lower())

    def test_every_verdict_carries_thresholds_and_a_corpus_watermark(self):
        v = sd.check("x", CORPUS)
        self.assertIn("advisory_threshold", v)
        self.assertIn("escalate_threshold", v)
        self.assertEqual(len(CORPUS), v["corpus_size"])
        self.assertTrue(v["corpus_watermark"].startswith("sha256:"))

    def test_the_watermark_is_order_independent_but_content_sensitive(self):
        self.assertEqual(sd.watermark(CORPUS), sd.watermark(list(reversed(CORPUS))))
        extra = CORPUS + [
            sd.SettledDecision(iri="http://ex/d/new", text="something else", decided_by="x")
        ]
        self.assertNotEqual(sd.watermark(CORPUS), sd.watermark(extra))


class PlaneRoutingTests(unittest.TestCase):
    """Why this bead waited for the planes."""

    def test_the_recorded_verdict_lands_in_the_inferred_plane(self):
        """A model-adjacent judgment ABOUT a human's decision is inferred.
        Writing it into crew:declared beside the decision it comments on would
        make a machine's opinion indistinguishable from the human's statement."""
        ep = sd.verdict_episode("some proposal", sd.check("some proposal", CORPUS),
                                "claude", "2026-01-01T00:00:00Z")
        self.assertEqual(sd.planes.plane_for("inferred"), ep["graph"])
        self.assertNotEqual(sd.planes.plane_for("declared"), ep["graph"])

    def test_the_recorded_verdict_is_tagged_inferred(self):
        ep = sd.verdict_episode("p", sd.check("p", CORPUS), "claude", "2026-01-01T00:00:00Z")
        self.assertIn('aegis:sourceKind      "inferred"', ep["episode_body"])

    def test_the_recorded_verdict_names_its_falsifier(self):
        """camayoc's shape rule applied to camayoc's own output."""
        ep = sd.verdict_episode("p", sd.check("p", CORPUS), "claude", "2026-01-01T00:00:00Z")
        self.assertIn("falsifier", ep["episode_body"])


class LoadTests(unittest.TestCase):
    def test_declared_decisions_load_from_an_export(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "decl.json"
            p.write_text(json.dumps([
                {"iri": "http://ex/d/1", "text": "a decision", "decided_by": "stiwi"}
            ]))
            loaded = sd.load_declared(p)
            self.assertEqual(1, len(loaded))
            self.assertEqual("stiwi", loaded[0].decided_by)

    def test_a_missing_decider_reads_as_unknown_not_as_a_name(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "decl.json"
            p.write_text(json.dumps([{"iri": "http://ex/d/1", "text": "a decision"}]))
            self.assertEqual("unknown", sd.load_declared(p)[0].decided_by)


if __name__ == "__main__":
    sys.exit(unittest.main())
