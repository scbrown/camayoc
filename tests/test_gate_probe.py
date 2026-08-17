"""The gate proof has to be able to FAIL — camayoc-045.

Before this file the untagged-write and falsifier refusals were proven only by
`scripts/bootstrap.sh` probes, which is to say: proven only on a machine that
had already installed a quipu, by a script nobody ran in CI, using a grep that
could not tell a refusal from a network error.

A gate that has never been observed to say no is not a gate. So each test here
stands up a stub store that behaves in one specific way and asserts what the
probe concludes. Two of the arms are regressions for defects the old grep
actually had:

  * `test_a_gateway_error_page_is_not_a_refusal` — a proxy answering 502 with
    "connect() failed (111: Connection refused) while connecting to upstream"
    matched the old alternation on "refus". The store was never reached, and
    the old arm printed PROVEN and exited 0. Verified against the old code.

    camayoc-045 attributes this to curl's stderr being captured by `2>&1`.
    That is wrong: `curl -s` prints no error message (exit 7, zero bytes on
    stderr), so a bare dead server did not trigger it. The response body is
    the path that does. `test_a_server_that_is_down_is_not_a_proof` covers the
    dead server anyway, because the old arm still mis-reported it — as "the
    store ACCEPTED", with a remedy about validate_on_write that has nothing to
    do with a socket that would not open.

  * `test_an_echoed_probe_is_not_a_violation` — the falsifier arm's grep
    alternation included the word "falsifier", and the probe body it sends
    contains that word twice. A store that ACCEPTED the write and echoed the
    node back read as PROVEN. Verified against the old code.

Both now fail loudly, and for the right reason: the verdict is read out of
designated JSON fields and the HTTP status, never out of text the caller
partly wrote.

The stub is deliberately not a quipu. Testing against a real store would prove
the shapes; these tests prove the PROBE, which is the thing that was never
tested and the thing that was wrong. `tests/test_metrics_slice.py` covers the
real-server path when a `quipu-server` binary is available.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_PROBE = ROOT / "scripts" / "gate_probe.sh"

#: Exit codes gate_probe.sh promises. Named here because the whole point of
#: camayoc-045 is that these three outcomes are different things.
REFUSED, ACCEPTED, NO_VERDICT = 0, 2, 3


class StubStore(BaseHTTPRequestHandler):
    """Answers /episode however the test class asked for. Set by subclassing."""

    status = 200
    payload: object = {"conforms": True, "id": "urn:accepted"}
    echo = False

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        request = self.rfile.read(length)

        payload = self.payload
        if self.echo:
            # The failure mode defect (b) describes: a store that took the
            # write and hands the node straight back, words and all.
            payload = dict(payload)  # type: ignore[arg-type]
            payload["node"] = json.loads(request)["nodes"][0]

        body = json.dumps(payload).encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def run_probes(server_url: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(GATE_PROBE)],
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "QUIPU_SERVER": server_url},
        capture_output=True,
        text=True,
        timeout=120,
    )


class ProbeBehaviourTests(unittest.TestCase):
    """One stub store per test; the assertion is what the probe concluded."""

    def probe_against(self, **behaviour) -> subprocess.CompletedProcess:
        handler = type("Handler", (StubStore,), behaviour)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            return run_probes(f"http://127.0.0.1:{server.server_port}")
        finally:
            server.shutdown()
            server.server_close()

    # ------------------------------------------------------------- the gate works
    def test_a_shacl_violation_report_proves_the_gate(self):
        result = self.probe_against(
            payload={
                "conforms": False,
                "violations": [
                    {"message": "sourceKind is required"},
                    {"message": "falsifier is required"},
                    {"message": "repositorySource is required"},
                    {"message": "blockerEvidence is required"},
                ],
            }
        )
        self.assertEqual(REFUSED, result.returncode, result.stdout + result.stderr)
        self.assertEqual(4, result.stdout.count("PROVEN"))
        self.assertNotIn("NOT PROVEN", result.stdout)

    def test_a_4xx_decline_proves_the_gate_without_a_violation_body(self):
        """Not every store returns a SHACL report. A refusal is still a refusal."""
        result = self.probe_against(status=422, payload={"error": "validation failed"})
        self.assertEqual(REFUSED, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("NOT PROVEN", result.stdout)

    # --------------------------------------------------------- the gate is off
    def test_an_accepted_write_is_reported_as_the_gate_being_off(self):
        result = self.probe_against(payload={"conforms": True, "id": "urn:took-it"})
        self.assertEqual(ACCEPTED, result.returncode, result.stdout + result.stderr)
        self.assertIn("NOT PROVEN", result.stdout)
        self.assertIn("ACCEPTED", result.stdout)

    def test_a_bare_success_with_no_verdict_field_is_still_acceptance(self):
        """HTTP 200 and nothing that says no means the write landed."""
        result = self.probe_against(payload={"nodes": ["camayoc-gate-probe"]})
        self.assertEqual(ACCEPTED, result.returncode, result.stdout + result.stderr)
        self.assertIn("NOT PROVEN", result.stdout)

    # ------------------------------------------ regression: defect (b), echoing
    def test_an_echoed_probe_is_not_a_violation(self):
        """The store ACCEPTS and echoes the node back, name and description.

        Every word the old alternation searched for — falsifier, sourceKind,
        repositorySource, blockerEvidence — is in what comes back, because the
        probe put it there. The verdict must come from the verdict fields.
        """
        result = self.probe_against(payload={"conforms": True, "id": "urn:took-it"}, echo=True)
        self.assertEqual(ACCEPTED, result.returncode, result.stdout + result.stderr)
        self.assertIn("NOT PROVEN", result.stdout)

        # The probes must really carry the words they are named for, or the
        # echo above sends nothing incriminating back and this proves nothing.
        probes = GATE_PROBE.read_text()
        for term in ("falsifier", "sourceKind", "repositorySource", "blockerEvidence"):
            self.assertIn(term, probes)

    # --------------------------------------- regression: defect (a), no server
    def test_a_server_that_is_down_is_not_a_proof(self):
        """A socket that will not open is not evidence about the shapes.

        The old arm called this "the store ACCEPTED an untagged Decision" and
        told the operator to enable validate_on_write. Both false, and the
        remedy sends them to the wrong file.
        """
        result = run_probes("http://127.0.0.1:1")
        self.assertEqual(NO_VERDICT, result.returncode, result.stdout + result.stderr)
        self.assertIn("NOT PROVEN", result.stdout)
        self.assertIn("could not look", result.stdout)
        self.assertNotIn("PROVEN —", result.stdout.replace("NOT PROVEN", ""))

    def test_a_server_fault_is_not_a_verdict(self):
        """A 500 means the write did not land. It does not mean the gate held."""
        result = self.probe_against(status=500, payload={"error": "internal"})
        self.assertEqual(NO_VERDICT, result.returncode, result.stdout + result.stderr)
        self.assertIn("could not look", result.stdout)

    def test_a_gateway_error_page_is_not_a_refusal(self):
        """The reachable form of defect (a): a proxy answers, the store does not.

        This is the exact page nginx serves when the upstream socket is closed.
        It contains "Connection refused", it arrives on stdout where `-s` does
        not suppress it, and the old alternation matched it — PROVEN, exit 0,
        having never reached the store at all.
        """

        class HtmlHandler(StubStore):
            def do_POST(self):
                body = (
                    b"<html><head><title>502 Bad Gateway</title></head><body>\n"
                    b"connect() failed (111: Connection refused) while connecting to upstream\n"
                    b"</body></html>"
                )
                self.send_response(502)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), HtmlHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            result = run_probes(f"http://127.0.0.1:{server.server_port}")
        finally:
            server.shutdown()
            server.server_close()
        # The page literally contains "refused"; the old grep took it (verified).
        self.assertEqual(NO_VERDICT, result.returncode, result.stdout + result.stderr)
        self.assertIn("could not look", result.stdout)


class ArmIndependenceTests(unittest.TestCase):
    """Each arm must be able to fail on its own.

    The arms are ordered and the script exits on the first failure, which is
    correct behaviour and also means a later arm can be dead code nobody
    notices. This drives each arm individually by trimming the ones before it.
    """

    ARMS = ("untagged Decision", "no falsifier", "no repository source", "no evidence kind")

    def test_every_arm_reports_acceptance_when_it_is_the_first_to_run(self):
        source = GATE_PROBE.read_text()
        for index, label in enumerate(self.ARMS):
            with self.subTest(arm=label):
                # Make the earlier arms pass by turning their gate_arm calls into
                # no-ops, so the arm under test is the one that reaches the stub.
                script = source.replace(
                    "run_gate_probes() {",
                    "run_gate_probes() {\n  _skipped=0",
                    1,
                )
                for _ in range(index):
                    script = script.replace("  gate_arm ", "  : skipped ", 1)

                path = Path(self.temp) / f"arm{index}.sh"
                path.write_text(script)

                server = ThreadingHTTPServer(("127.0.0.1", 0), StubStore)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    result = subprocess.run(
                        ["bash", str(path)],
                        env={
                            "PATH": "/usr/bin:/bin:/usr/local/bin",
                            "QUIPU_SERVER": f"http://127.0.0.1:{server.server_port}",
                        },
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                finally:
                    server.shutdown()
                    server.server_close()

                self.assertEqual(ACCEPTED, result.returncode, result.stdout + result.stderr)
                self.assertIn(label, result.stdout)

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.temp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)


if __name__ == "__main__":
    sys.exit(unittest.main())
