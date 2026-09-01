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
        self.assertNotIn("Bead", str(body))

    def test_stable_identifier_is_the_bidirectional_lookup_key(self):
        node = self.body()["nodes"][0]
        self.assertEqual("aegis-abc123", node["name"])
        self.assertEqual("aegis-abc123", node["properties"]["identifier"])

    def test_directive_mapping_is_an_about_edge(self):
        iri = f"{ingest.BASE_NS}directive-one"
        body = self.body(about=[iri, iri])
        self.assertEqual([{"source": "aegis-abc123", "target": "directive-one", "relation": "about"}], body["edges"])

    def test_external_about_iri_is_refused_not_minted_as_a_wrong_local_node(self):
        with self.assertRaisesRegex(ingest.WorkItemError, "safe local entity"):
            self.body(about=["http://example.test/directive/one"])

    def test_open_status_is_not_stored_as_a_decaying_judgment(self):
        props = self.body()["nodes"][0]["properties"]
        self.assertNotIn("status", props)
        self.assertNotIn("outcome", props)

    def test_close_is_a_durable_done_outcome(self):
        record = {**OPEN, "status": "closed", "closed_at": "2026-09-02T00:00:00Z"}
        props = self.body(record)["nodes"][0]["properties"]
        self.assertEqual("done", props["outcome"])
        self.assertEqual("2026-09-02T00:00:00Z", props["closedAt"])

    def test_closed_without_timestamp_is_refused(self):
        with self.assertRaisesRegex(ingest.WorkItemError, "closed_at"):
            self.body({**OPEN, "status": "closed"})

    def test_br_one_element_array_is_accepted(self):
        self.assertEqual("aegis-abc123", self.body([OPEN])["nodes"][0]["name"])

    def test_batch_is_refused_instead_of_silently_dropping_records(self):
        with self.assertRaisesRegex(ingest.WorkItemError, "exactly one"):
            self.body([OPEN, OPEN])


if __name__ == "__main__":
    unittest.main()
