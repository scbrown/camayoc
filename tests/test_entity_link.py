"""Entity linking: search retrieves, Jev picks (aegis-4hhqoe.12).

Stubbed search and Jev: these prove what the linker does with what it is
given — what it offers, what it may return, and that a failed call is an
error rather than an abstention. The live evaluation is on the bead.
"""
from __future__ import annotations

import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import entity_link as el  # noqa: E402
import jev  # noqa: E402


def search_of(by_query: dict[str, list[str]]):
    def search(q):
        key = "title" if "\n" not in q else "full"
        return {"results": [{"entity": e, "text": f"text of {e}"} for e in by_query[key]]}
    return search


class StubClient:
    def __init__(self, picks):
        self.picks = list(picks)
        self.offered = []

    def choice(self, state, instructions, criteria, none_text=None):
        self.offered.append(dict(criteria))
        pick = self.picks.pop(0)
        if isinstance(pick, BaseException):
            raise pick
        return {"choice": pick, "confidence": 0.9, "usage": {}}


SEARCH = search_of({
    "title": ["aegis:svc-a", "aegis:episode_ingest-x", "aegis:bead-closed-aegis-1"],
    "full": ["aegis:svc-b", "aegis:svc-a",
             "http://aegis.gastown.local/ontology/commit/repo/abc",
             "http://aegis.gastown.local/ontology/code/repo/f.rs::sym",
             "aegis:ledger-0123456789ab-a-directive-row"],
})


class EntityLinkTest(unittest.TestCase):
    def test_provenance_lifecycle_and_passages_are_never_offered(self):
        offered = [c["entity"] for c in el.candidates("t", "d", SEARCH)]
        self.assertEqual(offered, ["aegis:svc-a", "aegis:svc-b"])

    def test_the_item_itself_is_never_a_candidate(self):
        search = search_of({"title": ["aegis:aegis-x1", "aegis:svc-a"],
                            "full": ["http://aegis.gastown.local/ontology/workitem/aegis-x1",
                                     "aegis:aegis-x2"]})
        offered = [c["entity"] for c in el.candidates("t", "d", search, item="aegis-x1")]
        self.assertEqual(offered, ["aegis:svc-a", "aegis:aegis-x2"])

    def test_title_and_full_results_interleave_without_duplicates(self):
        search = search_of({"title": ["aegis:t1", "aegis:t2"],
                            "full": ["aegis:f1", "aegis:t1", "aegis:f2"]})
        offered = [c["entity"] for c in el.candidates("t", "d", search)]
        self.assertEqual(offered, ["aegis:t1", "aegis:f1", "aegis:t2", "aegis:f2"])

    def test_the_pool_is_capped(self):
        many = [f"aegis:e{i}" for i in range(50)]
        search = search_of({"title": many, "full": many})
        self.assertEqual(len(el.candidates("t", "d", search)), el.TOP_K)

    def test_an_offered_pick_is_returned(self):
        client = StubClient(["aegis:svc-b"])
        res = el.link("t", "d", client, SEARCH)
        self.assertEqual(res["choice"], "aegis:svc-b")
        self.assertIsNone(res["error"])
        self.assertEqual(set(client.offered[0]), {"aegis:svc-a", "aegis:svc-b"})

    def test_none_of_these_is_an_abstention_not_an_error(self):
        res = el.link("t", "d", StubClient([jev.NONE_OPTION]), SEARCH)
        self.assertIsNone(res["choice"])
        self.assertIsNone(res["error"])

    def test_an_unoffered_answer_is_never_returned(self):
        res = el.link("t", "d", StubClient(["aegis:never-offered"]), SEARCH)
        self.assertIsNone(res["choice"])

    def test_one_timeout_is_retried(self):
        res = el.link("t", "d", StubClient([TimeoutError("read timed out"), "aegis:svc-a"]), SEARCH)
        self.assertEqual(res["choice"], "aegis:svc-a")
        self.assertIsNone(res["error"])

    def test_a_persistent_failure_is_an_error_not_an_abstention(self):
        client = StubClient([TimeoutError("t1"), TimeoutError("t2")])
        res = el.link("t", "d", client, SEARCH)
        self.assertIsNone(res["choice"])
        self.assertIn("TimeoutError", res["error"])
        self.assertEqual(len(client.offered), el.RETRIES + 1)

    def test_no_candidates_asks_nothing(self):
        client = StubClient([])
        res = el.link("t", "d", client, search_of({"title": [], "full": []}))
        self.assertIsNone(res["choice"])
        self.assertEqual(client.offered, [])

    def test_the_written_link_is_inferred_and_quarantined(self):
        sent = {}
        fake = type(sys)("planes")
        fake.ensure_planes = lambda ts: None
        fake.plane_for = lambda kind: f"urn:plane:{kind}"
        post = lambda path, body, token="": sent.update(path=path, **body) or {}
        with mock.patch.dict(sys.modules, {"planes": fake}), \
                mock.patch.object(el, "_post", post):
            el.write_link("aegis-x1", "aegis:svc-a", "tok", "2026-10-01T00:00:00Z")
        self.assertEqual(sent["path"], "/knot")
        self.assertEqual(sent["graph"], "urn:plane:inferred")
        self.assertIn(f"<{el.ONTOLOGY}about> <{el.ONTOLOGY}svc-a>", sent["turtle"])
        self.assertIn('"inferred"', sent["turtle"])


if __name__ == "__main__":
    unittest.main()
