"""Quarantined entity-mention extraction — camayoc-0c8.

The producer's promises, pinned: deterministic (byte-identical re-runs),
abstaining (ambiguous labels match nobody, code fences are prose for nobody),
quarantined (the write targets ONLY the inferred plane, and only after that
plane is confirmed registered AND labelled), and loudly refusing when it
could not look — an unreachable store must never read as clean prose.

No network: quipu is the same in-process stub `test_planes.py` uses.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
extract = load("extract_entities")

INFERRED_PLANE = planes.plane_for("inferred")
QUIPU_IRI = "http://aegis.gastown.local/ontology/tool/quipu"
BOBBIN_IRI = "http://aegis.gastown.local/ontology/tool/bobbin"

#: Two clean labels, one ambiguous ("Indexer" names two entities), one too
#: short ("qp"). The stub serves this for every gazetteer query.
GAZETTEER_ROWS = [
    {"entity": QUIPU_IRI, "label": "Quipu"},
    {"entity": BOBBIN_IRI, "label": "Bobbin"},
    {"entity": QUIPU_IRI, "label": "qp"},
    {"entity": QUIPU_IRI, "label": "Indexer"},
    {"entity": BOBBIN_IRI, "label": "Indexer"},
    # A lang-tagged literal arrives as an object; the tag is not label text.
    {"entity": BOBBIN_IRI, "label": {"value": "Spuler", "lang": "de"}},
]

FIXTURE_MD = """\
# Overview

Quipu is the governed store. Bobbin reads from it.

```bash
echo Quipu   # code, not prose — must not match
```

## Details

The Indexer feeds Quipu nightly. Nothing mentions unquipu or Quipus here.
"""


class StubQuipu(BaseHTTPRequestHandler):
    """A quipu with /query, /graphs and /knot. Class attrs steer behaviour."""

    seen: list = []
    gazetteer_rows: list = GAZETTEER_ROWS
    graphs: list | None = None  # None = the inferred plane, labelled
    graphs_status = 200

    def _reply(self, payload, status=200):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if status == 200:
            self.wfile.write(raw)

    def do_GET(self):
        type(self).seen.append((self.path, None))
        if self.path.startswith("/graphs"):
            if self.graphs_status != 200:
                self._reply({}, self.graphs_status)
                return
            graphs = self.graphs
            if graphs is None:
                graphs = [{"iri": INFERRED_PLANE, "labels": {"trust_rank": 0}}]
            self._reply({"count": len(graphs), "graphs": graphs})
            return
        self._reply({}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).seen.append((self.path, body))
        if self.path == "/query":
            self._reply({"variables": ["entity", "label"],
                         "rows": self.gazetteer_rows,
                         "count": len(self.gazetteer_rows)})
        elif self.path == "/knot":
            self._reply({"tx_id": 9, "count": 5, "conforms": True})
        else:
            self._reply({}, 404)

    def log_message(self, *_a):
        return


class StubbedCase(unittest.TestCase):
    def serve(self, **behaviour):
        handler = type("H", (StubQuipu,), {"seen": [], **behaviour})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        planes.SERVER = f"http://127.0.0.1:{server.server_port}"
        return handler

    def fixture(self, text=FIXTURE_MD, name="prose.md") -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / name
        path.write_text(text)
        return path


class GazetteerTests(StubbedCase):
    def test_labels_map_to_their_single_entity(self):
        handler = self.serve()
        gazetteer, _stats = extract.fetch_gazetteer()
        self.assertEqual(QUIPU_IRI, gazetteer["Quipu"])
        self.assertEqual(BOBBIN_IRI, gazetteer["Bobbin"])
        query = next(body for path, body in handler.seen if path == "/query")
        self.assertIs(query["verbose"], True)

    def test_an_ambiguous_label_matches_for_nobody(self):
        """'Indexer' names two entities. Picking one would attach prose to
        the wrong referent — worse than a missing mention, even quarantined."""
        self.serve()
        gazetteer, stats = extract.fetch_gazetteer()
        self.assertNotIn("Indexer", gazetteer)
        self.assertEqual(["Indexer"], stats["labels_ambiguous"])

    def test_a_too_short_label_is_skipped_and_counted(self):
        self.serve()
        gazetteer, stats = extract.fetch_gazetteer()
        self.assertNotIn("qp", gazetteer)
        self.assertEqual(1, stats["labels_skipped_short"])

    def test_a_lang_tagged_label_uses_its_lexical_value(self):
        self.serve()
        gazetteer, _stats = extract.fetch_gazetteer()
        self.assertEqual(BOBBIN_IRI, gazetteer["Spuler"])

    def test_a_rowless_answer_is_a_refusal_not_an_empty_gazetteer(self):
        """'Could not read the gazetteer' must never scan as 'the graph has
        no labels' — the same distinction the gate probe had to learn."""
        self.serve()
        original = extract._call
        extract._call = lambda *a, **k: {"unexpected": True}
        self.addCleanup(setattr, extract, "_call", original)
        with self.assertRaises(extract.ExtractError):
            extract.fetch_gazetteer()


class ScanTests(StubbedCase):
    GAZ = {"Quipu": QUIPU_IRI, "Bobbin": BOBBIN_IRI}

    def test_positive_arm_finds_the_expected_mentions(self):
        path = self.fixture()
        mentions = extract.scan_file(path, self.GAZ, [])
        texts = [(m["text"], m["section"]) for m in mentions]
        self.assertEqual(
            [("Quipu", "Overview"), ("Bobbin", "Overview"), ("Quipu", "Details")],
            texts,
        )
        for m in mentions:
            self.assertEqual(path.as_posix(), m["file"])
        self.assertEqual(QUIPU_IRI, mentions[0]["entity"])

    def test_code_fences_are_not_prose(self):
        path = self.fixture()
        mentions = extract.scan_file(path, self.GAZ, [])
        self.assertNotIn(5, [m["line"] for m in mentions],
                         "the fenced 'echo Quipu' line must not match")

    def test_matching_is_whole_word(self):
        """'unquipu' and 'Quipus' contain the label and mention nothing;
        'quipu-ish' DOES carry the whole word 'quipu' — hyphens are word
        boundaries here exactly as they are for the work-item pattern."""
        path = self.fixture("unquipu Quipus\n")
        self.assertEqual([], extract.scan_file(path, {"quipu": QUIPU_IRI}, []))
        hyphened = self.fixture("quipu-ish\n", name="hyphen.md")
        self.assertEqual(
            ["quipu"],
            [m["text"] for m in extract.scan_file(hyphened, {"quipu": QUIPU_IRI}, [])],
        )

    def test_explicit_patterns_match_and_carry_their_entity(self):
        path = self.fixture("See quipu-ab12 for details.\n")
        patterns = [(extract.re.compile(r"quipu-[0-9a-z]{2,6}"), QUIPU_IRI)]
        mentions = extract.scan_file(path, {}, patterns)
        self.assertEqual([("quipu-ab12", QUIPU_IRI)],
                         [(m["text"], m["entity"]) for m in mentions])

    def test_control_negative_no_mentions_means_zero_facts(self):
        path = self.fixture("Nothing in this prose names anything known.\n")
        mentions = extract.scan_file(path, self.GAZ, [])
        self.assertEqual([], mentions)
        self.assertEqual("", extract.mention_triples(mentions))


class TripleTests(StubbedCase):
    def test_triples_carry_what_where_and_which_entity(self):
        path = self.fixture()
        turtle = extract.mention_triples(extract.scan_file(path, ScanTests.GAZ, []))
        self.assertIn(f"<{extract.ONTOLOGY}about> <{QUIPU_IRI}>", turtle)
        self.assertIn(f'<{extract.ONTOLOGY}identifier> "Quipu"', turtle)
        self.assertIn(f'<{extract.ONTOLOGY}filePath> "{path.as_posix()}"', turtle)
        self.assertIn("(§ Details)", turtle)

    def test_every_mention_is_tagged_inferred_and_only_inferred(self):
        path = self.fixture()
        turtle = extract.mention_triples(extract.scan_file(path, ScanTests.GAZ, []))
        self.assertIn('sourceKind> "inferred"', turtle)
        self.assertNotIn('"observed"', turtle)
        self.assertNotIn('"declared"', turtle)

    def test_rerun_output_is_byte_identical(self):
        path = self.fixture()
        first = extract.mention_triples(extract.scan_file(path, ScanTests.GAZ, []))
        second = extract.mention_triples(extract.scan_file(path, ScanTests.GAZ, []))
        self.assertEqual(first, second)
        self.assertTrue(first)


class PatternConfigTests(StubbedCase):
    def write_config(self, payload) -> Path:
        path = Path(tempfile.mkdtemp()) / "patterns.json"
        path.write_text(json.dumps(payload))
        return path

    def test_a_valid_config_compiles(self):
        path = self.write_config(
            {"patterns": [{"pattern": r"quipu-\d+", "entity": QUIPU_IRI}]}
        )
        [(regex, entity)] = extract.load_patterns(path)
        self.assertEqual(QUIPU_IRI, entity)
        self.assertTrue(regex.search("quipu-42"))

    def test_a_broken_regex_is_refused_not_dropped(self):
        path = self.write_config({"patterns": [{"pattern": "(", "entity": QUIPU_IRI}]})
        with self.assertRaises(extract.ExtractError):
            extract.load_patterns(path)

    def test_an_entry_without_an_entity_is_refused(self):
        path = self.write_config({"patterns": [{"pattern": "x"}]})
        with self.assertRaises(extract.ExtractError):
            extract.load_patterns(path)


class WritePathTests(StubbedCase):
    def test_the_write_targets_the_inferred_plane_and_nothing_else(self):
        handler = self.serve()
        path = self.fixture()
        rc = extract.main([str(path)])
        self.assertEqual(0, rc)
        knots = [b for p, b in handler.seen if p == "/knot"]
        self.assertEqual(1, len(knots))
        self.assertEqual(INFERRED_PLANE, knots[0]["graph"])
        self.assertIn("sourceKind", knots[0]["turtle"])
        self.assertTrue(knots[0]["actor"])
        self.assertTrue(knots[0]["source"])

    def test_control_negative_the_writer_is_never_called(self):
        """Zero mentions is zero facts — not an empty transaction."""
        handler = self.serve()
        path = self.fixture("Clean prose, mentioning nothing the graph knows.\n")
        rc = extract.main([str(path)])
        self.assertEqual(0, rc)
        self.assertEqual([], [p for p, _ in handler.seen if p == "/knot"])

    def test_dry_run_prints_triples_and_writes_nothing(self):
        handler = self.serve()
        path = self.fixture()
        import contextlib
        import io
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = extract.main([str(path), "--dry-run"])
        self.assertEqual(0, rc)
        self.assertIn(f"<{QUIPU_IRI}>", stdout.getvalue())
        self.assertEqual([], [p for p, _ in handler.seen if p == "/knot"])

    def test_an_unprovisioned_plane_refuses_before_any_write(self):
        handler = self.serve(graphs=[])
        path = self.fixture()
        rc = extract.main([str(path)])
        self.assertEqual(2, rc)
        self.assertEqual([], [p for p, _ in handler.seen if p == "/knot"])

    def test_a_registered_but_unlabelled_plane_is_refused(self):
        """Quarantine's appearance without its substance — planes.py's own
        wording, held to here."""
        handler = self.serve(
            graphs=[{"iri": INFERRED_PLANE, "labels": {"trust_rank": None}}]
        )
        path = self.fixture()
        rc = extract.main([str(path)])
        self.assertEqual(2, rc)
        self.assertEqual([], [p for p, _ in handler.seen if p == "/knot"])

    def test_an_unreachable_store_refuses_loudly(self):
        """Could not look is not zero mentions — and exit 0 here would print
        exactly like clean prose."""
        planes.SERVER = "http://127.0.0.1:1"
        path = self.fixture()
        rc = extract.main([str(path)])
        self.assertEqual(2, rc)

    def test_a_store_predating_the_graphs_surface_refuses(self):
        handler = self.serve(graphs_status=404)
        path = self.fixture()
        rc = extract.main([str(path)])
        self.assertEqual(2, rc)
        self.assertEqual([], [p for p, _ in handler.seen if p == "/knot"])


if __name__ == "__main__":
    sys.exit(unittest.main())
