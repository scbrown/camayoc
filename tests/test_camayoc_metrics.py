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


class TestGroupingKeyPartitionsSeries:
    """A pushgateway group is REPLACED WHOLESALE on every push to the same key.

    So a distinguishing label carried in the BODY partitions nothing: the second
    adapter to push destroys the first adapter's series, and the gateway returns
    success to both. Measured live on the sibling desire-path collector, written
    the same way on the same night — pushing source=claude-code then source=codex
    left only codex, of four plugins, and the surviving total read 4 where the
    truth was 2214. Wrong, not stale, and a plausible small number invites no
    investigation.

    These pin the URL, because the URL is where the partition lives. Asserting on
    the body would have passed for the broken version.
    """

    def _target(self, monkeypatch, **kw):
        seen = {}

        class _Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["body"] = req.data.decode()
            return _Resp()

        monkeypatch.setattr(m.urllib.request, "urlopen", fake_urlopen)
        m.push("camayoc", "x 1\n", url="http://gw.example/", **kw)
        return seen

    def test_adapter_is_a_url_segment_not_a_body_label(self, monkeypatch):
        seen = self._target(monkeypatch, grouping={"adapter": "git-provenance"})
        assert seen["url"].endswith("/metrics/job/camayoc/adapter/git-provenance")

    def test_two_adapters_address_two_different_groups(self, monkeypatch):
        a = self._target(monkeypatch, grouping={"adapter": "alpha"})["url"]
        b = self._target(monkeypatch, grouping={"adapter": "beta"})["url"]
        # THE regression. Equal URLs mean one group, and one group means the
        # second push silently deletes the first adapter's series.
        assert a != b, "both adapters push to ONE group — the second wipes the first"

    def test_a_grouping_value_cannot_escape_its_path_segment(self, monkeypatch):
        seen = self._target(monkeypatch, grouping={"adapter": "a/b?c#d"})
        assert "/metrics/job/camayoc/adapter/a%2Fb%3Fc%23d" in seen["url"]

    def test_no_grouping_is_the_bare_job_url(self, monkeypatch):
        seen = self._target(monkeypatch)
        assert seen["url"].endswith("/metrics/job/camayoc")

    def test_report_partitions_by_adapter(self, monkeypatch):
        urls = []
        monkeypatch.setenv(m.ENV, "http://gw.example/")

        class _Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        monkeypatch.setattr(m.urllib.request, "urlopen",
                            lambda req, timeout=None: (urls.append(req.full_url), _Resp())[1])
        m.report("alpha", {"camayoc_things_total": 1}, started=0.0)
        m.report("beta", {"camayoc_things_total": 2}, started=0.0)
        # every URL carries its adapter, and the two adapters never collide
        assert all("/adapter/" in u for u in urls), urls
        assert len({u for u in urls if "/job/camayoc/" in u}) == 2, urls
