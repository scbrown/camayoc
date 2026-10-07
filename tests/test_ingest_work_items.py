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


class PlannedWorkExpiryTests(unittest.TestCase):
    """aegis-qx96wr: planned work carries a kind and an idle limit; ordinary work is untouched."""

    def body(self, **extra):
        return ingest.episode_for({**OPEN, **extra}, actor="ian", source="br:aegis-abc123")

    def test_ordinary_work_is_byte_identical_to_before(self):
        # The digest of ordinary work must not move, or every bead is re-minted.
        self.assertEqual(self.body(labels=["infra"]), self.body())
        node = self.body(labels=["infra"])["nodes"][0]
        self.assertNotIn("workKind", node["properties"])
        self.assertNotIn("idleLimit", node["properties"])

    def test_kinds_and_their_limits(self):
        cases = [({"labels": ["stiwi-directive", "design"]}, "Directive", "P3D"),
                 ({"labels": ["dream", "dream-cycle"]}, "DreamCycle", "PT12H"),
                 ({"labels": ["design", "roles"]}, "Design", "P7D"),
                 ({"issue_type": "epic"}, "Plan", "P7D"),
                 ({"labels": ["plan"]}, "Plan", "P7D")]
        for extra, kind, limit in cases:
            props = self.body(**extra)["nodes"][0]["properties"]
            self.assertEqual((props["workKind"], props["idleLimit"]), (kind, limit), extra)

    def test_a_dream_proposal_is_not_a_dream_cycle(self):
        # aegis-2idcev: proposals carry `dream` but are not cycles; only dream-cycle is.
        self.assertNotIn("workKind", self.body(labels=["dream", "dream-proposal"])["nodes"][0]["properties"])

    def test_planned_work_gets_a_new_version_once(self):
        plain, planned = self.body(), self.body(labels=["stiwi-directive"])
        self.assertNotEqual(plain["name"], planned["name"])
        self.assertEqual(planned, self.body(labels=["stiwi-directive"]))
