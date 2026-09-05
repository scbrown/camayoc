from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

# The quipu-CLI gate — including WHY it keys on the QUIPU_BIN promise rather
# than on `CI`, which this repo paid two red days to learn — now lives in
# `tests/quipu_bin_guard.py`, so all three quipu-gated suites share one rule.
from quipu_bin_guard import QUIPU, requires_quipu

ROOT = Path(__file__).resolve().parents[1]


@requires_quipu
class RmlShapeTests(unittest.TestCase):
    @staticmethod
    def validate(fixture: str) -> subprocess.CompletedProcess[str]:
        assert QUIPU
        return subprocess.run(
            [
                QUIPU,
                "validate",
                "--shapes",
                str(ROOT / "shapes" / "rml-subset.shapes.ttl"),
                "--data",
                str(ROOT / "tests" / "fixtures" / "rml" / fixture),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_complete_subset_mapping_conforms(self):
        result = self.validate("valid.ttl")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("valid (0 warnings)", result.stdout)

    def test_incomplete_source_and_double_constructor_are_refused(self):
        result = self.validate("invalid.ttl")
        output = result.stdout + result.stderr
        self.assertNotEqual(0, result.returncode, output)
        self.assertIn("2 violation(s)", output)
        self.assertIn("Xone constraint not satisfied", output)
        self.assertIn("MinCount(1) not satisfied", output)


if __name__ == "__main__":
    unittest.main()
