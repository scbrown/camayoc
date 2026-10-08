"""Authority-gated plane promotion — camayoc-mip.

Almost every test here asserts a REFUSAL. That is the right shape for a
governance mechanism: the happy path is one line, and every value it has comes
from what it declines to do. A promotion gate that has never been observed to
say no is the same defect the gate probes were written to catch, one layer up.
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quipu_bin_guard import QUIPU_SERVER, requires_quipu_server  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


promote_plane = load("promote_plane")

GRANTS = {"alice": ["crew:records"], "bob": ["crew:records", "crew:declared"]}
T1 = ("<http://ex/fact/1>", "<http://ex/p>", "<http://ex/o>")


def ok(**over):
    """A promotion that should succeed, so each test can break exactly one thing."""
    args = dict(
        triples=[T1],
        target_plane="crew:records",
        promoted_by="alice",
        authored_by="claude",
        reason="corroborated by the deploy log",
        timestamp="2026-01-01T00:00:00Z",
        grants=GRANTS,
    )
    args.update(over)
    return args


class PromotionGateTests(unittest.TestCase):
    def test_a_fully_authorised_promotion_succeeds(self):
        """The control. Without this, every refusal below could be passing
        because the function refuses everything."""
        episode, close = promote_plane.promote(**ok())
        self.assertIsNone(close)  # no --source-episode: interval left open, said out loud
        self.assertEqual(
            promote_plane.planes.PLANES["crew:records"]["iri"], episode["graph"]
        )
        self.assertEqual("alice", episode["actor"])

    def test_promotion_without_authority_over_the_target_is_refused(self):
        with self.assertRaises(promote_plane.PromotionRefused) as c:
            promote_plane.promote(**ok(target_plane="crew:declared"))
        self.assertIn("holds no authority", str(c.exception))

    def test_self_promotion_is_refused(self):
        """The rule the skill states to agents in prose, enforced here."""
        with self.assertRaises(promote_plane.PromotionRefused) as c:
            promote_plane.promote(
                **ok(promoted_by="claude", authored_by="claude",
                     grants={"claude": ["crew:records"]})
            )
        self.assertIn("cannot promote it", str(c.exception))

    def test_self_promotion_is_refused_even_with_authority(self):
        """Ordering matters: the self-promotion gate must run whether or not
        the principal holds the grant, or a principal with authority over a
        plane could launder its own output into it."""
        with self.assertRaises(promote_plane.PromotionRefused) as c:
            promote_plane.promote(
                **ok(promoted_by="alice", authored_by="alice")
            )
        self.assertIn("cannot promote it", str(c.exception))

    def test_a_sideways_or_downward_move_is_not_a_promotion(self):
        with self.assertRaises(promote_plane.PromotionRefused) as c:
            promote_plane.promote(**ok(target_plane="crew:inferred",
                                       grants={"alice": ["crew:inferred"]}))
        self.assertIn("does not outrank", str(c.exception))

    def test_an_unknown_target_plane_is_refused(self):
        with self.assertRaises(promote_plane.PromotionRefused):
            promote_plane.promote(**ok(target_plane="crew:vibes"))

    def test_a_promotion_must_state_a_reason(self):
        """An unexplained trust upgrade is precisely the record a later reader
        cannot assess."""
        with self.assertRaises(promote_plane.PromotionRefused) as c:
            promote_plane.promote(**ok(reason="   "))
        self.assertIn("must state its reason", str(c.exception))


class AuthorityFileTests(unittest.TestCase):
    """The grant file fails CLOSED. This is the half most likely to be got
    wrong, because the insecure behaviour is also the convenient one."""

    def test_a_missing_authority_file_grants_nobody(self):
        with tempfile.TemporaryDirectory() as d:
            promote_plane.AUTHORITY_PATH = Path(d) / "absent.json"
            self.assertEqual({}, promote_plane.load_authority())

    def test_a_missing_file_therefore_refuses_every_promotion(self):
        with tempfile.TemporaryDirectory() as d:
            promote_plane.AUTHORITY_PATH = Path(d) / "absent.json"
            args = ok()
            del args["grants"]
            with self.assertRaises(promote_plane.PromotionRefused):
                promote_plane.promote(**args)

    def test_an_unreadable_authority_file_refuses_rather_than_permits(self):
        """'Could not look' is not 'no restrictions'. Treating a malformed
        grant file as unrestricted is what makes an authority check worthless."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "broken.json"
            p.write_text("{not json")
            promote_plane.AUTHORITY_PATH = p
            with self.assertRaises(promote_plane.PromotionRefused) as c:
                promote_plane.load_authority()
            self.assertIn("fails closed", str(c.exception))

    def test_a_well_formed_file_is_honoured(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "auth.json"
            p.write_text(json.dumps({"carol": ["crew:records"]}))
            promote_plane.AUTHORITY_PATH = p
            self.assertEqual({"carol": ["crew:records"]}, promote_plane.load_authority())


class ShippedAuthorityTests(unittest.TestCase):
    """The SHIPPED grant set is pinned exactly. A grant is a human authority
    decision; widening it must fail here rather than pass silently."""

    def setUp(self):
        # Restore the module-global afterwards so later tests are not left
        # reading the shipped file (sattler review nit on camayoc#77).
        saved = promote_plane.AUTHORITY_PATH
        self.addCleanup(setattr, promote_plane, "AUTHORITY_PATH", saved)

    def test_the_shipped_grants_are_exactly_the_decided_ones(self):
        promote_plane.AUTHORITY_PATH = ROOT / "config" / "plane-authority.json"
        self.assertEqual(
            {"publish_work_cost.py": ["read:crew:records"], "sattler": ["crew:declared"]},
            promote_plane.load_authority(),
        )

    def test_the_grantee_still_cannot_promote_its_own_output(self):
        with self.assertRaises(promote_plane.PromotionRefused):
            promote_plane.check_not_self_promotion("sattler", "sattler")


class PromotionRecordTests(unittest.TestCase):
    def test_the_record_names_where_the_fact_came_from(self):
        """A promoted fact must be distinguishable from a directly-observed
        one, or promotion launders provenance instead of recording it."""
        episode, close = promote_plane.promote(**ok())
        self.assertIsNone(close)  # no --source-episode: interval left open, said out loud
        body = episode["turtle"]
        self.assertIn("promotedFrom", body)
        self.assertIn("promotedInto", body)
        self.assertIn("promotedBy", body)
        self.assertIn("authoredBy", body)

    def test_the_promotion_event_carries_its_own_falsifier(self):
        """camayoc's own shape rule applied to camayoc's own mechanism: the
        promotion is a Verification-shaped claim and must name what would
        disprove it."""
        self.assertIn("falsifier", promote_plane.promote(**ok())[0]["turtle"])

    def test_the_promotion_event_is_tagged_observed_not_inferred(self):
        """The MOVE is an observed event even though the fact it moves was
        inferred. Tagging the promotion itself `inferred` would put the audit
        record in the plane it is supposed to be moving things out of."""
        self.assertIn('aegis:sourceKind      "observed"',
                      promote_plane.promote(**ok())[0]["turtle"])

    def test_the_reason_survives_into_the_record(self):
        episode, _ = promote_plane.promote(**ok(reason="reproduced twice on staging"))
        self.assertIn("reproduced twice on staging", episode["turtle"])


class PromotedTriplesTests(unittest.TestCase):
    """aegis-is257g: a promotion must ASSERT the facts it moves, not only a
    record that they moved. The record-only version moved zero edges while
    looking done, and with --source-episode it would have dropped them."""

    def test_the_write_asserts_every_promoted_triple_in_the_target_graph(self):
        t2 = ("<http://ex/fact/2>", "<http://ex/p>", '"a literal"@en')
        write, _ = promote_plane.promote(**ok(triples=[T1, t2], target_plane="crew:declared", promoted_by="bob"))
        self.assertEqual(promote_plane.planes.PLANES["crew:declared"]["iri"], write["graph"])
        for s_, p_, o_ in (T1, t2):
            self.assertIn(f"{s_} {p_} {o_} .", write["turtle"])

    def test_a_triple_absent_from_the_source_plane_is_refused(self):
        with self.assertRaises(promote_plane.PromotionRefused) as c:
            promote_plane.promote(**ok(source_has=lambda t: t != T1))
        self.assertIn("not in crew:inferred", str(c.exception))

    def test_a_triple_present_in_the_source_plane_passes_the_gate(self):
        write, _ = promote_plane.promote(**ok(source_has=lambda t: True))
        self.assertIn(" ".join(T1), write["turtle"])

    def test_an_empty_edge_set_is_refused(self):
        with self.assertRaises(promote_plane.PromotionRefused):
            promote_plane.promote(**ok(triples=[]))

    def test_the_record_iri_is_the_edge_set_digest_not_the_timestamp(self):
        """Old names embedded a hardcoded timestamp and collided across runs."""
        t2 = ("<http://ex/fact/2>", "<http://ex/p>", "<http://ex/o>")
        a, _ = promote_plane.promote(**ok(triples=[T1, t2], timestamp="2026-10-07T00:00:00Z"))
        b, _ = promote_plane.promote(**ok(triples=[t2, T1], timestamp="2026-10-08T00:00:00Z"))
        c, _ = promote_plane.promote(**ok(triples=[T1]))
        self.assertEqual(a["digest"], b["digest"])  # same edge set, any order, any time
        self.assertNotEqual(a["digest"], c["digest"])
        self.assertIn(f"urn:camayoc:plane-promotion:{a['digest']}", a["turtle"])
        self.assertNotIn("2026-10-07T00:00:00Z>", a["turtle"])

    def test_the_falsifier_names_the_promoted_triples_not_the_subject(self):
        write, _ = promote_plane.promote(**ok())
        self.assertIn("promoted triples is absent from the target plane", write["turtle"])

    def test_the_default_timestamp_is_now_not_a_constant(self):
        self.assertRegex(promote_plane._now(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertNotEqual("2026-01-01T00:00:00Z", promote_plane._now())

    def test_ntriples_parsing_accepts_iris_and_literals_and_refuses_junk(self):
        got = promote_plane.parse_ntriples(
            "# comment\n\n<http://a/s> <http://a/p> <http://a/o> .\n"
            '<http://a/s> <http://a/p> "x \\"q\\""@en .\n'
            '<http://a/s> <http://a/p> "5"^^<http://www.w3.org/2001/XMLSchema#integer> .\n'
        )
        self.assertEqual(3, len(got))
        with self.assertRaises(promote_plane.PromotionRefused):
            promote_plane.parse_ntriples("<http://a/s> <http://a/p> bare-word .")


@requires_quipu_server
class PromotionAgainstARealStoreTests(unittest.TestCase):
    """End to end on an ephemeral quipu-server: after a promotion the TRIPLE is
    in crew:declared. A record-only promote_plane (the aegis-is257g defect,
    rebuilt as a mutant) must fail this same check."""

    S, P, O = "<http://ex/directive/1>", "<http://aegis.gastown.local/ontology/governedBy>", "<http://ex/policy/1>"

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        cls.port = sock.getsockname()[1]
        sock.close()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.proc = subprocess.Popen(
            [QUIPU_SERVER, "--db", str(Path(cls.temp.name) / "store.db"), "--bind", f"127.0.0.1:{cls.port}"],
            cwd=cls.temp.name, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(50):
            try:
                cls.call("/health")
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("ephemeral quipu-server did not start")
        saved = promote_plane.planes.SERVER
        promote_plane.planes.SERVER = cls.base
        try:
            promote_plane.planes.ensure_planes("2026-10-07T00:00:00Z")
        finally:
            promote_plane.planes.SERVER = saved
        inferred = promote_plane.planes.PLANES["crew:inferred"]["iri"]
        cls.call("/knot", {"turtle": f"{cls.S} {cls.P} {cls.O} .", "graph": inferred, "actor": "test"})
        cls.auth = Path(cls.temp.name) / "auth.json"
        cls.auth.write_text(json.dumps({"bob": ["crew:declared"]}))
        cls.edges = Path(cls.temp.name) / "edges.nt"
        cls.edges.write_text(f"{cls.S} {cls.P} {cls.O} .\n")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        cls.temp.cleanup()

    @classmethod
    def call(cls, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(cls.base + path, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or b"{}")

    def ask(self, plane):
        iri = promote_plane.planes.PLANES[plane]["iri"]
        return self.call("/query", {"query": f"ASK {{ GRAPH <{iri}> {{ {self.S} {self.P} {self.O} }} }}"})["result"]

    def run_script(self, script):
        env = dict(os.environ, QUIPU_SERVER=self.base, CAMAYOC_AUTHORITY=str(self.auth))
        env["QUIPU_AUTH_TOKEN"] = "isolated-test-fixture"
        return subprocess.run(
            [sys.executable, str(script), "--triples-file", str(self.edges), "--to", "crew:declared",
             "--by", "bob", "--authored-by", "claude", "--reason", "integration test"],
            env=env, capture_output=True, text=True, timeout=60,
        )

    def test_1_the_mutant_record_only_promotion_moves_nothing(self):
        """Control first, on the clean store: the record-only shape must leave
        crew:declared without the edge, and the script must say so (exit 5)."""
        self.assertTrue(self.ask("crew:inferred"))
        self.assertFalse(self.ask("crew:declared"))
        mutant_dir = Path(self.temp.name) / "mutant"
        mutant_dir.mkdir()
        (mutant_dir / "planes.py").write_text((ROOT / "scripts" / "planes.py").read_text())
        (mutant_dir / "quipu_auth.py").write_text((ROOT / "scripts" / "quipu_auth.py").read_text())
        source = (ROOT / "scripts" / "promote_plane.py").read_text()
        old = 'f"{facts}\\n\\n{links}\\n\\n{record}"'
        self.assertIn(old, source, "mutation site moved; update this test")
        (mutant_dir / "promote_plane.py").write_text(source.replace(old, 'f"{links}\\n\\n{record}"'))
        result = self.run_script(mutant_dir / "promote_plane.py")
        self.assertEqual(5, result.returncode, result.stderr)
        self.assertFalse(self.ask("crew:declared"))

    def test_2_a_real_promotion_puts_the_triple_in_the_target_plane(self):
        result = self.run_script(ROOT / "scripts" / "promote_plane.py")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("all read back", result.stdout)
        self.assertTrue(self.ask("crew:declared"))
        self.assertTrue(self.ask("crew:inferred"), "no --source-episode: the source interval stays open")


if __name__ == "__main__":
    sys.exit(unittest.main())
