"""The checkable-blocker shapes, against quipu's own SHACL engine (aegis-c0awwp).

The quipu CLI is found by tests/quipu_bin_guard.py, the one rule all
quipu-gated suites share: QUIPU_BIN is the integration job's promise, so there
this suite RUNS (a skip there fails the job), and elsewhere it skips with the
reason. Every arm was also run by hand against quipu 0.8.1.
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
          "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> . "
          "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n")
WORK = 'aegis:w1 a aegis:WorkItem ; rdfs:label "w1" ; aegis:sourceKind "observed"'
BLOCKER = 'a aegis:Blocker ; rdfs:label "b" ; aegis:sourceKind "declared" ; aegis:blockerEvidence "stated"'


@requires_quipu
class BlockerShapes(unittest.TestCase):
    def valid(self, body: str) -> bool:
        with tempfile.NamedTemporaryFile("w", suffix=".ttl", delete=False) as fh:
            fh.write(PREFIX + body)
        out = subprocess.run([str(QUIPU), "validate", "--shapes", str(SHAPES), "--data", fh.name],
                             capture_output=True, text=True)
        Path(fh.name).unlink()
        return out.stdout.lstrip().startswith("valid")

    def test_a_workitem_may_wait_on_a_workitem(self):
        self.assertTrue(self.valid(f'{WORK} ; aegis:blockedOn aegis:w2 . aegis:w2 a aegis:WorkItem ; '
                                   'rdfs:label "w2" ; aegis:sourceKind "observed" .'))

    def test_a_workitem_may_wait_on_a_checkable_condition(self):
        self.assertTrue(self.valid(f'{WORK} ; aegis:blockedOn aegis:b . aegis:b {BLOCKER} ; '
                                   'aegis:blockerKind "pr-merged" ; aegis:prRef "scbrown/quipu#274" .'))

    def test_an_unkinded_stated_blocker_is_still_valid(self):
        self.assertTrue(self.valid(f'aegis:b {BLOCKER} .'))

    def test_a_kinded_blocker_with_no_resolution_is_refused(self):
        self.assertFalse(self.valid(f'aegis:b {BLOCKER} ; aegis:blockerKind "date" .'))

    def test_each_kind_needs_its_own_probe_parameters(self):
        self.assertTrue(self.valid(f'aegis:b {BLOCKER} ; aegis:blockerKind "pr-merged" ; aegis:prRef "scbrown/quipu#274" .'))
        self.assertFalse(self.valid(f'aegis:b {BLOCKER} ; aegis:blockerKind "pr-merged" ; aegis:prRef "quipu 274" .'))
        self.assertTrue(self.valid(f'aegis:b {BLOCKER} ; aegis:blockerKind "release-installed" ; '
                                   'aegis:tool "yupana" ; aegis:minVersion "0.10.0" .'))
        self.assertTrue(self.valid(f'aegis:b {BLOCKER} ; aegis:blockerKind "ci-green" ; aegis:repoRef "scbrown/quipu@main" .'))

    def test_a_shell_command_in_a_probe_parameter_is_refused(self):
        self.assertFalse(self.valid(f'aegis:b {BLOCKER} ; aegis:blockerKind "release-installed" ; '
                                    'aegis:tool "yupana; rm -rf ~" ; aegis:minVersion "0.10.0" .'))

    def test_an_unknown_kind_is_refused(self):
        self.assertFalse(self.valid(f'aegis:b {BLOCKER} ; aegis:blockerKind "vibes" ; '
                                    'aegis:resolutionQuery "ASK {{}}" .'))

    def test_blockedOn_to_anything_else_is_refused(self):
        self.assertFalse(self.valid(f'{WORK} ; aegis:blockedOn aegis:d1 . aegis:d1 a aegis:Decision .'))


if __name__ == "__main__":
    unittest.main()
