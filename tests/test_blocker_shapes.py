"""The checkable-blocker shapes, against quipu's own SHACL engine (aegis-c0awwp).

Skipped when no `quipu` binary is on PATH; every arm below was also run by hand
against quipu 0.8.1 when the shapes landed.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHAPES = ROOT / "shapes" / "core.shapes.ttl"
PREFIX = ("@prefix aegis: <http://aegis.gastown.local/ontology/> . "
          "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> . "
          "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n")
WORK = 'aegis:w1 a aegis:WorkItem ; rdfs:label "w1" ; aegis:sourceKind "observed"'
BLOCKER = 'a aegis:Blocker ; rdfs:label "b" ; aegis:sourceKind "declared" ; aegis:blockerEvidence "stated"'


@unittest.skipUnless(shutil.which("quipu"), "needs a quipu binary on PATH")
class BlockerShapes(unittest.TestCase):
    def valid(self, body: str) -> bool:
        with tempfile.NamedTemporaryFile("w", suffix=".ttl", delete=False) as fh:
            fh.write(PREFIX + body)
        out = subprocess.run(["quipu", "validate", "--shapes", str(SHAPES), "--data", fh.name],
                             capture_output=True, text=True)
        Path(fh.name).unlink()
        return out.stdout.lstrip().startswith("valid")

    def test_a_workitem_may_wait_on_a_workitem(self):
        self.assertTrue(self.valid(f'{WORK} ; aegis:blockedOn aegis:w2 . aegis:w2 a aegis:WorkItem ; '
                                   'rdfs:label "w2" ; aegis:sourceKind "observed" .'))

    def test_a_workitem_may_wait_on_a_checkable_condition(self):
        self.assertTrue(self.valid(f'{WORK} ; aegis:blockedOn aegis:b . aegis:b {BLOCKER} ; '
                                   'aegis:blockerKind "pr-merged" ; aegis:resolutionQuery "ASK {{}}" .'))

    def test_an_unkinded_stated_blocker_is_still_valid(self):
        self.assertTrue(self.valid(f'aegis:b {BLOCKER} .'))

    def test_a_kinded_blocker_with_no_resolution_is_refused(self):
        self.assertFalse(self.valid(f'aegis:b {BLOCKER} ; aegis:blockerKind "date" .'))

    def test_a_kinded_blocker_with_two_resolutions_is_refused(self):
        self.assertFalse(self.valid(f'aegis:b {BLOCKER} ; aegis:blockerKind "date" ; '
                                    'aegis:resolvesOn "2026-10-01"^^xsd:date ; aegis:resolutionQuery "ASK {{}}" .'))

    def test_an_unknown_kind_is_refused(self):
        self.assertFalse(self.valid(f'aegis:b {BLOCKER} ; aegis:blockerKind "vibes" ; '
                                    'aegis:resolutionQuery "ASK {{}}" .'))

    def test_blockedOn_to_anything_else_is_refused(self):
        self.assertFalse(self.valid(f'{WORK} ; aegis:blockedOn aegis:d1 . aegis:d1 a aegis:Decision .'))


if __name__ == "__main__":
    unittest.main()
