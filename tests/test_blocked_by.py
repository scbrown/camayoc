"""blocked_by: whether a blocker still holds is evaluated at read time (aegis-c0awwp).

A small in-memory store answers the evaluator's single-pattern queries. The
arm that matters most: "could not tell" never rounds to UNBLOCKED, because
that is the direction an event consumer acts on.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import blocked_by as bb  # noqa: E402

A = bb.A
TODAY = dt.date(2026, 9, 24)


class Store:
    """Triples as (s, p, o) with local names for aegis terms."""

    def __init__(self, triples, asks=None):
        self.t = set(triples)
        self.asks = asks or {}

    def post(self, endpoint, body):
        q = body["query"]
        if body.get("graph"):
            return {"rows": [], "truncated": False}  # everything lives in default here
        if q.startswith("ASK"):
            if q in self.asks and isinstance(self.asks[q], Exception):
                raise self.asks[q]
            return {"result": self.asks.get(q, False)}
        return {"rows": self._select(q), "truncated": False}

    def _select(self, q):
        where = q[q.index("{"):]
        if " . " in where.strip("{} "):
            raise AssertionError(f"multi-pattern query (quipu 408s joins live): {q}")
        subj = re.search(r"\{ <" + re.escape(A) + r"([^>]+)>", q)
        s = subj.group(1) if subj else None
        if "> <%sblockedOn> ?t" % A in q or "?w <%sblockedOn> ?t" % A in q:
            return [{"w": f"aegis:{a}", "t": f"aegis:{c}"} for a, b, c in self.t
                    if b == "blockedOn" and (s is None or a == s)]
        if "> a ?t" in q:
            return [{"t": f"aegis:{c}"} for a, b, c in self.t if a == s and b == "a"]
        if f"> ?v }}" in q:
            pred = re.search(r"<" + re.escape(A) + r"([A-Za-z]+)> \?v", q).group(1)
            return [{"v": c} for a, b, c in self.t if a == s and b == pred]
        for pred, var in (("closedAt", "c"), ("resolvesOn", "d"), ("resolutionQuery", "q")):
            if f"<{A}{pred}> ?{var}" in q:
                return [{var: c} for a, b, c in self.t if a == s and b == pred]
        if " ?w <%sobserves> ?obs . ?obs " % A in q:
            raise AssertionError("multi-pattern join over the whole store: quipu 408s it live")
        if q.startswith("SELECT ?obs ?t WHERE { ?obs <%sobservedBlockedOn> ?t }" % A):
            return [{"obs": f"aegis:{o}", "t": f"aegis:{t}"} for o, b, t in self.t if b == "observedBlockedOn"]
        m = re.search(r"\?w <" + re.escape(A) + r"observes> <" + re.escape(A) + r"([^>]+)>", q)
        if m:
            return [{"w": f"aegis:{w}"} for w, b, o in self.t if b == "observes" and o == m.group(1)]
        if f"<{A}observedBlockedOn> ?t" in q:
            return [{"t": f"aegis:{c}"} for a, b, c in self.t if a == s and b == "observedBlockedOn"]
        if f"<{A}observes> ?obs" in q:
            return [{"obs": f"aegis:{o}"} for a, b, o in self.t if a == s and b == "observes"]
        if f"<{A}observedAt> ?at" in q:
            return [{"at": c} for a, b, c in self.t if a == s and b == "observedAt"]
        for pred, var in (("observedStatus", "st"), ("observedValue", "v")):
            if f"<{A}{pred}> ?{var}" in q:
                return [{var: c} for a, b, c in self.t if a == s and b == pred]
        raise AssertionError(f"unexpected query {q}")


def item(name, status=None, at="2026-09-20T00:00:00Z", obs=None):
    out = [(name, "a", "WorkItem")]
    if status:
        o = obs or f"obs-{name}-{at}"
        out += [(name, "observes", o), (o, "observedAt", at), (o, "observedStatus", status)]
    return out


def run(store, **kw):
    kw.setdefault("probes", {})
    return {r["item"]: r for r in bb.evaluate(store.post, today=TODAY, **kw)}


class WorkItemTargets(unittest.TestCase):
    def test_all_dependencies_closed_is_unblocked(self):
        s = Store(item("w", "blocked") + item("d1", "closed") + [("w", "blockedOn", "d1")])
        self.assertEqual(run(s)["w"]["verdict"], "UNBLOCKED")

    def test_the_latest_observation_wins(self):
        s = Store(item("w", "blocked") + item("d", "open", at="2026-09-01T00:00:00Z", obs="o1")
                  + item("d", "closed", at="2026-09-23T00:00:00Z", obs="o2")
                  + [("w", "blockedOn", "d")])
        self.assertEqual(run(s)["w"]["verdict"], "UNBLOCKED")

    def test_one_open_dependency_is_blocked(self):
        s = Store(item("w", "blocked") + item("d1", "closed") + item("d2", "in_progress")
                  + [("w", "blockedOn", "d1"), ("w", "blockedOn", "d2")])
        self.assertEqual(run(s)["w"]["verdict"], "BLOCKED")

    def test_closedAt_on_the_workitem_counts_as_closed(self):
        s = Store(item("w", "open") + item("d") + [("d", "closedAt", "2026-09-22"), ("w", "blockedOn", "d")])
        self.assertEqual(run(s)["w"]["verdict"], "UNBLOCKED")

    def test_unknown_never_rounds_to_unblocked(self):
        s = Store(item("w", "open") + item("d1", "closed") + item("d2")  # d2: no status at all
                  + [("w", "blockedOn", "d1"), ("w", "blockedOn", "d2")])
        self.assertEqual(run(s)["w"]["verdict"], "UNKNOWN")

    def test_a_closed_item_is_left_out(self):
        s = Store(item("w", "closed") + item("d1", "open") + [("w", "blockedOn", "d1")])
        self.assertNotIn("w", run(s))


class TrackerProjection(unittest.TestCase):
    """aegis-3b3nrb: tracker dependencies live on the versioned Observation."""

    def obs(self, item, name, at, status, deps=()):
        return ([(item, "observes", name), (name, "observedAt", at), (name, "observedStatus", status)]
                + [(name, "observedBlockedOn", d) for d in deps])

    def test_a_projected_dependency_blocks(self):
        s = Store([("w", "a", "WorkItem")] + self.obs("w", "o1", "2026-09-20", "blocked", ["d"])
                  + item("d", "open"))
        self.assertEqual(run(s)["w"]["verdict"], "BLOCKED")

    def test_a_dependency_removed_in_the_newest_observation_no_longer_blocks(self):
        s = Store([("w", "a", "WorkItem")]
                  + self.obs("w", "o1", "2026-09-20", "blocked", ["d"])  # older: blocked on d
                  + self.obs("w", "o2", "2026-09-23", "open", [])         # newest: dependency gone
                  + item("d", "open"))
        self.assertNotIn("w", run(s), "an item with no current blocker is not reported")

    def test_one_item_reads_only_its_latest_observation(self):
        s = Store([("w", "a", "WorkItem")] + self.obs("w", "o1", "2026-09-20", "blocked", ["d"])
                  + item("d", "open"))
        self.assertEqual(run(s, item="w")["w"]["verdict"], "BLOCKED")

    def test_status_falls_back_to_the_observation_snapshot(self):
        s = Store(item("w", "open") + [("d", "a", "WorkItem"), ("d", "observes", "od"),
                  ("od", "observedAt", "2026-09-22"), ("od", "observedValue", '{"status": "closed"}'),
                  ("w", "blockedOn", "d")])
        self.assertEqual(run(s)["w"]["verdict"], "UNBLOCKED")


class TypedProbes(unittest.TestCase):
    """pr-merged / release-installed / ci-green: the parameters come from the
    graph, the probe code is fixed in camayoc (aegis-c0awwp)."""

    def case(self, kind, props, answer):
        calls = []
        def probe(*args):
            calls.append(args)
            return answer
        s = Store(item("w", "open") + [("b", "a", "Blocker"), ("b", "blockerKind", kind)]
                  + [("b", k, v) for k, v in props.items()] + [("w", "blockedOn", "b")])
        return run(s, probes={kind: probe})["w"]["verdict"], calls

    def test_each_probe_gets_its_parameters_and_its_answer_decides(self):
        for kind, props, want_args in (
                ("pr-merged", {"prRef": "scbrown/quipu#274"}, ("scbrown/quipu#274",)),
                ("release-installed", {"tool": "yupana", "minVersion": "0.10.0"}, ("yupana", "0.10.0")),
                ("ci-green", {"repoRef": "scbrown/quipu@main"}, ("scbrown/quipu@main",))):
            for answer, want in ((True, "UNBLOCKED"), (False, "BLOCKED"), (None, "UNKNOWN")):
                with self.subTest(kind=kind, answer=answer):
                    verdict, calls = self.case(kind, props, answer)
                    self.assertEqual(verdict, want)
                    self.assertEqual(calls, [want_args])

    def test_a_missing_parameter_is_unknown_and_nothing_is_probed(self):
        verdict, calls = self.case("pr-merged", {}, True)
        self.assertEqual((verdict, calls), ("UNKNOWN", []))

    def test_the_real_probes_refuse_malformed_parameters_without_running_anything(self):
        self.assertIsNone(bb.probe_pr_merged("quipu 274; rm -rf ~"))
        self.assertIsNone(bb.probe_release_installed("yupana; rm -rf ~", "0.10.0"))
        self.assertIsNone(bb.probe_release_installed("yupana", "latest"))
        self.assertIsNone(bb.probe_ci_green("not a repo ref"))

    def test_version_comparison_pads_and_orders_numerically(self):
        self.assertEqual(bb._version_tuple("yupana 0.10.0 (abc)"), (0, 10, 0))
        orig = bb._run
        try:
            bb._run = lambda argv: "yupana 0.9.12\n"
            self.assertFalse(bb.probe_release_installed("yupana", "0.10"))
            bb._run = lambda argv: "yupana 0.10.0\n"
            self.assertTrue(bb.probe_release_installed("yupana", "0.10"))
            bb._run = lambda argv: None
            self.assertIsNone(bb.probe_release_installed("yupana", "0.10"))
        finally:
            bb._run = orig


class Planes(unittest.TestCase):
    def test_declared_blockers_count_and_inferred_ones_do_not(self):
        import planes
        gs = bb.graphs()
        self.assertIn(planes.plane_for("declared"), gs)
        self.assertIn(planes.plane_for("observed"), gs)
        self.assertNotIn(planes.plane_for("inferred"), gs)


class ConditionTargets(unittest.TestCase):
    def blocker(self, name, **props):
        return [(name, "a", "Blocker")] + [(name, k, v) for k, v in props.items()]

    def test_a_date_blocker_resolves_on_its_date(self):
        past = Store(item("w", "open") + self.blocker("b", resolvesOn='"2026-09-24"^^xsd:date')
                     + [("w", "blockedOn", "b")])
        future = Store(item("w", "open") + self.blocker("b", resolvesOn='"2026-09-25"^^xsd:date')
                       + [("w", "blockedOn", "b")])
        self.assertEqual(run(past)["w"]["verdict"], "UNBLOCKED")
        self.assertEqual(run(future)["w"]["verdict"], "BLOCKED")

    def test_an_ask_true_resolves_and_false_blocks(self):
        ask = "ASK { ?r a <x> }"
        for answer, want in ((True, "UNBLOCKED"), (False, "BLOCKED")):
            s = Store(item("w", "open") + self.blocker("b", resolutionQuery=ask)
                      + [("w", "blockedOn", "b")], asks={ask: answer})
            self.assertEqual(run(s)["w"]["verdict"], want)

    def test_an_ask_that_fails_is_unknown_not_resolved(self):
        ask = "ASK { broken"
        s = Store(item("w", "open") + self.blocker("b", resolutionQuery=ask)
                  + [("w", "blockedOn", "b")], asks={ask: RuntimeError("HTTP 400")})
        self.assertEqual(run(s)["w"]["verdict"], "UNKNOWN")

    def test_a_blocker_with_no_resolution_is_unknown(self):
        s = Store(item("w", "open") + self.blocker("b") + [("w", "blockedOn", "b")])
        self.assertEqual(run(s)["w"]["verdict"], "UNKNOWN")

    def test_one_item_by_id(self):
        s = Store(item("w", "open") + item("d", "closed") + item("v", "open") + item("e", "open")
                  + [("w", "blockedOn", "d"), ("v", "blockedOn", "e")])
        self.assertEqual(list(run(s, item="w")), ["w"])


class AdapterRecord(unittest.TestCase):
    """aegis-2qo001: what the emitter keys transitions and delivery on."""

    def base(self, dep_status="open"):
        return (item("w", "blocked") + item("d", dep_status) + [("w", "blockedOn", "d"),
                ("obs-w-2026-09-20T00:00:00Z", "observedValue", '{"status": "blocked", "assignee": "grant"}')])

    def test_the_record_names_item_verdict_evidence_assignee_and_targets(self):
        r = run(Store(self.base()))["w"]
        self.assertEqual((r["verdict"], r["assignee"]), ("BLOCKED", "grant"))
        self.assertEqual([b["target"] for b in r["blockers"]], ["d"])
        self.assertTrue(r["evidence"].startswith("sha256:"))

    def test_the_same_facts_give_the_same_evidence_on_every_run(self):
        self.assertEqual(run(Store(self.base()))["w"]["evidence"], run(Store(self.base()))["w"]["evidence"])

    def test_a_blocker_changing_state_changes_the_evidence(self):
        self.assertNotEqual(run(Store(self.base("open")))["w"]["evidence"],
                            run(Store(self.base("closed")))["w"]["evidence"])

    def test_no_snapshot_means_no_assignee_not_a_guess(self):
        s = Store(item("w", "blocked") + item("d", "open") + [("w", "blockedOn", "d")])
        self.assertIsNone(run(s)["w"]["assignee"])


if __name__ == "__main__":
    unittest.main()
