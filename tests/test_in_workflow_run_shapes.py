"""aegis:inWorkflowRun, the WorkItem -> WorkflowRun link (aegis-1i5h1j C2).

Shuttle creates a work item for a step of its run and advances the run when
the item closes, so the item must name exactly one run the graph holds.
Validated by quipu's own SHACL engine via the shared quipu_bin_guard.
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
WORK = 'aegis:w1 a aegis:WorkItem ; rdfs:label "w1" ; aegis:sourceKind "observed"'
RUN = 'aegis:r1 a aegis:WorkflowRun .'


@requires_quipu
class InWorkflowRunShapes(unittest.TestCase):
    def valid(self, body: str) -> bool:
        with tempfile.NamedTemporaryFile("w", suffix=".ttl", delete=False) as fh:
            fh.write(PREFIX + body)
        out = subprocess.run([str(QUIPU), "validate", "--shapes", str(SHAPES), "--data", fh.name],
                             capture_output=True, text=True)
        Path(fh.name).unlink()
        return out.stdout.lstrip().startswith("valid")

    def test_a_work_item_may_name_its_run(self):
        self.assertTrue(self.valid(f'{WORK} ; aegis:inWorkflowRun aegis:r1 . {RUN}'))

    def test_the_link_is_optional(self):
        self.assertTrue(self.valid(f'{WORK} .'))

    def test_a_target_that_is_not_a_run_is_refused(self):
        # The wrong-type target must be VALID ON ITS OWN, or the refusal could
        # come from the target's own shape and pass with this constraint gone.
        other = 'aegis:w2 a aegis:WorkItem ; rdfs:label "w2" ; aegis:sourceKind "observed" .'
        self.assertTrue(self.valid(other), "control: the target alone must be valid")
        self.assertFalse(self.valid(f'{WORK} ; aegis:inWorkflowRun aegis:w2 . {other}'))

    def test_a_work_item_belongs_to_at_most_one_run(self):
        self.assertFalse(self.valid(f'{WORK} ; aegis:inWorkflowRun aegis:r1 , aegis:r2 . {RUN} '
                                    'aegis:r2 a aegis:WorkflowRun .'))


if __name__ == "__main__":
    unittest.main()
