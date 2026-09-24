"""The review-age shape, against quipu's own SHACL engine (aegis-kxjack).

Uses tests/quipu_bin_guard.py like every quipu-gated suite: it RUNS in the
integration job (a skip there fails the job) and skips elsewhere with the reason.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from quipu_bin_guard import QUIPU, requires_quipu

ROOT = Path(__file__).resolve().parents[1]
SHAPES = ROOT / "shapes" / "core.shapes.ttl"
PREFIX = ("@prefix aegis: <http://aegis.gastown.local/ontology/> . "
          "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n")


@requires_quipu
class ReviewAgeShape(unittest.TestCase):
    def valid(self, body: str) -> bool:
        with tempfile.NamedTemporaryFile("w", suffix=".ttl", delete=False) as fh:
            fh.write(PREFIX + body)
        out = subprocess.run([str(QUIPU), "validate", "--shapes", str(SHAPES), "--data", fh.name],
                             capture_output=True, text=True)
        Path(fh.name).unlink()
        return out.stdout.lstrip().startswith("valid")

    def test_any_entity_may_declare_a_readable_age(self):
        self.assertTrue(self.valid('aegis:fact1 rdfs:label "a claim" ; aegis:reviewAfter "2026-10-01T00:00:00Z" .'))
        self.assertTrue(self.valid('aegis:fact1 rdfs:label "a claim" ; aegis:reviewAfter "2026-10-01" .'))
        self.assertTrue(self.valid('aegis:fact1 rdfs:label "a claim" ; aegis:maxAge "P14D" .'))
        self.assertTrue(self.valid('aegis:fact1 rdfs:label "a claim" ; aegis:maxAge "PT12H" .'))

    def test_an_unreadable_instant_is_refused(self):
        self.assertFalse(self.valid('aegis:fact1 aegis:reviewAfter "next tuesday" .'))

    def test_an_ambiguous_or_malformed_duration_is_refused(self):
        self.assertFalse(self.valid('aegis:fact1 aegis:maxAge "P1M" .'))
        self.assertFalse(self.valid('aegis:fact1 aegis:maxAge "30 days" .'))
        for bad in ("P", "PT", "P1DT"):   # sattler, review of #28: the writer must refuse what the reader cannot use
            self.assertFalse(self.valid(f'aegis:fact1 aegis:maxAge "{bad}" .'), bad)
        self.assertTrue(self.valid('aegis:fact1 aegis:maxAge "P1DT2H30M" .'))

    def test_two_review_instants_are_refused(self):
        self.assertFalse(self.valid('aegis:fact1 aegis:reviewAfter "2026-10-01", "2026-11-01" .'))

    def test_an_entity_with_no_age_is_untouched(self):
        self.assertTrue(self.valid('aegis:fact2 rdfs:label "no age" .'))


if __name__ == "__main__":
    unittest.main()
