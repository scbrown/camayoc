from __future__ import annotations

import importlib.util, io, json, sqlite3, sys, tempfile, unittest
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

    def test_csv_and_sqlite_adapters_produce_the_same_quads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "records.csv"
            csv_path.write_text("id,name\ntwo,Beta\none,Alpha\none,Alpha\n")
            db_path = root / "records.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE records (id TEXT, name TEXT)")
                conn.executemany(
                    "INSERT INTO records VALUES (?, ?)",
                    [("two", "Beta"), ("one", "Alpha"), ("one", "Alpha")],
                )
            csv_plan = self.module.compile_mapping(
                ROOT / "tests/fixtures/rml/csv.ttl", "https://example.invalid/rml/csv-map"
            )
            sql_plan = self.module.compile_mapping(
                ROOT / "tests/fixtures/rml/sqlite.ttl", "https://example.invalid/rml/sqlite-map"
            )
            csv_source = self.module.load_source(csv_plan, csv_path, root)
            sql_source = self.module.load_source(sql_plan, db_path, root)
            self.assertEqual(
                self.module.materialize(csv_plan, csv_source.records),
                self.module.materialize(sql_plan, sql_source.records),
            )

    def test_source_boundaries_and_mutating_sql_refuse(self):
        plan = self.module.compile_mapping(
            ROOT / "tests/fixtures/rml/csv.ttl", "https://example.invalid/rml/csv-map"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root.parent / "outside.csv"
            with self.assertRaisesRegex(self.module.RmlExecutionError, "escapes allowed root"):
                self.module.load_source(plan, outside, root)
        with self.assertRaisesRegex(self.module.RmlExecutionError, "exactly one SELECT"):
            self.module._validate_sql("DELETE FROM records")

    def test_governed_write_carries_graph_actor_and_mapping_provenance(self):
        plan = self.module.compile_mapping(
            ROOT / "tests/fixtures/rml/valid.ttl", "https://example.invalid/rml/map"
        )
        records = json.loads((ROOT / "tests/fixtures/rml/records.json").read_text())
        captured = {}

        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_args): return False

        def opener(req, timeout):
            captured.update(json.loads(req.data))
            return Response(b'{"tx_id":42,"count":4,"conforms":true}')

        result = self.module.governed_write(
            "https://example.invalid", plan, self.module.materialize(plan, records),
            "malcolm", "sha256:" + "b" * 64, opener=opener,
        )
        self.assertEqual(42, result["tx_id"])
        self.assertEqual(str(plan.target_graph), captured["graph"])
        self.assertEqual("malcolm", captured["actor"])
        self.assertIn(str(plan.mapping_iri), captured["source"])
        self.assertEqual(4, len(rdflib.Graph().parse(data=captured["turtle"], format="turtle")))

    def test_invalid_mapping_refuses_before_source_access(self):
        with self.assertRaises(self.module.RmlExecutionError):
            self.module.compile_mapping(
                ROOT / "tests/fixtures/rml/invalid.ttl", "https://example.invalid/rml/map"
            )


if __name__ == "__main__": unittest.main()
