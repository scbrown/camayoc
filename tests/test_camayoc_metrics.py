"""The exposition and the push contract, offline.

Deliberately no network: the delivery proof is a real run against a real gateway
read back from Prometheus (docs/metrics.md), and a test that reached the gateway
would pass or fail on the state of the machine it ran on — the wrong property for
a regression guarding a text format and a URL shape.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import camayoc_metrics as m


class Exposition(unittest.TestCase):
    def test_labels_are_sorted_so_output_is_deterministic(self):
        out = m.exposition([("x", {"b": "2", "a": "1"}, 5)])
        self.assertEqual(out, 'x{a="1",b="2"} 5\n')

    def test_a_metric_without_labels_emits_no_braces(self):
        self.assertEqual(m.exposition([("x", {}, 1)]), "x 1\n")

    def test_a_quote_in_a_label_cannot_break_the_line(self):
        out = m.exposition([("x", {"a": 'he said "hi"'}, 1)])
        self.assertIn(r'a="he said \"hi\""', out)

    def test_a_newline_in_a_label_cannot_forge_a_second_metric(self):
        """Exposition is line-oriented, so an unescaped newline in a label would
        let one sample inject another."""
        out = m.exposition([("x", {"a": "one\ntwo"}, 1)])
        self.assertEqual(len(out.strip().splitlines()), 1)


class PushRefusals(unittest.TestCase):
    """Every refusal must be NAMED, and none may raise: the caller is an ingest
    that must finish whatever the gateway does."""

    def test_an_unset_env_is_reported_not_raised(self):
        ok, why = m.push("j", "x 1\n", url="")
        self.assertFalse(ok)
        self.assertIn(m.ENV, why)

    def test_a_url_with_no_host_is_refused(self):
        ok, why = m.push("j", "x 1\n", url="not-a-url")
        self.assertFalse(ok)
        self.assertIn("no host", why)

    def test_an_unreachable_gateway_is_reported_not_raised(self):
        ok, why = m.push("j", "x 1\n", url="http://127.0.0.1:1/")
        self.assertFalse(ok)
        self.assertIn("unreachable", why)


if __name__ == "__main__":
    unittest.main()
