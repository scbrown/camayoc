from __future__ import annotations

import importlib.util, sys, unittest
from pathlib import Path

try:
    import rdflib  # noqa: F401
except ImportError:
    rdflib = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(rdflib, "rdflib is required for RML execution")
class RmlExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("rml_executor", ROOT / "scripts/rml_executor.py")
        cls.module = importlib.util.module_from_spec(spec); sys.modules["rml_executor"] = cls.module
        assert spec.loader; spec.loader.exec_module(cls.module)

    def test_json_mapping_is_deterministic_and_deduplicated(self):
        plan = self.module.compile_mapping(
            ROOT / "tests/fixtures/rml/valid.ttl", "https://example.invalid/rml/map"
        )
        import json
        records = json.loads((ROOT / "tests/fixtures/rml/records.json").read_text())
        first = self.module.materialize(plan, records)
        self.assertEqual(first, self.module.materialize(plan, list(reversed(records))))
        self.assertEqual(4, len(first.splitlines()))
        self.assertIn("https://example.invalid/rml/target", first)

    def test_invalid_mapping_refuses_before_source_access(self):
        with self.assertRaises(self.module.RmlExecutionError):
            self.module.compile_mapping(
                ROOT / "tests/fixtures/rml/invalid.ttl", "https://example.invalid/rml/map"
            )


if __name__ == "__main__": unittest.main()
