"""Real local HTTP controls; credentials and HOME are temporary fixtures."""
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import planes


class AuthTransport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.token = self.home / ".config" / "quipu" / "token"
        self.token.parent.mkdir(parents=True)
        self.expected = "fixture-one"
        self.calls = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                owner.calls.append(self.headers.get("Authorization"))
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                good = owner.calls[-1] == "Bearer " + owner.expected
                self.send_response(200 if good else 401)
                self.end_headers()
                self.wfile.write(json.dumps({} if good else {
                    "reason": "missing_or_invalid_bearer_token"}).encode())

            def log_message(self, *_args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"HOME": str(self.home)}, clear=True).start()
        patch.object(planes, "AUTH", None).start()
        patch.object(planes, "SERVER", f"http://127.0.0.1:{self.server.server_port}").start()

    def test_explicit_override_positive_control(self):
        with patch.object(planes, "AUTH", self.expected):
            self.assertEqual(planes._post("/knot", {}, client="camayoc-planes"), {})
        self.assertEqual(len(self.calls), 1)

    def test_canonical_file_without_exported_token(self):
        self.token.write_text(self.expected + "\n")
        self.assertEqual(planes._post("/knot", {}, client="camayoc-planes"), {})

    def test_environment_overrides_file_at_call_time(self):
        self.token.write_text("stale-fixture")
        os.environ["QUIPU_AUTH_TOKEN"] = self.expected
        self.assertEqual(planes._post("/knot", {}, client="camayoc-planes"), {})

    def test_file_change_is_seen_without_reimport(self):
        self.token.write_text(self.expected)
        planes._post("/knot", {}, client="camayoc-planes")
        self.expected = "fixture-two"
        self.token.write_text(self.expected)
        self.assertEqual(planes._post("/knot", {}, client="camayoc-planes"), {})
        self.assertEqual(len(self.calls), 2)

    def test_explicit_file_overrides_default(self):
        self.token.write_text("wrong-fixture")
        selected = self.home / "selected-token"
        selected.write_text(self.expected)
        os.environ["QUIPU_AUTH_TOKEN_FILE"] = str(selected)
        self.assertEqual(planes._post("/knot", {}, client="camayoc-planes"), {})

    def test_refusal_is_not_retried_and_explains_provisioning(self):
        with self.assertRaisesRegex(planes.PlaneError, "QUIPU_AUTH_TOKEN_FILE"):
            planes._post("/knot", {}, client="camayoc-planes")
        self.assertEqual(self.calls, [None])

    def test_invalid_credential_is_refused_without_sending_or_echoing_it(self):
        secret = "private-fixture\ninjected-header"
        os.environ["QUIPU_AUTH_TOKEN"] = secret
        with self.assertRaises(planes.PlaneError) as caught:
            planes._post("/knot", {}, client="camayoc-planes")
        self.assertNotIn("private-fixture", str(caught.exception))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
