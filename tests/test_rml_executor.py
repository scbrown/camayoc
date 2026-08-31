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

    def test_same_source_join_emits_edges_and_counts_unmatched(self):
        # camayoc-5bf: the FK-shaped edge. Order "b" names a customer that no
        # row carries... except every row IS a customer row here (same source),
        # so unmatched means a customer_id no row has.
        plan = self.module.compile_mapping(
            ROOT / "tests/fixtures/rml/join.ttl", "https://example.invalid/rml/orders"
        )
        records = [
            {"id": "o1", "customer_id": "c1"},
            {"id": "o2", "customer_id": "c1"},
        ]
        nquads, unmatched = self.module.materialize_with_stats(plan, records)
        self.assertEqual(0, unmatched)
        self.assertIn(
            "<https://example.invalid/order/o1> <https://example.invalid/rml/placedBy> "
            "<https://example.invalid/customer/c1>",
            nquads,
        )
        # Determinism: reversed input, identical bytes.
        self.assertEqual(nquads, self.module.materialize(plan, list(reversed(records))))

    def test_unmatched_join_is_counted_not_silent(self):
        plan = self.module.compile_mapping(
            ROOT / "tests/fixtures/rml/join.ttl", "https://example.invalid/rml/orders"
        )
        # The parent index is built from the same records; key "ghost" appears
        # as a child value only, so the join finds nothing for that row.
        records = [{"id": "o1", "customer_id": "c1"}]
        with_ghost = records + [{"id": "o2", "customer_id": ""}]
        # Both rows index as parents (same source), so "" IS a customer key
        # here; force a genuine miss by joining against a missing key instead.
        nquads, unmatched = self.module.materialize_with_stats(plan, with_ghost)
        self.assertEqual(0, unmatched)
        # Now a plan-level miss: cross-source, empty parent side.
        cross = self.module.compile_mapping(
            ROOT / "tests/fixtures/rml/join-cross.ttl", "https://example.invalid/rml/orders"
        )
        key = cross.parent_sources[0][0]
        nquads, unmatched = self.module.materialize_with_stats(cross, records, {key: []})
        self.assertEqual(1, unmatched)
        self.assertNotIn("placedBy", nquads)

    def test_cross_source_join_resolves_against_parent_records(self):
        cross = self.module.compile_mapping(
            ROOT / "tests/fixtures/rml/join-cross.ttl", "https://example.invalid/rml/orders"
        )
        key = cross.parent_sources[0][0]
        self.assertEqual("https://example.invalid/rml/customers-source", key)
        nquads, unmatched = self.module.materialize_with_stats(
            cross,
            [{"id": "o1", "customer_id": "7"}],
            # SQLite-shaped int meets CSV-shaped string: joins compare str().
            {key: [{"cid": 7, "name": "Ada"}]},
        )
        self.assertEqual(0, unmatched)
        self.assertIn("<https://example.invalid/customer/7>", nquads)

    def test_cross_source_join_without_parent_records_refuses(self):
        cross = self.module.compile_mapping(
            ROOT / "tests/fixtures/rml/join-cross.ttl", "https://example.invalid/rml/orders"
        )
        with self.assertRaisesRegex(self.module.RmlExecutionError, "no parent source provided"):
            self.module.materialize_with_stats(cross, [{"id": "o1", "customer_id": "7"}])

    def test_joinless_ref_object_map_refuses_at_compile(self):
        data = (ROOT / "tests/fixtures/rml/join.ttl").read_text().replace(
            "rr:joinCondition ex:placed-by-join .", "."
        ).replace("ex:placed-by-ref a rr:RefObjectMap ; rr:parentTriplesMap ex:customers ;\n",
                  "ex:placed-by-ref a rr:RefObjectMap ; rr:parentTriplesMap ex:customers ")
        with self.assertRaisesRegex(self.module.RmlExecutionError, "at least one joinCondition"):
            self.module.compile_mapping_data(data, "https://example.invalid/rml/orders")

    def test_ref_object_map_with_a_constructor_refuses(self):
        data = (ROOT / "tests/fixtures/rml/join.ttl").read_text().replace(
            "ex:placed-by-ref a rr:RefObjectMap ;",
            'ex:placed-by-ref a rr:RefObjectMap ; rr:template "https://example.invalid/x/{id}" ;',
        )
        with self.assertRaisesRegex(self.module.RmlExecutionError, "cannot also carry a constructor"):
            self.module.compile_mapping_data(data, "https://example.invalid/rml/orders")

    def test_invalid_mapping_refuses_before_source_access(self):
        with self.assertRaises(self.module.RmlExecutionError):
            self.module.compile_mapping(
                ROOT / "tests/fixtures/rml/invalid.ttl", "https://example.invalid/rml/map"
            )


if __name__ == "__main__": unittest.main()
