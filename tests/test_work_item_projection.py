"""Tracker dependencies and status reach the graph without re-minting anything (aegis-3b3nrb)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ingest_work_items import blocked_on_of, episode_for  # noqa: E402

REC = {"id": "aegis-x", "title": "t", "created_at": "2026-09-01T00:00:00Z",
       "updated_at": "2026-09-02T00:00:00Z", "status": "closed", "assignee": None,
       "closed_at": "2026-09-02T00:00:00Z"}


def old_digest(record):
    """The digest episode_for produced before this change, recomputed independently."""
    snap = {k: record.get(k) for k in ("id", "title", "status", "assignee", "closed_at")}
    snap["updated_at"] = record.get("updated_at") or record["created_at"]
    canonical = json.dumps(snap, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class Projection(unittest.TestCase):
    def test_a_bead_without_dependencies_keeps_its_version(self):
        body = episode_for(REC, actor="a", source="s")
        self.assertEqual(body["name"], f"tracker-work-item:aegis-x:{old_digest(REC)}",
                         "a no-dependency bead must not be re-minted")
        self.assertEqual(body, episode_for({**REC, "blocked_on": []}, actor="a", source="s"))

    def test_dependencies_version_the_observation_and_become_edges(self):
        a = episode_for({**REC, "blocked_on": ["aegis-b", "aegis-a"]}, actor="a", source="s")
        b = episode_for({**REC, "blocked_on": ["aegis-a", "aegis-b"]}, actor="a", source="s")
        self.assertEqual(a, b, "the order of dependencies must not matter")
        self.assertNotEqual(a["name"], episode_for(REC, actor="a", source="s")["name"])
        obs = a["nodes"][1]["name"]
        self.assertEqual(sorted(e["target"] for e in a["edges"] if e["relation"] == "observedBlockedOn"),
                         ["aegis-a", "aegis-b"])
        self.assertTrue(all(e["source"] == obs for e in a["edges"] if e["relation"] == "observedBlockedOn"))
        self.assertEqual(a["nodes"][0], episode_for(REC, actor="a", source="s")["nodes"][0],
                         "the WorkItem node stays byte-identical")

    def test_status_is_structured_on_the_observation(self):
        props = episode_for(REC, actor="a", source="s")["nodes"][1]["properties"]
        self.assertEqual((props["observedStatus"], props["observedClosedAt"]),
                         ("closed", "2026-09-02T00:00:00Z"))

    def test_only_blocks_edges_block(self):
        rows = [{"issue_id": "aegis-x", "depends_on_id": "aegis-p", "type": "parent-child"},
                {"issue_id": "aegis-x", "depends_on_id": "aegis-b", "type": "blocks"},
                {"issue_id": "aegis-x", "depends_on_id": "aegis-r", "type": "related"}]
        fake = lambda *a, **k: types.SimpleNamespace(stdout=json.dumps(rows))  # noqa: E731
        self.assertEqual(blocked_on_of("aegis-x", "db", run=fake), ["aegis-b"])


if __name__ == "__main__":
    unittest.main()
