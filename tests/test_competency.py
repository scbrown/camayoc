"""NO COVERAGE is an outcome, not a low score — camayoc-b6h.

The bead's discipline is that a question the ontology cannot answer must be
reported as a gap, never silently answered from the nearest term. That is a
behaviour, and behaviours need tests that watch them fail.

`scripts/competency.py` implements the half of b6h that needs no model: parsing
the suite (nothing can be embedded until it parses), the verdict shape, and a
deterministic matcher. The embedding matcher is blocked — `models/all-MiniLM-L6-v2`
in the sibling repo has `tokenizer.json` and no weights, because the xet CDN the
download redirects to answers 403 (na-6td). That blocks scoring quality, not the
discipline.

Two tests below are the ones worth reading: `test_a_paraphrase_is_missed`, which
pins the lexical matcher's real failure mode rather than pretending it does not
have one, and `test_the_method_label_never_claims_to_be_semantic`, which is the
thing that keeps this honest as it changes.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE_DIR = ROOT / "competency"


def _module():
    spec = importlib.util.spec_from_file_location("competency", ROOT / "scripts" / "competency.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: the dataclass resolves its annotations through
    # sys.modules, and `from __future__ import annotations` makes that lookup
    # mandatory rather than incidental.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


competency = _module()


class SuiteParsingTests(unittest.TestCase):
    """The suite has to be machine-readable before any matcher can run."""

    def setUp(self):
        self.suite = competency.parse_suite(SUITE_DIR)

    def test_the_shipped_suite_parses(self):
        self.assertTrue(self.suite)
        # Every file contributes; a parser that silently drops one would still
        # look like it worked.
        sources = {q.source for q in self.suite}
        self.assertEqual({p.name for p in SUITE_DIR.glob("*.md")}, sources)

    def test_ids_are_unique_because_numbers_are_not(self):
        """Numbers restart per file and skip (metrics runs 1-11 then 22-23)."""
        ids = [q.id for q in self.suite]
        self.assertEqual(len(ids), len(set(ids)))

    def test_acceptance_sections_are_not_questions(self):
        """'The slice is done when 1-12 run as named queries' is not a question.

        It contains numbered references and would otherwise be scored against.
        """
        for question in self.suite:
            self.assertNotIn("acceptance", question.section.lower())

    def test_a_wrapped_question_is_joined_not_truncated(self):
        """crew-task-lifecycle#9 spans two lines; half a question scores wrong."""
        ninth = next(q for q in self.suite if q.id == "crew-task-lifecycle#9")
        self.assertIn("created, assigned, worked", ninth.text)
        self.assertTrue(ninth.text.rstrip().endswith("?"))

    def test_parameters_are_extracted(self):
        tenth = next(q for q in self.suite if q.id == "crew-task-lifecycle#10")
        self.assertEqual(["principal", "time-window"], tenth.parameters)

    def test_parameters_do_not_contribute_to_a_match(self):
        """`<work-item>` is a slot, not a word.

        Two unrelated questions sharing a parameter name must not score as
        similar for that reason alone.
        """
        self.assertEqual(set(), competency.tokenize("<work-item> <principal> <date>"))


class WatermarkTests(unittest.TestCase):
    def test_the_watermark_moves_when_the_suite_does(self):
        """A verdict is unreadable later without knowing what it scored against."""
        suite = competency.parse_suite(SUITE_DIR)
        before = competency.watermark(suite)

        grown = suite + [
            competency.Question(
                id="x#1", number=1, text="A new question", section="s", source="x.md", line=1
            )
        ]

        self.assertNotEqual(before, competency.watermark(grown))

    def test_the_watermark_is_order_independent(self):
        """Reordering files must not look like a changed corpus."""
        suite = competency.parse_suite(SUITE_DIR)
        self.assertEqual(competency.watermark(suite), competency.watermark(list(reversed(suite))))


class CoverageVerdictTests(unittest.TestCase):
    def setUp(self):
        self.suite = competency.parse_suite(SUITE_DIR)

    def test_a_covered_question_is_full(self):
        verdict = competency.assess(
            "What did we decide about the ingress rules, and why?", self.suite
        )
        self.assertEqual("Full", verdict["coverage"])
        self.assertFalse(verdict["gap"])
        self.assertEqual("crew-task-lifecycle#1", verdict["matches"][0]["id"])

    def test_an_uncovered_question_is_reported_as_a_gap_not_answered(self):
        """The whole point of the bead.

        The nearest term must not be presented as an answer — so the verdict
        says Empty, sets `gap`, and the matches list stays empty rather than
        offering a consolation prize.
        """
        verdict = competency.assess(
            "Which container images shipped a vulnerable openssl version?", self.suite
        )
        self.assertEqual("Empty", verdict["coverage"])
        self.assertTrue(verdict["gap"])
        self.assertEqual(0.0, verdict["best_score"])

    def test_a_related_but_unanswered_question_is_partial(self):
        """Not every miss is a gap; some are a new question worth writing."""
        verdict = competency.assess("Which decisions were escalated?", self.suite)
        self.assertEqual("Partial", verdict["coverage"])
        self.assertFalse(verdict["gap"])

    def test_a_gap_becomes_a_pitch_bead_at_p3(self):
        """b6h: gaps become candidate beads. Pitches are always P3."""
        verdict = competency.assess("Which container images shipped openssl?", self.suite)
        bead = competency.gap_bead(verdict)
        self.assertIn("-p P3", bead)
        self.assertIn("-l pitch", bead)
        self.assertIn(verdict["corpus_watermark"], bead)

    def test_an_empty_suite_does_not_report_everything_as_covered(self):
        """Degenerate input must fail toward the gap, never toward Full."""
        verdict = competency.assess("anything at all", [])
        self.assertEqual("Empty", verdict["coverage"])
        self.assertTrue(verdict["gap"])


class HonestyTests(unittest.TestCase):
    """The things that stop a word count being read as understanding."""

    def test_the_method_label_never_claims_to_be_semantic(self):
        verdict = competency.assess("anything", competency.parse_suite(SUITE_DIR))
        self.assertFalse(verdict["semantic"])
        self.assertIn("lexical", verdict["method"])
        for forbidden in ("semantic", "embedding", "meaning"):
            self.assertNotIn(forbidden, verdict["method"])

    def test_every_verdict_carries_what_is_needed_to_distrust_it(self):
        verdict = competency.assess("anything", competency.parse_suite(SUITE_DIR))
        for key in ("method", "semantic", "floor", "full", "suite_size", "corpus_watermark"):
            self.assertIn(key, verdict)

    def test_a_paraphrase_is_missed(self):
        """The lexical matcher's real failure mode, pinned rather than hidden.

        "Who is accountable for X" means what crew-task-lifecycle asks as "who
        owns X", and word overlap cannot see it. This test asserts the CURRENT
        behaviour so the limitation is visible in the suite instead of living in
        a comment nobody reads.

        It is the safe direction — a spurious gap gets filed and a human
        dismisses it, whereas answering from the nearest term is the failure the
        bead exists to prevent. When embeddings land this test should FAIL, and
        the correct response is to update it and change `METHOD`, not to relax
        the threshold until it passes today.
        """
        suite = competency.parse_suite(SUITE_DIR)
        paraphrase = competency.assess(
            "Who is accountable for this gauge and can they currently take action?", suite
        )
        direct = competency.assess(
            "Who owns `<metric>` — and is that owner currently able to act?", suite
        )

        # Note what is NOT asserted: that `direct` reaches Full. Jaccard is
        # symmetric, and metrics-and-requirements#2 carries a trailing
        # parenthetical the quote does not, so even a verbatim quote is diluted
        # by words the asker never said. Asserting Full here would have been a
        # threshold fitted to one example — see test_thresholds_are_uncalibrated.
        self.assertGreater(direct["best_score"], paraphrase["best_score"])
        self.assertNotEqual("Full", paraphrase["coverage"])
        self.assertNotEqual("Empty", direct["coverage"])

    def test_a_verbatim_short_question_scores_full(self):
        """The one calibration-free sanity check: asking the suite its own question.

        A matcher that cannot recognise an exact copy of an entry is broken
        regardless of how the thresholds are set.
        """
        suite = competency.parse_suite(SUITE_DIR)
        eighth = next(q for q in suite if q.id == "crew-task-lifecycle#8")
        verdict = competency.assess(eighth.text, suite)
        self.assertEqual("Full", verdict["coverage"])
        self.assertEqual(1.0, verdict["best_score"])

    def test_thresholds_are_uncalibrated_and_say_so(self):
        """There is no held-out set here, so the numbers are starting points.

        This pins that they are DECLARED in every verdict rather than buried,
        which is what lets a reader re-score with their own and compare.
        """
        suite = competency.parse_suite(SUITE_DIR)
        strict = competency.assess("Which decisions were escalated?", suite, floor=0.9, full=0.95)
        loose = competency.assess("Which decisions were escalated?", suite, floor=0.01, full=0.02)

        self.assertEqual("Empty", strict["coverage"])
        self.assertEqual("Full", loose["coverage"])
        self.assertEqual(strict["best_score"], loose["best_score"])
        self.assertEqual(0.9, strict["floor"])
        self.assertEqual(0.01, loose["floor"])


if __name__ == "__main__":
    unittest.main()
