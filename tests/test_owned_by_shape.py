"""aegis:ownedBy is an IRI on every subject, against quipu's own SHACL engine (aegis-j32oup).

One literal owner ("aegis-crew") among 591 IRIs was invisible to every reader that
joins the owner to a principal. Uses tests/quipu_bin_guard.py like every
quipu-gated suite.
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
class OwnedByShape(unittest.TestCase):
    def valid(self, body: str) -> bool:
        with tempfile.NamedTemporaryFile("w", suffix=".ttl", delete=False) as fh:
            fh.write(PREFIX + body)
        out = subprocess.run([str(QUIPU), "validate", "--shapes", str(SHAPES), "--data", fh.name],
                             capture_output=True, text=True)
        Path(fh.name).unlink()
        return out.stdout.lstrip().startswith("valid")

    def test_an_iri_owner_is_accepted(self):
        self.assertTrue(self.valid('aegis:path1 aegis:ownedBy aegis:braino .'))

    def test_a_string_owner_is_refused_on_an_unshaped_class(self):
        # The live case: an untyped-for-this-shape subject carrying a literal.
        self.assertFalse(self.valid('aegis:path1 aegis:ownedBy "aegis-crew" .'))

    def test_one_string_among_iri_owners_is_refused(self):
        self.assertFalse(self.valid('aegis:path1 aegis:ownedBy aegis:braino, "aegis-crew" .'))

    def test_a_subject_without_an_owner_is_untouched(self):
        self.assertTrue(self.valid('aegis:path2 rdfs:label "no owner" .'))


if __name__ == "__main__":
    unittest.main()
