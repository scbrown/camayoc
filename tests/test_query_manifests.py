"""Stored-query manifests must match Quipu's released parameter schema."""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StoredQueryManifestTests(unittest.TestCase):
    def test_every_parameter_is_a_typed_object_and_covers_the_template(self):
        for path in sorted((ROOT / "queries").glob("*.json")):
            with self.subTest(query=path.name):
                manifest = json.loads(path.read_text())
                params = manifest.get("params", [])
                self.assertTrue(all(isinstance(param, dict) for param in params))
                for param in params:
                    self.assertEqual(
                        {"name", "type", "required", "description"}, set(param)
                    )
                    self.assertIn(param["type"], {"iri", "text"})
                    self.assertIs(param["required"], True)
                    self.assertTrue(param["description"])

                declared = {param["name"] for param in params}
                referenced = set(re.findall(r"\{([A-Za-z][A-Za-z0-9_]*)\}", manifest["template"]))
                self.assertEqual(referenced, declared)


if __name__ == "__main__":
    unittest.main()
