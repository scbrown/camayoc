from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUIPU = shutil.which("quipu")
IN_CI = os.environ.get("CI", "").lower() in {"1", "true", "yes"}


class RmlShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QUIPU:
            return
        if IN_CI:
            raise RuntimeError("quipu CLI is required to execute the RML shape gate in CI")
        raise unittest.SkipTest("quipu CLI is required to execute the RML shape gate")

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
