from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "prometheus-rules.yml"
QUIPU_SERVER_BIN = os.environ.get("QUIPU_SERVER_BIN") or shutil.which("quipu-server")


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ingest = load_script("ingest_metrics")
retrieve = load_script("retrieve_metric")


class PrometheusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = {"status": "success", "data": {"result": [{"value": [0, "2.5"]}]}}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class MetricsUnitTests(unittest.TestCase):
    def test_parser_is_deterministic_and_carries_executable_method(self):
        rules = ingest.parse_rules(FIXTURE, strict=True)
        self.assertEqual(1, len(rules))
        self.assertEqual("ExampleLatencyHigh", rules[0].metric_name)
        self.assertEqual("> 0", rules[0].threshold)
        self.assertEqual("vector(1) > 0", rules[0].expression)
        turtle = ingest.render_turtle(rules, "http://127.0.0.1:9999")
        self.assertIn('quipu:derivationSystem "prometheus"', turtle)
        self.assertIn('aegis:contentHash "', turtle)
        self.assertNotIn("observedValue", turtle)
        self.assertEqual(turtle, ingest.render_turtle(rules, "http://127.0.0.1:9999"))

    def test_q7_executes_and_q8_distinguishes_unreachable(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), PrometheusHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = f"http://127.0.0.1:{server.server_port}"
        method = {"system": "prometheus", "query": "example_metric", "params": {"endpoint": endpoint}}
        try:
            result = retrieve.execute(method)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual("retrieved", result["status"])
        self.assertEqual("2.5", result["result"][0]["value"][1])

        unreachable = retrieve.execute(
            {"system": "prometheus", "query": "example_metric", "params": {"endpoint": "http://127.0.0.1:1"}},
            timeout=0.1,
        )
        self.assertEqual("unreachable", unreachable["status"])
        self.assertNotIn("healthy", json.dumps(unreachable).lower())


@unittest.skipUnless(QUIPU_SERVER_BIN, "quipu-server is required for named-query integration")
class NamedQueryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        cls.port = sock.getsockname()[1]
        sock.close()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.proc = subprocess.Popen(
            [QUIPU_SERVER_BIN, "--db", str(Path(cls.temp.name) / "store.db"), "--bind", f"127.0.0.1:{cls.port}"],
            cwd=cls.temp.name,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(50):
            try:
                cls.request("/health")
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("ephemeral quipu-server did not start")

        ontology = (ROOT / "ontology" / "core.ttl").read_text()
        shapes = (ROOT / "shapes" / "core.shapes.ttl").read_text()
        cls.request("/knot", {"turtle": ontology, "actor": "test"})
        cls.request("/shapes", {"action": "load", "name": "camayoc-core-test", "turtle": shapes})
        turtle = ingest.render_turtle(ingest.parse_rules(FIXTURE, strict=True), "http://127.0.0.1:9999")
        cls.request(
            "/knot",
            {"turtle": turtle, "actor": "test", "replace_snapshot": True, "snapshot": "metrics-test"},
        )
        for query in sorted((ROOT / "queries").glob("*.json")):
            cls.request("/queries", json.loads(query.read_text()))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        cls.temp.cleanup()

    @classmethod
    def request(cls, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            cls.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"{path} returned HTTP {exc.code}: {detail}") from exc

    def test_q1_q4_and_q7_run_against_seeded_fixture(self):
        q1 = self.request(
            "/ask",
            {"name": "camayoc_metrics_for_subject", "params": {"subject": "http://aegis.gastown.local/ontology/service-example"}},
        )
        self.assertEqual(1, q1["count"])

        q4 = self.request("/ask", {"name": "camayoc_unvalidated_metric_claims", "params": {}})
        self.assertGreater(q4["count"], 0)

        q7 = self.request(
            "/ask",
            {
                "name": "camayoc_metric_retrieval_method",
                "params": {
                    "metric": "http://aegis.gastown.local/ontology/metric-examplelatencyhigh-bcf55738"
                },
            },
        )
        self.assertEqual(1, q7["count"])
        self.assertEqual("prometheus", q7["rows"][0]["system"])

        q8 = self.request("/ask", {"name": "camayoc_metric_reachability_candidates", "params": {}})
        self.assertEqual(1, q8["count"])


if __name__ == "__main__":
    unittest.main()
