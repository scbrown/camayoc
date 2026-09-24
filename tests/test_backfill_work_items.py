"""backfill_work_items: every bead becomes a WorkItem, without harming the store.

No network. A fake quipu records what would have been written.
"""
from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import backfill_work_items as bf  # noqa: E402
import planes  # noqa: E402
from ingest_work_items import episode_for  # noqa: E402

NS = "http://aegis.gastown.local/ontology/"


def bead(i, created="2026-09-01T00:00:00Z", status="closed"):
    return {"id": f"aegis-{i}", "title": f"t{i}", "created_at": created,
            "updated_at": created, "status": status, "assignee": None, "closed_at": None}


class FakeQuipu:
    def __init__(self, covered=(), control=True, fail_on=(), slow_on=()):
        self.covered = set(covered)
        self.control = control
        self.fail_on, self.slow_on = set(fail_on), set(slow_on)
        self.writes = []
        self.now = 0.0

    def post(self, endpoint, body):
        if endpoint == "/query":
            if "identifier" in body["query"]:
                return {"rows": [{"w": f"aegis:{i}", "id": f'"{i}"'} for i in self.covered],
                        "truncated": False}
            rows = [{"w": f"{NS}{i}"} for i in self.covered]
            if self.control and not rows:
                rows = [{"w": f"{NS}some-other-workitem"}]
            return {"rows": rows if self.control else [], "truncated": False}
        item = body["nodes"][0]["name"]
        self.writes.append(body)
        if item in self.slow_on:
            self.now += 9.0
        if item in self.fail_on:
            raise planes.PlaneError("/episode unreachable: timed out")
        self.covered.add(item)
        return {"outcome": "created"}

    def clock(self):
        return self.now


def go(q, records, **kw):
    kw.setdefault("rate", 0)
    kw.setdefault("stop_after", 5.0)
    return bf.run(records, bf.covered(q.post), q.post, actor="a", source="s",
                  clock=q.clock, sleep=lambda s: None, **kw)


class Selection(unittest.TestCase):
    def test_writes_only_the_missing_and_newest_first(self):
        q = FakeQuipu(covered={"aegis-1"})
        recs = [bead(1), bead(2, "2026-09-02T00:00:00Z"), bead(3, "2026-09-03T00:00:00Z")]
        report = go(q, recs)
        self.assertEqual([b["nodes"][0]["name"] for b in q.writes], ["aegis-3", "aegis-2"])
        self.assertEqual((report["covered_before"], report["missing"], report["written"]), (1, 2, 2))

    def test_max_bounds_a_run(self):
        q = FakeQuipu()
        report = go(q, [bead(i) for i in range(10)], limit=3)
        self.assertEqual(report["written"], 3)

    def test_dry_run_writes_nothing(self):
        q = FakeQuipu()
        report = go(q, [bead(1), bead(2)], dry_run=True)
        self.assertEqual(q.writes, [])
        self.assertEqual(report["attempted"], 2)

    def test_the_body_is_exactly_what_the_standing_sync_sends(self):
        q = FakeQuipu()
        go(q, [bead(7)])
        self.assertEqual(q.writes[0], episode_for(bead(7), actor="a", source="s"))


class Safety(unittest.TestCase):
    def test_no_workitems_at_all_is_a_broken_instrument_not_a_green_light(self):
        with self.assertRaises(ValueError):
            bf.covered(FakeQuipu(control=False).post)

    def test_a_slow_write_stops_the_run(self):
        q = FakeQuipu(slow_on={"aegis-3"})
        recs = [bead(i, f"2026-09-0{i}T00:00:00Z") for i in (1, 2, 3)]
        report = go(q, recs)
        self.assertIn("writer-hold", report["stopped"])
        self.assertEqual(len(q.writes), 1, "nothing may be written after the slow one")

    def test_a_lost_response_is_not_retried_in_the_same_run(self):
        q = FakeQuipu(fail_on={"aegis-2"})
        report = go(q, [bead(1), bead(2, "2026-09-02T00:00:00Z")])
        names = [b["nodes"][0]["name"] for b in q.writes]
        self.assertEqual(names.count("aegis-2"), 1)
        self.assertEqual((report["indeterminate"], report["written"]), (1, 1))

    def test_a_truncated_listing_is_refused(self):
        fake = lambda *a, **k: types.SimpleNamespace(  # noqa: E731
            stdout=json.dumps({"issues": [bead(1)], "total": 2, "has_more": True}))
        with self.assertRaises(ValueError):
            bf.all_beads(Path("x.db"), run=fake)


if __name__ == "__main__":
    unittest.main()
