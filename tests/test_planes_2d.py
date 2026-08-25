"""Two-dimensional ingress routing and the window IRI scheme.

Routing gained a second dimension (source_kind x data_kind) for the shuttle
workflow engine and quipu's deep freeze. The invariants pinned here:

- the default `data_kind="knowledge"` preserves EVERY pre-2-D caller, because
  every static plane IS a knowledge plane — a documented fact, not a silent
  fallback;
- any pair with no plane refuses (never ROOT); `operational` refuses pointing
  at the window scheme;
- the window IRI scheme is what shuttle reimplements, so this pin is the only
  thing keeping producer and convention from drifting;
- the promotion move rule: assert in the target, CLOSE the source episode
  (a bitemporal retraction), record which; no source named => the record says
  `sourceLeftOpen true` out loud.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


planes = load("planes")
windows = load("windows")
promote_plane = load("promote_plane")


class TwoDimensionalRoutingTests(unittest.TestCase):
    def test_every_static_plane_declares_the_knowledge_kind(self):
        """The premise the default rests on. If a plane ever declares another
        kind, the default stops being a documented fact and this fails."""
        for name, spec in planes.PLANES.items():
            self.assertEqual("knowledge", spec["data_kind"], name)

    def test_the_default_kind_preserves_every_pre_2d_caller(self):
        for kind in ("observed", "declared", "inferred"):
            self.assertEqual(planes.plane_for(kind), planes.plane_for(kind, "knowledge"))

    def test_operational_data_refuses_the_static_planes(self):
        """Operational data is window-addressed so completed windows can be
        frozen whole. Routing it into a static plane would make the plane
        unfreezable and the window scheme decorative."""
        with self.assertRaises(planes.PlaneError) as c:
            planes.plane_for("observed", "operational")
        self.assertIn("windows.py", str(c.exception))

    def test_an_unknown_kind_refuses_rather_than_defaulting(self):
        with self.assertRaises(planes.PlaneError) as c:
            planes.plane_for("observed", "archive")
        self.assertIn("Refusing to default to ROOT", str(c.exception))

    def test_an_unknown_source_kind_still_refuses(self):
        with self.assertRaises(planes.PlaneError):
            planes.plane_for("hallucinated")


class WindowSchemeTests(unittest.TestCase):
    def test_the_window_iri_scheme_is_pinned(self):
        """Shuttle reimplements this scheme (no cross-repo import); this pin
        is what keeps the two from drifting."""
        self.assertEqual(
            planes.PLANE_NS.replace("/plane/", "/window/") + "shuttle/runs/2026-08",
            windows.window_iri("shuttle/runs", "2026-08"),
        )

    def test_window_family_and_month_are_validated_never_guessed(self):
        for family, month in [
            ("Shuttle/Runs", "2026-08"),
            ("shuttle runs", "2026-08"),
            ("", "2026-08"),
            ("shuttle/runs", "2026-13"),
            ("shuttle/runs", "202608"),
            ("shuttle/runs", "aug-2026"),
        ]:
            with self.assertRaises(planes.PlaneError, msg=f"{family}/{month}"):
                windows.window_iri(family, month)

    def test_the_window_label_is_operational_fresh_solerecord(self):
        """soleRecord is honest: until a freeze, the window graph is the only
        copy. The freeze relabels to archive/backed."""
        self.assertEqual(
            {"kind": "operational", "freshness": "fresh", "durability": "soleRecord"},
            windows.WINDOW_LABEL,
        )


class MoveRuleTests(unittest.TestCase):
    GRANTS = {"alice": ["crew:records"]}

    def _promote(self, **over):
        args = dict(
            subject="http://ex/fact/1",
            target_plane="crew:records",
            promoted_by="alice",
            authored_by="claude",
            reason="corroborated",
            timestamp="2026-01-01T00:00:00Z",
            grants=self.GRANTS,
        )
        args.update(over)
        return promote_plane.promote(**args)

    def test_naming_the_source_episode_produces_the_close(self):
        episode, close = self._promote(source_episode="crew-briefing-2026-07")
        self.assertEqual("crew-briefing-2026-07", close["episode"])
        self.assertEqual("preserve", close["on_orphan"])
        self.assertIn("camayoc:sourceLeftOpen false", episode["episode_body"])

    def test_without_a_source_episode_the_record_says_left_open(self):
        episode, close = self._promote()
        self.assertIsNone(close)
        self.assertIn("camayoc:sourceLeftOpen true", episode["episode_body"])

    def test_the_record_derives_from_the_promoted_subject(self):
        episode, _ = self._promote(source_episode="ep")
        self.assertIn("prov:wasDerivedFrom", episode["episode_body"])


class MoveRuleCommitOrderTests(unittest.TestCase):
    """The two-write commit path, which `promote()` alone cannot exercise.

    Assert-then-close is chosen so that a HALF-APPLIED move is the recoverable
    half: the fact readable in two planes at different trust, visibly. The
    branch that says so is `main`'s exit 4, and a rule whose failure branch is
    untested is a rule that has only ever been observed succeeding.
    """

    GRANTS = {"alice": ["crew:records"]}

    ARGV = [
        "promote_plane.py",
        "--subject", "http://ex/fact/1",
        "--to", "crew:records",
        "--by", "alice",
        "--authored-by", "claude",
        "--reason", "corroborated by the deploy log",
        "--source-episode", "crew-briefing-2026-07",
    ]

    def _run(self, retract_fails: bool, argv=None):
        """Run `main` with the network replaced by a recorder.

        Returns (exit code, posted paths, stderr text).
        """
        posted: list[str] = []

        def fake_post(path, body):
            posted.append(path)
            if retract_fails and path == "/episode/retract":
                # promote_plane loads its OWN planes instance, so the error
                # `main` catches is that module's class, not this file's.
                raise promote_plane.planes.PlaneError("HTTP 503 store unavailable")
            return {}

        err = io.StringIO()
        with mock.patch.object(promote_plane.planes, "_post", fake_post), \
             mock.patch.object(promote_plane, "load_authority", lambda: self.GRANTS), \
             mock.patch.object(sys, "argv", argv or self.ARGV), \
             contextlib.redirect_stderr(err):
            code = promote_plane.main()
        return code, posted, err.getvalue()

    def test_the_assert_is_committed_before_the_close(self):
        """Commit ORDER, not merely both writes: close-then-failed-assert would
        lose the promoted fact outright, which is the unrecoverable direction."""
        code, posted, _ = self._run(retract_fails=False)
        self.assertEqual(0, code)
        self.assertEqual(["/episode", "/episode/retract"], posted)

    def test_a_failed_close_exits_4_rather_than_reporting_success(self):
        code, posted, _ = self._run(retract_fails=True)
        self.assertEqual(4, code)
        self.assertEqual(["/episode", "/episode/retract"], posted)

    def test_a_failed_close_says_the_fact_is_now_in_two_planes(self):
        """The operator has to learn the state from the failure itself; an
        exit code alone leaves a half-applied move looking like a lost one."""
        _, _, err = self._run(retract_fails=True)
        self.assertIn("PROMOTED but source close FAILED", err)
        self.assertIn("readable in both planes", err)

    def test_the_failure_hands_back_the_exact_retry_body(self):
        """Recovery must not require reconstructing the retraction by hand —
        that is where an `on_orphan` default would silently differ."""
        _, _, err = self._run(retract_fails=True)
        self.assertIn("POST /episode/retract", err)
        payload = json.loads(err[err.index("{"):err.rindex("}") + 1])
        self.assertEqual(
            {
                "episode": "crew-briefing-2026-07",
                "timestamp": "2026-01-01T00:00:00Z",
                "actor": "alice",
                "on_orphan": "preserve",
            },
            payload,
        )

    def test_without_a_source_episode_no_close_is_attempted_at_all(self):
        """The left-open path must not post an empty retraction: a retract with
        no episode named is exactly the close that silently never happened."""
        argv = [a for a in self.ARGV if a not in ("--source-episode", "crew-briefing-2026-07")]
        code, posted, _ = self._run(retract_fails=True, argv=argv)
        self.assertEqual(0, code)
        self.assertEqual(["/episode"], posted)


if __name__ == "__main__":
    unittest.main()
