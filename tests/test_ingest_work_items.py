"""Tracker records enter through Camayoc as governed WorkItems."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "ingest_work_items", ROOT / "scripts/ingest_work_items.py"
)
ingest = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(ingest)


OPEN = {
    "id": "aegis-abc123",
    "title": "Make tracker ingress first-class",
    "status": "in_progress",
    "created_at": "2026-09-01T00:00:00Z",
}


class WorkItemIngressTests(unittest.TestCase):
    def body(self, record=OPEN, **kwargs):
        return ingest.episode_for(record, actor="malcolm", source="br:aegis-abc123", **kwargs)

    def test_reuses_work_item_and_observed_plane(self):
        body = self.body()
        node = body["nodes"][0]
        self.assertEqual("WorkItem", node["type"])
        self.assertEqual("observed", node["properties"]["sourceKind"])
        self.assertEqual(ingest.planes.plane_for("observed"), body["graph"])
        self.assertEqual("Observation", body["nodes"][1]["type"])
        self.assertNotIn("Bead", str(body))

    def test_stable_identifier_is_the_bidirectional_lookup_key(self):
        node = self.body()["nodes"][0]
        self.assertEqual("aegis-abc123", node["name"])
        self.assertEqual("aegis-abc123", node["properties"]["identifier"])

    def test_directive_mapping_is_an_about_edge(self):
        iri = f"{ingest.BASE_NS}directive-one"
        body = self.body(about=[iri, iri])
        self.assertIn(
            {"source": "aegis-abc123", "target": "directive-one", "relation": "about"},
            body["edges"],
        )

    def test_external_about_iri_is_refused_not_minted_as_a_wrong_local_node(self):
        with self.assertRaisesRegex(ingest.WorkItemError, "safe local entity"):
            self.body(about=["http://example.test/directive/one"])

    def test_status_is_an_immutable_observation_not_a_work_item_judgment(self):
        props = self.body()["nodes"][0]["properties"]
        self.assertNotIn("status", props)
        self.assertNotIn("outcome", props)
        self.assertIn('"status":"in_progress"', self.body()["nodes"][1]["properties"]["observedValue"])

    def test_changed_record_mints_a_new_observation_but_identical_work_item(self):
        first = self.body()
        changed = self.body({**OPEN, "title": "Corrected title", "updated_at": "2026-09-02T00:00:00Z"})
        self.assertEqual(first["nodes"][0], changed["nodes"][0])
        self.assertNotEqual(first["nodes"][1]["name"], changed["nodes"][1]["name"])
        self.assertNotEqual(first["name"], changed["name"])

    def test_identical_record_is_byte_stable(self):
        self.assertEqual(self.body(), self.body())

    def test_br_one_element_array_is_accepted(self):
        self.assertEqual("aegis-abc123", self.body([OPEN])["nodes"][0]["name"])

    def test_batch_is_refused_instead_of_silently_dropping_records(self):
        with self.assertRaisesRegex(ingest.WorkItemError, "exactly one"):
            self.body([OPEN, OPEN])


if __name__ == "__main__":
    unittest.main()
