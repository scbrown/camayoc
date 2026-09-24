"""review_due: a declared age is evaluated at read time, and "cannot tell" stays UNKNOWN (aegis-kxjack)."""
from __future__ import annotations

import datetime as dt
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import review_due as rd  # noqa: E402

A = rd.A
NOW = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.timezone.utc)


class Store:
    """Triples (s, p, o) with local names; answers only single-pattern queries."""

    def __init__(self, triples):
        self.t = list(triples)

    def post(self, endpoint, body):
        if body.get("graph"):
            return {"rows": [], "truncated": False}
        q = body["query"]
        where = q[q.index("{"):]
        if " . " in where.strip("{} "):
            raise AssertionError(f"multi-pattern query (quipu 408s joins live): {q}")
        m = re.search(r"\{ \?s <" + re.escape(A) + r"(\w+)> \?v \}", q)
        if m:
            return self.rows([{"s": f"aegis:{s}"} for s, p, o in self.t if p == m.group(1)])
        m = re.search(r"\{ \?ver <" + re.escape(A) + r"verifies> <" + re.escape(A) + r"([^>]+)> \}", q)
        if m:
            return self.rows([{"ver": f"aegis:{s}"} for s, p, o in self.t if p == "verifies" and o == m.group(1)])
        m = re.search(r"\{ <" + re.escape(A) + r"([^>]+)> <" + re.escape(A) + r"(\w+)> \?v \}", q)
        if m:
            s0, p0 = m.groups()
            return self.rows([{"v": o} for s, p, o in self.t if s == s0 and p == p0])
        raise AssertionError(f"unexpected query {q}")

    @staticmethod
    def rows(r):
        return {"rows": r, "truncated": False}


def run(triples):
    return {r["entity"]: r for r in rd.evaluate(Store(triples).post, now=NOW)}


class ReviewAfter(unittest.TestCase):
    def test_a_passed_instant_is_due_and_names_its_owner(self):
        r = run([("f", "reviewAfter", '"2026-09-20T00:00:00Z"'), ("f", "ownedBy", "aegis:dearing")])["f"]
        self.assertEqual((r["verdict"], r["owner"]), ("DUE", "dearing"))

    def test_a_future_instant_is_not_due(self):
        self.assertEqual(run([("f", "reviewAfter", '"2026-10-01"')])["f"]["verdict"], "NOT_DUE")

    def test_an_unreadable_instant_is_unknown_not_fresh(self):
        self.assertEqual(run([("f", "reviewAfter", '"next tuesday"')])["f"]["verdict"], "UNKNOWN")


class MaxAge(unittest.TestCase):
    def verified(self, when):
        return [("v1", "verifies", "f"), ("v1", "verifiedAt", f'"{when}"')]

    def test_an_age_exceeded_since_the_last_verification_is_due(self):
        r = run([("f", "maxAge", '"P7D"')] + self.verified("2026-09-10T00:00:00Z"))["f"]
        self.assertEqual((r["verdict"], r["due_at"]), ("DUE", "2026-09-17T00:00:00+00:00"))

    def test_the_latest_verification_is_the_anchor(self):
        triples = [("f", "maxAge", '"P7D"'), ("v1", "verifies", "f"), ("v1", "verifiedAt", '"2026-09-01T00:00:00Z"'),
                   ("v2", "verifies", "f"), ("v2", "verifiedAt", '"2026-09-20T00:00:00Z"')]
        self.assertEqual(run(triples)["f"]["verdict"], "NOT_DUE")

    def test_an_unanchored_age_is_unknown_never_fresh_and_never_due(self):
        r = run([("f", "maxAge", '"P1W"')])["f"]
        self.assertEqual(r["verdict"], "UNKNOWN")
        self.assertIn("no anchor", r["basis"][0]["why"])

    def test_months_are_refused_as_ambiguous(self):
        self.assertIsNone(rd.parse_duration("P1M"))
        self.assertEqual(rd.parse_duration("PT1M"), dt.timedelta(minutes=1))
        self.assertEqual(rd.parse_duration("P2W"), dt.timedelta(weeks=2))
        self.assertIsNone(rd.parse_duration("P"))


class Combination(unittest.TestCase):
    def test_a_known_overdue_age_wins_over_an_unanchored_one(self):
        r = run([("f", "reviewAfter", '"2026-09-01"'), ("f", "maxAge", '"P7D"')])["f"]
        self.assertEqual(r["verdict"], "DUE")

    def test_all_known_and_ahead_is_not_due_but_one_unknown_is_unknown(self):
        self.assertEqual(run([("f", "reviewAfter", '"2026-12-01"'), ("f", "maxAge", '"P7D"')])["f"]["verdict"],
                         "UNKNOWN")

    def test_an_entity_with_no_declared_age_is_not_reported(self):
        self.assertEqual(run([("g", "ownedBy", "aegis:wu")]), {})

    def test_evidence_is_stable_and_moves_when_the_age_moves(self):
        a = run([("f", "reviewAfter", '"2026-09-20"')])["f"]["evidence"]
        self.assertEqual(a, run([("f", "reviewAfter", '"2026-09-20"')])["f"]["evidence"])
        self.assertNotEqual(a, run([("f", "reviewAfter", '"2026-09-21"')])["f"]["evidence"])


if __name__ == "__main__":
    unittest.main()
