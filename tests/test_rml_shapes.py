from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# `QUIPU_BIN` is a PROMISE by the job that set it: "I fetched a quipu CLI and put
# it here." It is the same idiom `test_metrics_slice.py` already uses for
# `QUIPU_SERVER_BIN`, and the `integration` arm of ci.yml writes both from the
# release tarball, which ships `quipu` next to `quipu-server`.
QUIPU = os.environ.get("QUIPU_BIN") or shutil.which("quipu")

# WHY THIS NO LONGER KEYS ON `CI` (camayoc CI red on main 2026-08-31 -> 2026-09-02,
# surfaced by aegis-anb66y's owner-routed CI watcher).
#
# This gate was written in the shape of `tests/rdflib_guard.py` — skip for a human,
# refuse for a machine — and that shape is right THERE, because the `test` job
# `pip install rdflib`s: the refusal names a dependency the workflow genuinely
# provides, so it can only fire on a real regression.
#
# Copied here, the same shape asserts something that was never true: that every CI
# job provides a quipu CLI. None did. So `setUpClass` raised on every run of every
# job, main went red on the commit that added this file and stayed red — 360 tests
# passing behind one unconditional error — and the gate itself has never executed
# anywhere, on any machine. A gate that cannot pass is not stricter than one that
# skips; it is a gate nobody can read, which is the same green-check-over-an-unrun-
# suite failure in the other direction.
#
# So the refusal now keys on the PROMISE rather than on the runner. If a job set
# `QUIPU_BIN` and the binary is not there, that job is broken and this goes red.
# If nothing promised a quipu, this skips and says where the gate does run. The
# integration arm is what makes that honest: it fetches the CLI, so the shapes are
# now actually validated on every push for the first time.
_PROMISED = "QUIPU_BIN" in os.environ

_WHERE = (
    "The RML shape gate needs the quipu CLI. It runs in the `integration` job of "
    ".github/workflows/ci.yml, which fetches it from the quipu release tarball and "
    "exports QUIPU_BIN. To run it here, put a `quipu` on PATH or set QUIPU_BIN."
)


class RmlShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QUIPU and Path(QUIPU).exists():
            return
        if _PROMISED:
            raise RuntimeError(
                f"QUIPU_BIN is set to {os.environ['QUIPU_BIN']!r} but no CLI is there. "
                "The job that set it did not deliver it; this is that job's fault, not "
                "a missing optional dependency."
            )
        raise unittest.SkipTest(_WHERE)

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
