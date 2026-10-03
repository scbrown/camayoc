"""A recorded day's changes must reproduce the full population verdicts."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import blocked_by as bb
import change_adapter as ca
import review_due as rd
from test_blocked_by import Store, item
from test_review_due import Store as ReviewStore

NOW = dt.datetime(2026, 10, 3, tzinfo=dt.timezone.utc).timestamp()


def change(subject, prop, value=None, old=None):
    return {"entity": bb.A + subject, "attribute": bb.term_iris(prop)[-1],
            "value": value, "old_value": old, "graph": "ROOT", "op": "assert"}


class Incremental(unittest.TestCase):
    def test_batched_history_matches_full_and_bounds_reads(self):
        triples = item("w", "open") + [("w", "blockedOn", "d")]
        for i in range(100):
            triples += item("d", "closed" if i == 99 else "open",
                            at=f"2026-09-{1 + i // 24:02d}T{i % 24:02d}:00:00Z", obs=f"od{i}")
        store = Store(triples)
        calls = []
        def post(endpoint, body):
            calls.append(body["query"])
            return store.post(endpoint, body)
        old = bb.evaluate(post, item="w")
        old_count = len(calls)
        calls.clear()
        new = bb.evaluate(post, item="w", batch_history=True)
        self.assertEqual(new, old)
        self.assertLess(len(calls), old_count // 3)
        self.assertTrue(any("?at31" in q for q in calls))
        self.assertFalse(any("VALUES" in q or "BIND" in q or " . " in q for q in calls))

    def test_batched_tie_preserves_projected_status_preference(self):
        store = Store(item("w", "open") + [("w", "blockedOn", "d"), ("d", "a", "WorkItem"),
                      ("d", "observes", "older"), ("d", "observes", "projected"),
                      ("older", "observedAt", "2026-09-30"), ("projected", "observedAt", "2026-09-30"),
                      ("projected", "observedStatus", "closed")])
        self.assertEqual(bb.evaluate(store.post, item="w", batch_history=True), bb.evaluate(store.post, item="w"))

    def test_idle_does_no_reads(self):
        def no_reads(*args):
            self.fail("idle adapter made a graph request")
        result = ca.evaluate("blocked", no_reads, {"now": NOW, "changes": [], "items": []})
        self.assertEqual(result["records"], [])

    def test_closed_dependency_invalidates_waiter_not_unrelated_population(self):
        store = Store(item("w", "open") + item("d", "closed", obs="od") + [("w", "blockedOn", "d")])
        result = ca.evaluate("blocked", store.post, {"now": NOW,
                             "changes": [change("od", "observedStatus", "closed")]})
        self.assertEqual(result["scope"], ["d", "w"])
        self.assertEqual(result["records"], bb.evaluate(store.post))

    def test_removed_observation_link_keeps_former_owner_in_scope(self):
        store = Store(item("w", "open") + item("d", "closed") + [("w", "blockedOn", "d")])
        result = ca.evaluate("blocked", store.post, {"now": NOW,
                             "changes": [change("d", "observes", old={"ref": bb.A + "deleted"})]})
        self.assertIn("w", result["scope"])

    def test_deleted_verification_link_invalidates_former_entity(self):
        store = ReviewStore([("f", "maxAge", "P1D")])
        result = ca.evaluate("review", store.post, {"now": NOW,
                             "changes": [change("v", "verifies", old={"ref": bb.A + "f"})]})
        self.assertEqual(result["scope"], ["f"])
        self.assertEqual(result["records"][0]["verdict"], "UNKNOWN")

    def test_missing_age_anchor_waits_for_graph_change(self):
        store = ReviewStore([("f", "maxAge", "P1D")])
        result = ca.evaluate("review", store.post, {"now": NOW, "items": ["f"]})
        self.assertEqual(result["records"][0]["verdict"], "UNKNOWN")
        self.assertIsNone(result["next_checks"]["f"])

    def test_due_without_graph_changes(self):
        store = ReviewStore([("f", "reviewAfter", '"2026-10-03T01:00:00Z"')])
        first = ca.evaluate("review", store.post, {"now": NOW, "items": ["f"]})
        due = first["next_checks"]["f"]
        self.assertEqual(due, NOW + 3600)
        after = ca.evaluate("review", store.post, {"now": due, "items": ["f"]})
        self.assertEqual(after["records"][0]["verdict"], "DUE")
        self.assertIsNone(after["next_checks"]["f"])

    def test_discovery_does_not_evaluate_population(self):
        store = Store(item("w", "open") + [("w", "blockedOn", "d")])
        calls = []
        def post(endpoint, body):
            calls.append(body["query"])
            return store.post(endpoint, body)
        result = ca.evaluate("blocked", post, {"discover": True, "now": NOW})
        self.assertEqual(result["items"], ["w"])
        self.assertEqual(len(calls), 6)
        self.assertFalse(any("observedStatus" in q for q in calls))

    def test_recorded_day_parity_close_reopen_remove_and_add(self):
        store = Store(item("w", "open") + item("other", "open") + item("d", "open", obs="od")
                      + [("w", "blockedOn", "d"), ("other", "blockedOn", "d")])
        state = {r["item"]: r for r in bb.evaluate(store.post)}
        day = [("od", "observedStatus", "open", "closed"),
               ("od", "observedStatus", "closed", "open"),
               ("w", "blockedOn", "d", None),
               ("w", "blockedOn", None, "d"),
               ("od", "observedStatus", "open", "closed")]
        for step, (subject, prop, old, new) in enumerate(day):
            if old is not None:
                store.t.discard((subject, prop, old))
            if new is not None:
                store.t.add((subject, prop, new))
            result = ca.evaluate("blocked", store.post, {"now": NOW + step * 3600,
                                 "changes": [change(subject, prop, new, old)]})
            for key in result["scope"]:
                state.pop(key, None)
            state.update((r["item"], r) for r in result["records"])
            self.assertEqual(state, {r["item"]: r for r in bb.evaluate(store.post)}, (subject, prop, new))


if __name__ == "__main__":
    unittest.main()
