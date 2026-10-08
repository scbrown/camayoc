"""aegis-qx96wr: instants parse on the production interpreter (Python 3.10).

The tracker writes observedAt with NANOSECONDS. Python 3.11+ parses that;
3.10 (the chaski host) does not, so every idleLimit anchor was None and no
lapse ever fired. The normaliser is tested as TEXT, so the test holds on any
interpreter, and ci.yml also runs the adapter tests under 3.10."""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import review_due as rd

UTC = dt.timezone.utc


class Instants(unittest.TestCase):
    def test_the_normaliser_gives_310_compatible_text(self):
        self.assertEqual(rd._iso_text("2026-10-01T13:10:47.150614617Z"), "2026-10-01T13:10:47.150614+00:00")
        self.assertEqual(rd._iso_text("2026-10-01T13:10:47.15Z"), "2026-10-01T13:10:47.150000+00:00")
        self.assertEqual(rd._iso_text("2026-10-01T13:10:47Z"), "2026-10-01T13:10:47+00:00")

    def test_nanosecond_tracker_timestamps_parse(self):
        self.assertEqual(rd.parse_instant('"2026-10-01T13:10:47.150614617Z"'),
                         dt.datetime(2026, 10, 1, 13, 10, 47, 150614, tzinfo=UTC))
        self.assertEqual(rd.parse_instant("2026-09-25T20:58:57.155523207Z^^xsd:dateTime"),
                         dt.datetime(2026, 9, 25, 20, 58, 57, 155523, tzinfo=UTC))

    def test_existing_forms_still_parse(self):
        self.assertEqual(rd.parse_instant("2026-10-01"), dt.datetime(2026, 10, 1, tzinfo=UTC))
        self.assertEqual(rd.parse_instant("2026-10-01T13:10:47+02:00"),
                         dt.datetime(2026, 10, 1, 11, 10, 47, tzinfo=UTC))
        self.assertIsNone(rd.parse_instant("not a time"))


if __name__ == "__main__":
    unittest.main()
