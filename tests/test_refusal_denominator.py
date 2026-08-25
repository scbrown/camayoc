"""The refused-write denominator reporter — camayoc-0d3 item 1.

`docs/design/incident-corpus.md` §4.2 is a section about a number nobody had.
This is the reporter that produces it, and the tests below are mostly about
the three ways it must refuse to overstate that number:

  * a store it could not reach must never render as "no refusals"
  * a `shacl` refusal must never render as "refused for a missing falsifier"
  * a hand-narrowed subset must never render as something the stream classified

Plus the arithmetic, which is the easy part and the part that would be wrong
in the flattering direction if the abstentions were not tested first.

No live quipu is required and none is faked at the protocol level: the fetch
functions are exercised by substituting the module's one request primitive,
and the rest of the module is pure.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rd = load("refusal_denominator", "scripts/refusal_denominator.py")

EVENTS = [
    {"graph": "https://camayoc.local/plane/crew/records", "actor": "strider",
     "source": "camayoc ingress", "reason": "shacl", "refused_datums": 3,
     "at": "2026-08-24T09:00:00Z"},
    {"graph": "https://camayoc.local/plane/crew/records", "actor": "strider",
     "source": "camayoc ingress", "reason": "shacl", "refused_datums": 1,
     "at": "2026-08-24T11:30:00Z"},
    {"graph": "https://camayoc.local/plane/crew/inferred", "actor": "polecat-7",
     "source": "shantytown", "reason": "authority", "refused_datums": 2,
     "at": "2026-08-25T08:00:00Z"},
    {"graph": "https://camayoc.local/plane/crew/records", "actor": "strider",
     "source": "camayoc ingress", "reason": "placement", "refused_datums": 1,
     "at": "2026-08-25T09:15:00Z"},
]


class EnvelopeTests(unittest.TestCase):
    """How the event list arrives is unknown; reading nothing as zero is not."""

    def test_a_bare_list_is_accepted(self):
        self.assertEqual(4, len(rd.events_from_payload(EVENTS)))

    def test_a_wrapped_list_is_accepted(self):
        for key in ("events", "items", "results", "data"):
            with self.subTest(key=key):
                self.assertEqual(4, len(rd.events_from_payload({key: EVENTS})))

    def test_an_unrecognised_envelope_abstains_rather_than_reporting_zero(self):
        """THE LOAD-BEARING ONE. An empty list here would print '0 refusals'
        and be indistinguishable from a store where the gate never fired."""
        with self.assertRaises(rd.CouldNotLook) as caught:
            rd.events_from_payload({"payload": {"refusals": 4}})
        self.assertIn("Refusing to read that as zero", str(caught.exception))

    def test_a_non_collection_response_abstains(self):
        with self.assertRaises(rd.CouldNotLook):
            rd.events_from_payload("4 refusals")

    def test_non_dict_entries_are_dropped_not_counted(self):
        self.assertEqual(1, len(rd.events_from_payload([EVENTS[0], "junk", None])))


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.summary = rd.summarise(EVENTS)

    def test_it_counts_every_refusal(self):
        self.assertEqual(4, self.summary["refused"])

    def test_it_groups_by_the_reason_verbatim(self):
        self.assertEqual({"shacl": 2, "authority": 1, "placement": 1},
                         self.summary["by_reason"])

    def test_the_shape_gate_total_is_reported_as_its_own_quantity(self):
        """Two shacl refusals is an UPPER bound on 'refused for a missing
        falsifier' — the record names the gate, not the failing shape. The
        field is named shape_gate_refusals for that reason and there is no
        field claiming the narrower count."""
        self.assertEqual(2, self.summary["shape_gate_refusals"])
        self.assertNotIn("missing_falsifier", self.summary)

    def test_an_unknown_gate_class_is_surfaced_as_unrecognised(self):
        """A new gate class must appear as a new row rather than disappearing
        into an 'other' bucket that nobody reads."""
        summary = rd.summarise(EVENTS + [{"reason": "quota"}])
        self.assertEqual(["quota"], summary["unrecognised_reasons"])
        self.assertEqual(1, summary["by_reason"]["quota"])

    def test_a_missing_reason_is_labelled_rather_than_blank(self):
        summary = rd.summarise([{"graph": "g"}])
        self.assertIn("(no reason recorded)", summary["by_reason"])

    def test_it_reports_the_observed_window(self):
        self.assertEqual("2026-08-24T09:00:00Z", self.summary["first_seen"])
        self.assertEqual("2026-08-25T09:15:00Z", self.summary["last_seen"])

    def test_an_untimed_stream_reports_no_window_rather_than_inventing_one(self):
        """A range taken from ingest order would look exactly like evidence."""
        summary = rd.summarise([{"reason": "shacl"}, {"reason": "shacl"}])
        self.assertIsNone(summary["first_seen"])
        self.assertEqual(2, summary["events_without_a_timestamp"])

    def test_datum_counts_are_summed_and_absences_counted_separately(self):
        summary = rd.summarise(EVENTS + [{"reason": "shacl"}])
        self.assertEqual(7, summary["refused_datums"])
        self.assertEqual(1, summary["events_without_datum_count"])

    def test_the_operator_filter_narrows_and_records_that_it_did(self):
        summary = rd.summarise(EVENTS, reason_contains="shacl")
        self.assertEqual(2, summary["refused"])
        self.assertEqual(4, summary["refused_before_filter"])
        self.assertEqual("shacl", summary["reason_filter"])


class RateTests(unittest.TestCase):
    def test_the_share_is_refused_over_all_attempts(self):
        self.assertAlmostEqual(0.2, rd.rate(8, 2))

    def test_an_empty_store_has_no_rate_rather_than_a_rate_of_zero(self):
        """0% is a measurement. 'Nothing to divide' is not one, and the two
        must not print the same."""
        self.assertIsNone(rd.rate(0, 0))

    def test_zero_refusals_against_a_real_population_is_a_real_zero(self):
        self.assertEqual(0.0, rd.rate(12, 0))


class ReportTests(unittest.TestCase):
    def render(self, summary, accepted):
        return "\n".join(rd.render(summary, accepted))

    def test_the_three_floors_are_printed_every_run(self):
        """Not a footnote, not behind a flag. A reader who sees the number must
        see what it is a floor of."""
        text = self.render(rd.summarise(EVENTS), 96)
        self.assertIn("speculate", text)
        self.assertIn("BODIES are not stored", text)
        self.assertIn("different time origins", text)

    def test_the_report_never_calls_a_shacl_refusal_a_falsifier_refusal(self):
        text = self.render(rd.summarise(EVENTS), 96)
        self.assertIn("UPPER bound on 'refused for a missing falsifier'", text)

    def test_the_report_refuses_to_promise_a_per_form_breakdown(self):
        text = self.render(rd.summarise(EVENTS), 96)
        self.assertIn("A1-A7", text)
        self.assertIn("cannot be recovered", text)

    def test_an_operator_filter_is_attributed_to_the_operator(self):
        text = self.render(rd.summarise(EVENTS, reason_contains="shacl"), 96)
        self.assertIn("OPERATOR-supplied filter", text)
        self.assertIn("not one this stream records", text)

    def test_an_unread_population_prints_unknown_not_zero(self):
        text = self.render(rd.summarise(EVENTS), None)
        self.assertIn("UNKNOWN", text)
        self.assertNotIn("refused share               : 100", text)

    def test_an_empty_stream_says_zero_refusals_out_loud(self):
        text = self.render(rd.summarise([]), 40)
        self.assertIn("(no refusals recorded)", text)
        self.assertIn("0.00%", text)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FetchTests(unittest.TestCase):
    """The store-facing half, with the one request primitive substituted."""

    def substitute(self, handler):
        real = rd.urllib.request.urlopen
        rd.urllib.request.urlopen = handler
        self.addCleanup(lambda: setattr(rd.urllib.request, "urlopen", real))

    def serve(self, payload):
        self.substitute(lambda req, timeout=None: FakeResponse(json.dumps(payload).encode()))

    def raise_http(self, code):
        def handler(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, code, "no", {}, io.BytesIO(b""))
        self.substitute(handler)

    def test_refusals_are_fetched_and_parsed(self):
        self.serve({"events": EVENTS})
        self.assertEqual(4, len(rd.fetch_refusals()))

    def test_a_404_reads_as_a_store_that_predates_the_stream(self):
        """Exactly the distinction gate_probe.sh makes. A quipu without the
        event route knows nothing about refusals; it does not report none."""
        self.raise_http(404)
        with self.assertRaises(rd.CouldNotLook) as caught:
            rd.fetch_refusals()
        self.assertIn("predates", str(caught.exception))

    def test_an_unreachable_store_is_not_evidence(self):
        def handler(req, timeout=None):
            raise urllib.error.URLError("connection refused")
        self.substitute(handler)
        with self.assertRaises(rd.CouldNotLook) as caught:
            rd.fetch_refusals()
        self.assertIn("not evidence", str(caught.exception))

    def test_a_non_json_body_abstains(self):
        self.substitute(lambda req, timeout=None: FakeResponse(b"<html>502</html>"))
        with self.assertRaises(rd.CouldNotLook):
            rd.fetch_refusals()

    def test_the_accepted_population_comes_from_the_named_stored_query(self):
        seen = {}

        def handler(req, timeout=None):
            seen["body"] = json.loads(req.data)
            return FakeResponse(json.dumps({"count": 96, "rows": []}).encode())

        self.substitute(handler)
        self.assertEqual(96, rd.fetch_accepted())
        self.assertEqual(rd.ACCEPTED_QUERY, seen["body"]["name"])

    def test_a_countless_answer_is_not_a_population_of_zero(self):
        self.serve({"rows": []})
        with self.assertRaises(rd.CouldNotLook) as caught:
            rd.fetch_accepted()
        self.assertIn("not an accepted population of zero", str(caught.exception))

    def test_the_named_stored_query_exists_on_disk(self):
        """The reporter names a stored query; a name with no file behind it
        would fail only against a live store, which is the least convenient
        place to find out."""
        path = ROOT / "queries" / f"{rd.ACCEPTED_QUERY}.json"
        self.assertTrue(path.exists(), path)
        self.assertEqual(rd.ACCEPTED_QUERY, json.loads(path.read_text())["name"])


class CommandLineTests(unittest.TestCase):
    def invoke(self, *argv) -> tuple[int, str]:
        argv_before, sys.argv = sys.argv, ["refusal_denominator.py", *argv]
        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer):
                code = rd.main()
        finally:
            sys.argv = argv_before
        return code, buffer.getvalue()

    def events_file(self, payload) -> str:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "events.json"
        path.write_text(json.dumps(payload))
        return str(path)

    def test_it_reports_from_a_saved_stream(self):
        code, text = self.invoke("--events-file", self.events_file({"events": EVENTS}),
                                 "--accepted", "96")
        self.assertEqual(0, code)
        self.assertIn("refused writes in the stream : 4", text)
        self.assertIn("accepted Verifications      : 96", text)

    def test_json_output_carries_the_floors_as_data(self):
        code, text = self.invoke("--events-file", self.events_file(EVENTS),
                                 "--accepted", "96", "--json")
        self.assertEqual(0, code)
        payload = json.loads(text)
        self.assertEqual(4, payload["refused"])
        self.assertEqual(3, len(payload["floors"]))
        self.assertAlmostEqual(4 / 100, payload["refused_share"])

    def test_a_missing_file_exits_could_not_look(self):
        code, _ = self.invoke("--events-file", "/nonexistent/events.json")
        self.assertEqual(3, code)

    def test_an_unreadable_envelope_exits_could_not_look_not_zero(self):
        code, text = self.invoke("--events-file", self.events_file({"total": 0}))
        self.assertEqual(3, code)
        self.assertEqual("", text)

    def test_without_an_accepted_count_the_share_is_undefined_not_invented(self):
        code, text = self.invoke("--events-file", self.events_file(EVENTS))
        self.assertEqual(0, code)
        self.assertIn("UNKNOWN (not read)", text)


class NoVocabularyWasMintedTests(unittest.TestCase):
    """Item 2 stays deferred, and this is what holds it there.

    The A1-A7 refused-verification taxonomy is buildable and must not be built:
    no competency question asks for per-form refusal counts, and
    competency-before-classes does not lapse because a dependency cleared. A
    future session reaching for the terms will trip this first.
    """

    def test_the_ontology_carries_no_refusal_form_vocabulary(self):
        ontology = (ROOT / "ontology" / "core.ttl").read_text()
        for term in ("RefusalForm", "refusalForm", "refusedForm", "A1", "A7"):
            self.assertNotIn(f"aegis:{term} a ", ontology)
            self.assertNotIn(f"camayoc:{term} a ", ontology)

    def test_the_reporter_writes_no_turtle(self):
        """A reporter that emitted facts would need vocabulary for them, and
        the rate it computes decays — a judgment at read time, not a fact true
        at write time."""
        source = (ROOT / "scripts" / "refusal_denominator.py").read_text()
        self.assertNotIn("@prefix", source.replace("no @prefix", ""))
        self.assertNotIn("/knot", source)
        self.assertNotIn("/episode", source)


if __name__ == "__main__":
    unittest.main()
