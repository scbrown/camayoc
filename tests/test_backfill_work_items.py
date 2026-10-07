"""backfill_work_items: every bead becomes a WorkItem, without harming the store.

No network. A fake quipu records what would have been written.
"""
from __future__ import annotations

import json
import sys
import types
import unittest
from unittest import mock
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


def dep(i, deps, created="2026-09-01T00:00:00Z"):
    record = bead(i, created)
    record["blocked_on"] = list(deps)
    return record


class Reprojection(unittest.TestCase):
    """aegis-ima1hq: a covered bead is re-projected only when its deps CHANGED."""

    def test_unchanged_deps_are_written_once_then_never_again(self):
        q = FakeQuipu(covered={"aegis-1"})
        projected = {}
        first = go(q, [dep(1, ["aegis-9"])], projected=projected)
        self.assertEqual((first["written"], first["reproject_pending"]), (1, 1))
        second = go(q, [dep(1, ["aegis-9"])], projected=projected)
        self.assertEqual((second["attempted"], second["reproject_pending"]), (0, 0))
        self.assertEqual(len(q.writes), 1)

    def test_changed_deps_are_reprojected(self):
        q = FakeQuipu(covered={"aegis-1"})
        projected = {"aegis-1": "aegis-9"}
        report = go(q, [dep(1, ["aegis-9", "aegis-8"])], projected=projected)
        self.assertEqual(report["written"], 1)
        self.assertEqual(projected["aegis-1"], "aegis-8,aegis-9")

    def test_a_newly_written_missing_bead_records_its_deps(self):
        q = FakeQuipu()
        projected = {}
        go(q, [dep(1, ["aegis-9"])], projected=projected)
        self.assertEqual(go(q, [dep(1, ["aegis-9"])], projected=projected)["attempted"], 0)

    def test_missing_beads_come_before_reprojections_under_max(self):
        # The starvation shape: more stale covered beads than --max, all NEWER.
        covered = {f"aegis-{i}" for i in range(10, 20)}
        q = FakeQuipu(covered=covered)
        recs = [dep(i, ["aegis-x"], "2026-09-09T00:00:00Z") for i in range(10, 20)]
        recs += [bead(1), bead(2)]
        report = go(q, recs, limit=3, projected={})
        names = [b["nodes"][0]["name"] for b in q.writes]
        self.assertEqual(sorted(names[:2]), ["aegis-1", "aegis-2"])
        self.assertEqual(report["written"], 3)

    def test_an_indeterminate_write_is_not_recorded(self):
        q = FakeQuipu(covered={"aegis-1"}, fail_on={"aegis-1"})
        projected = {}
        go(q, [dep(1, ["aegis-9"])], projected=projected)
        self.assertNotIn("aegis-1", projected)

    def test_state_roundtrip_and_malformed_state_means_empty(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.projected.json"
            self.assertEqual(bf.load_projected(path), {})
            bf.save_projected(path, {"aegis-1": "aegis-9"})
            self.assertEqual(bf.load_projected(path), {"aegis-1": "aegis-9"})
            path.write_text("[1, 2")
            self.assertEqual(bf.load_projected(path), {})
            path.write_text('{"aegis-1": 5}')
            self.assertEqual(bf.load_projected(path), {})


class Safety(unittest.TestCase):
    def test_no_workitems_at_all_is_a_broken_instrument_not_a_green_light(self):
        with self.assertRaises(ValueError):
            bf.covered(FakeQuipu(control=False).post)

    def test_one_slow_write_backs_off_and_continues(self):
        q = FakeQuipu(slow_on={"aegis-3"})
        recs = [bead(i, f"2026-09-0{i}T00:00:00Z") for i in (1, 2, 3)]
        report = go(q, recs)
        self.assertIsNone(report["stopped"])
        self.assertEqual((len(q.writes), report["slow_writes"]), (3, 1))

    def test_two_consecutive_slow_writes_stop_the_run(self):
        q = FakeQuipu(slow_on={"aegis-3", "aegis-2"})
        recs = [bead(i, f"2026-09-0{i}T00:00:00Z") for i in (1, 2, 3)]
        report = go(q, recs)
        self.assertIn("2 consecutive", report["stopped"])
        self.assertEqual(len(q.writes), 2, "nothing may be written after the second slow one")

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


class DependencyLookup(unittest.TestCase):
    """A failed `br dep list` must skip the bead, never write it without deps."""

    def test_a_timed_out_lookup_marks_only_that_record_and_the_rest_attach(self):
        import subprocess
        from ingest_work_items import attach_blocked_on

        def fake(cmd, **kw):
            if cmd[5] == "aegis-slow":
                raise subprocess.TimeoutExpired(cmd, 15)
            return types.SimpleNamespace(stdout=json.dumps(
                [{"issue_id": cmd[5], "depends_on_id": "aegis-d", "type": "blocks"}]))

        recs = [dict(bead(1), dependency_count=1), dict(bead(2), id="aegis-slow", dependency_count=1),
                bead(3)]
        self.assertEqual(attach_blocked_on(recs, Path("x.db"), run=fake), ["aegis-slow"])
        self.assertEqual(recs[0]["blocked_on"], ["aegis-d"])
        self.assertTrue(recs[1]["dep_unknown"])
        self.assertNotIn("blocked_on", recs[2])

    def test_a_record_with_unknown_dependencies_is_not_written(self):
        q = FakeQuipu()
        report = go(q, [bead(1), dict(bead(2, "2026-09-02T00:00:00Z"), dep_unknown=True)])
        self.assertEqual([b["nodes"][0]["name"] for b in q.writes], ["aegis-1"])
        self.assertEqual(report["written"], 1)


class Paging(unittest.TestCase):
    """quipu caps a result at 10,000 rows; the crew:records plane passed that on
    2026-09-25 and every backfill run refused a truncated read (aegis-jrobfn)."""

    def pages(self, total, cap=10_000):
        rows = [{"w": f"aegis:w{i:06d}"} for i in range(total)]
        calls = []

        def post(endpoint, body):
            calls.append(body["query"])
            q = body["query"]
            if "LIMIT" not in q:  # the old unpaged read
                return {"rows": rows[:cap], "truncated": total > cap}
            limit = int(q.split("LIMIT ")[1].split()[0])
            offset = int(q.split("OFFSET ")[1].split()[0])
            page = rows[offset:offset + limit]
            return {"rows": page[:cap], "truncated": len(page) > cap}
        return post, calls

    def test_more_rows_than_the_server_cap_are_all_read(self):
        post, calls = self.pages(12_345)
        got = bf.paged(post, bf.WORKITEM_QUERIES[0], {}, "WorkItem", None)
        self.assertEqual(12_345, len(got))
        self.assertEqual(12_345, len({r["w"] for r in got}))
        self.assertTrue(all("ORDER BY ?w" in q for q in calls))

    def test_an_exact_multiple_of_the_page_ends_on_an_empty_page(self):
        post, calls = self.pages(2 * bf.PAGE)
        self.assertEqual(2 * bf.PAGE, len(bf.paged(post, bf.WORKITEM_QUERIES[0], {}, "WorkItem", None)))
        self.assertEqual(3, len(calls))

    def test_a_truncated_page_is_still_refused(self):
        post, _ = self.pages(12_000, cap=100)  # a server cap below the page size
        with self.assertRaises(ValueError):
            bf.paged(post, bf.WORKITEM_QUERIES[0], {}, "WorkItem", None)


class DependencyCache(unittest.TestCase):
    """aegis-ky3zpa: dependency reads are cached across runs by updated_at."""

    def run_main(self, d, records, lookups):
        from unittest import mock
        import ingest_work_items

        def blocked(recs, db, run=None):
            for r in recs:
                lookups.append(r["id"])
                r["blocked_on"] = ["aegis-x"]
            return []
        q = FakeQuipu(covered={r["id"] for r in records})
        with mock.patch.object(bf, "all_beads", return_value=[dict(r) for r in records]), \
                mock.patch.object(ingest_work_items, "attach_blocked_on", blocked), \
                mock.patch.object(planes, "_post", lambda e, b, client=None: q.post(e, b)), \
                mock.patch("sys.stdout"):
            bf.main(["--db", "x.db", "--actor", "a", "--source", "s", "--rate", "0",
                     "--lock", str(Path(d) / "b.lock")])

    def test_an_unchanged_bead_is_read_once_and_a_touched_one_again(self):
        import tempfile
        rec = dict(bead(1), dependency_count=1)
        with tempfile.TemporaryDirectory() as d:
            lookups = []
            self.run_main(d, [rec], lookups)
            self.run_main(d, [rec], lookups)
            self.assertEqual(lookups, ["aegis-1"], "second run must hit the cache")
            self.run_main(d, [dict(rec, updated_at="2026-10-07T00:00:00Z")], lookups)
            self.assertEqual(lookups, ["aegis-1", "aegis-1"])

    def test_malformed_cache_entries_are_dropped(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.deps.json"
            path.write_text(json.dumps({"a": ["t", ["b"]], "b": 5, "c": ["t", "b"], "d": [1, []]}))
            self.assertEqual(bf.load_deps_cache(path), {"a": ["t", ["b"]]})

class SplitTypeQuipu(FakeQuipu):
    """Answers each asserted-type query with only the items typed THAT way:
    `legacy` under the old class, `quechua` under its Quechua twin."""

    def __init__(self, legacy, quechua, schema=()):
        super().__init__(covered=set(legacy) | set(quechua) | set(schema))
        self.by_type = {bf.WORKITEM_TYPES[0]: set(legacy), bf.WORKITEM_TYPES[1]: set(quechua),
                        bf.WORKITEM_TYPES[2]: set(schema)}
        self.schema = set(schema)

    def post(self, endpoint, body):
        if endpoint == "/query" and "identifier" in body["query"]:
            # seeds' schema.org items carry ONLY schema:identifier (aegis-bqgdr3)
            ids = self.schema if "schema.org/identifier" in body["query"] else self.covered - self.schema
            return {"rows": [{"w": f"aegis:{i}", "id": f'"{i}"'} for i in sorted(ids)],
                    "truncated": False}
        if endpoint == "/query":
            iri = next(t for t in self.by_type if f"<{t}>" in body["query"])
            return {"rows": [{"w": f"{NS}{i}"} for i in sorted(self.by_type[iri])],
                    "truncated": False}
        return super().post(endpoint, body)


class QuechuaTypedItemsAreCovered(unittest.TestCase):
    """aegis-9dpcta: the class may be renamed, the identifier may not. An item
    typed only with the Quechua twin is already covered; re-posting it through
    /episode would write the legacy type beside it and double-type the record."""

    def test_a_quechua_typed_item_is_not_rewritten(self):
        q = SplitTypeQuipu(legacy={"aegis-1"}, quechua={"aegis-2"})
        report = go(q, [bead(1), bead(2), bead(3, "2026-09-03T00:00:00Z")])
        self.assertEqual([b["nodes"][0]["name"] for b in q.writes], ["aegis-3"])
        self.assertEqual(report["covered_before"], 2)

    def test_a_legacy_only_reader_would_rewrite_it(self):
        """The mutant: read only the legacy class and the Quechua-typed item
        looks missing. This is the double-typing the dual read prevents."""
        q = SplitTypeQuipu(legacy={"aegis-1"}, quechua={"aegis-2"})
        with mock.patch.object(bf, "WORKITEM_QUERIES", bf.WORKITEM_QUERIES[:1]):
            go(q, [bead(1), bead(2), bead(3, "2026-09-03T00:00:00Z")])
        self.assertIn("aegis-2", [b["nodes"][0]["name"] for b in q.writes])


class SchemaActionItemsAreCovered(unittest.TestCase):
    """aegis-bqgdr3: a seed in the schema.org model is typed schema:Action and
    carries schema:identifier, not the legacy predicate. It is covered."""

    def test_a_schema_action_item_is_not_rewritten(self):
        q = SplitTypeQuipu(legacy={"aegis-1"}, quechua=set(), schema={"aegis-2"})
        report = go(q, [bead(1), bead(2), bead(3, "2026-09-03T00:00:00Z")])
        self.assertEqual([b["nodes"][0]["name"] for b in q.writes], ["aegis-3"])
        self.assertEqual(report["covered_before"], 2)

    def test_a_reader_of_only_the_legacy_identifier_would_rewrite_it(self):
        q = SplitTypeQuipu(legacy={"aegis-1"}, quechua=set(), schema={"aegis-2"})
        with mock.patch.object(bf, "IDENTIFIER_QUERIES", bf.IDENTIFIER_QUERIES[:1]):
            go(q, [bead(1), bead(2), bead(3, "2026-09-03T00:00:00Z")])
        self.assertIn("aegis-2", [b["nodes"][0]["name"] for b in q.writes])

    def test_a_reader_of_only_the_older_types_would_rewrite_it(self):
        q = SplitTypeQuipu(legacy={"aegis-1"}, quechua=set(), schema={"aegis-2"})
        with mock.patch.object(bf, "WORKITEM_QUERIES", bf.WORKITEM_QUERIES[:2]):
            go(q, [bead(1), bead(2), bead(3, "2026-09-03T00:00:00Z")])
        self.assertIn("aegis-2", [b["nodes"][0]["name"] for b in q.writes])


if __name__ == "__main__":
    unittest.main()
