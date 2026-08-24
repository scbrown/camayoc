"""Authority-gated plane promotion — camayoc-mip.

Almost every test here asserts a REFUSAL. That is the right shape for a
governance mechanism: the happy path is one line, and every value it has comes
from what it declines to do. A promotion gate that has never been observed to
say no is the same defect the gate probes were written to catch, one layer up.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

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


def ok(**over):
    """A promotion that should succeed, so each test can break exactly one thing."""
    args = dict(
        subject="http://ex/fact/1",
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


class PromotionRecordTests(unittest.TestCase):
    def test_the_record_names_where_the_fact_came_from(self):
        """A promoted fact must be distinguishable from a directly-observed
        one, or promotion launders provenance instead of recording it."""
        episode, close = promote_plane.promote(**ok())
        self.assertIsNone(close)  # no --source-episode: interval left open, said out loud
        body = episode["episode_body"]
        self.assertIn("promotedFrom", body)
        self.assertIn("promotedInto", body)
        self.assertIn("promotedBy", body)
        self.assertIn("authoredBy", body)

    def test_the_promotion_event_carries_its_own_falsifier(self):
        """camayoc's own shape rule applied to camayoc's own mechanism: the
        promotion is a Verification-shaped claim and must name what would
        disprove it."""
        self.assertIn("falsifier", promote_plane.promote(**ok())[0]["episode_body"])

    def test_the_promotion_event_is_tagged_observed_not_inferred(self):
        """The MOVE is an observed event even though the fact it moves was
        inferred. Tagging the promotion itself `inferred` would put the audit
        record in the plane it is supposed to be moving things out of."""
        self.assertIn('aegis:sourceKind      "observed"',
                      promote_plane.promote(**ok())[0]["episode_body"])

    def test_the_reason_survives_into_the_record(self):
        episode, _ = promote_plane.promote(**ok(reason="reproduced twice on staging"))
        self.assertIn("reproduced twice on staging", episode["episode_body"])


if __name__ == "__main__":
    sys.exit(unittest.main())
