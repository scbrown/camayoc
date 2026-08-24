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

import importlib.util
import sys
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


if __name__ == "__main__":
    unittest.main()
