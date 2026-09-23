"""bootstrap.sh must succeed when run a second time against the same store.

caboodle's resumed install re-runs bootstrap as camayoc's functional
verification. On the first run quipu has no shapes loaded, so its vocabulary
gate is inactive and the ontology load succeeds; bootstrap then loads shapes,
and every later load of core.ttl is refused with HTTP 400 ("unknown rdf:type
IRIs: rdf:Property, rdfs:Class"). Before this test that refusal failed every
resumed install, printing an empty "ontology load FAILED:".

The second arm is what stops the first from passing vacuously: against a store
that does NOT hold the ontology, the presence check must say so.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quipu_bin_guard import QUIPU_SERVER as QUIPU_SERVER_BIN, requires_quipu_server  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.sh"
PRESENT = ROOT / "scripts" / "ontology_present.py"
ONTOLOGY = ROOT / "ontology" / "core.ttl"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@requires_quipu_server
class BootstrapRerunTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.server = f"http://127.0.0.1:{free_port()}"
        bindir = str(Path(QUIPU_SERVER_BIN).resolve().parent)
        self.env = dict(
            os.environ,
            PATH=bindir + os.pathsep + os.environ.get("PATH", ""),
            QUIPU_SERVER=self.server,
            CLAUDE_PROJECT_DIR=str(self.project),
            CLAUDE_PLUGIN_ROOT=str(ROOT),
        )
        self.env.pop("QUIPU_AUTH_TOKEN", None)

    def tearDown(self):
        pid = self.project / ".quipu" / "server.pid"
        if pid.exists():
            try:
                os.kill(int(pid.read_text().strip()), 15)
            except (ProcessLookupError, ValueError):
                pass
        self.temp.cleanup()

    def bootstrap(self):
        return subprocess.run(
            ["bash", str(BOOTSTRAP)], cwd=self.project, env=self.env,
            capture_output=True, text=True, timeout=300,
        )

    def test_a_second_run_against_the_same_store_succeeds(self):
        first = self.bootstrap()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("ontology: loaded (core.ttl)", first.stdout)

        second = self.bootstrap()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("server: already running", second.stdout)
        self.assertIn("ontology: already present", second.stdout)
        self.assertNotIn("FAILED", second.stdout)


@requires_quipu_server
class OntologyPresenceDiscriminatesTest(unittest.TestCase):
    """Without this arm a checker that always exits 0 would pass the test above."""

    def test_a_store_without_the_ontology_reports_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            port = free_port()
            proc = subprocess.Popen(
                [QUIPU_SERVER_BIN, "--db", str(Path(tmp) / "s.db"), "--bind", f"127.0.0.1:{port}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                url = f"http://127.0.0.1:{port}"
                for _ in range(60):
                    try:
                        urllib.request.urlopen(url + "/health", timeout=1)
                        break
                    except OSError:
                        time.sleep(0.25)
                out = subprocess.run(
                    [sys.executable, str(PRESENT), str(ONTOLOGY), url],
                    capture_output=True, text=True, timeout=60,
                )
                self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
                self.assertRegex(out.stdout, r"^0/\d+")
            finally:
                proc.terminate()
                proc.wait(timeout=10)

    def test_a_dead_server_is_cannot_tell_not_missing(self):
        out = subprocess.run(
            [sys.executable, str(PRESENT), str(ONTOLOGY), f"http://127.0.0.1:{free_port()}"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
