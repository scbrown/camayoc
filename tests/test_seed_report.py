"""The seed must report convergence as success — camayoc-16y.

`skills/camayoc/SKILL.md` teaches agents to branch on `outcome` and never on
`count`, because a store that already holds a fact returns `unchanged` and that
is the success case. camayoc-16y observed that camayoc's own seed path did not
follow the discipline it teaches: it read `count` and `conforms` out of the
response with `sed` and led its status line with the count, so a second, fully
converged run announced "seed: ingested 0 facts".

Nobody had ever run the seed twice against a stub and looked at what it said,
which is why it went unnoticed. These tests do exactly that.

## Which branch is the real one

The rule is written for `POST /episode`; the seed writes to `POST /knot`. Read
against quipu's source rather than guessed at: `/episode` returns `outcome`,
one of `created` | `updated` | `unchanged` (`src/episode/mod.rs:96-102`), and
`/knot` does not — its success body is `{conforms, tx_id, count, snapshot,
replaced}` (`src/mcp/mod.rs:512-518`).

So `test_a_response_without_an_outcome_says_so_rather_than_guessing` is the
*production* path today, not a hypothetical: the seed genuinely cannot tell
convergence from a re-add, and saying so is the honest report. The
outcome-carrying tests keep the branch honest for the day `/knot` grows one, or
for the day the seed moves to `/episode` (camayoc-s0h).

The failure body is also quipu's real one — `violations` is an integer COUNT
and `issues` is the list, arriving with HTTP 200 (`src/mcp/mod.rs:471-477`).
The first draft of this suite invented a shape where `violations` was the list,
and the parser written against it raised a TypeError on the real thing.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "scripts" / "seed_knowledge.sh"

OK, REFUSED = 0, 2


def make_handler(knot_response: object, knot_status: int = 200):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # /health
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path.rstrip("/").endswith("knot"):
                status, payload = knot_status, knot_response
            else:  # /shapes
                status, payload = 200, {"ok": True}
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    return Handler


class SeedReportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # A minimal tree for the walker: one module, one document.
        self.src = Path(self._tmp.name) / "src"
        self.src.mkdir()
        (self.src / "widget.py").write_text('"""A widget."""\n\n\ndef spin():\n    return 1\n')
        (self.src / "README.md").write_text("# Widget\n\nIt spins.\n")

    def seed(self, knot_response, knot_status=200) -> subprocess.CompletedProcess:
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(knot_response, knot_status))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            return subprocess.run(
                ["bash", str(SEED), str(self.src)],
                env={
                    "PATH": "/usr/bin:/bin:/usr/local/bin",
                    "QUIPU_SERVER": f"http://127.0.0.1:{server.server_port}",
                    "CLAUDE_PLUGIN_ROOT": str(ROOT),
                    "CLAUDE_PROJECT_DIR": self._tmp.name,
                },
                capture_output=True,
                text=True,
                timeout=180,
            )
        finally:
            server.shutdown()
            server.server_close()

    # ------------------------------------------------ the rule camayoc-16y cites
    def test_unchanged_is_reported_as_success(self):
        result = self.seed({"outcome": "unchanged", "count": 0, "conforms": True})
        self.assertEqual(OK, result.returncode, result.stdout + result.stderr)
        self.assertIn("unchanged", result.stdout)
        self.assertIn("SUCCESS", result.stdout)

    def test_a_zero_count_never_leads_the_report(self):
        """The exact regression: a converged re-run must not read as a failure.

        The old line was `seed: ingested 0 facts (conforms: true)`. The count
        may still appear — it is useful — but never as the verdict.
        """
        result = self.seed({"outcome": "unchanged", "count": 0, "conforms": True})
        self.assertEqual(OK, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("ingested 0 facts", result.stdout)
        self.assertIn("detail, not the verdict", result.stdout)

    def test_a_created_outcome_is_reported_as_itself(self):
        result = self.seed({"outcome": "created", "count": 41, "conforms": True})
        self.assertEqual(OK, result.returncode, result.stdout + result.stderr)
        self.assertIn("outcome created", result.stdout)
        self.assertIn("count 41", result.stdout)

    def test_a_response_without_an_outcome_says_so_rather_than_guessing(self):
        result = self.seed({"count": 41, "conforms": True})
        self.assertEqual(OK, result.returncode, result.stdout + result.stderr)
        self.assertIn("no `outcome`", result.stdout)
        self.assertIn("cannot be confirmed", result.stdout)

    # --------------------------------------- a refusal must not slide past a 200
    def test_conforms_false_at_http_200_is_a_refusal_not_a_status_line(self):
        """The old code printed `(conforms: false)` and then said "done"."""
        result = self.seed(
            {
                "conforms": False,
                "violations": 1,
                "warnings": 0,
                "issues": [{"message": "CodeModule lacks aegis:sourceKind"}],
                "hint": "every fact carries camayoc:sourceKind",
            }
        )
        self.assertEqual(REFUSED, result.returncode, result.stdout + result.stderr)
        self.assertIn("REFUSED", result.stdout)
        self.assertIn("CodeModule lacks aegis:sourceKind", result.stdout)
        self.assertNotIn("seed: done", result.stdout)


    def test_a_violation_count_with_no_issue_list_still_refuses(self):
        """`violations` is an integer COUNT in quipu, not a list.

        The first version of this parser sliced it as a list, which is a
        TypeError — the operator would have got a traceback instead of the
        reason their seed was rejected. With no `issues` to print, the hint
        stands in rather than a bare number.
        """
        result = self.seed({"conforms": False, "violations": 3, "hint": "load the shapes first"})
        self.assertEqual(REFUSED, result.returncode, result.stdout + result.stderr)
        self.assertIn("REFUSED", result.stdout)
        self.assertIn("load the shapes first", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    # ------------------------------------------- structured, not text-scraped
    def test_a_nested_count_is_not_read_as_the_count(self):
        """The `sed` this replaced matched the LAST "count" in the body.

        `.*"count"` is greedy, so a nested `stats.count` won the parse: against
        this response the old expression reports 9999 when the count is 7
        (verified). Parsing JSON reads the top-level key and the nested one
        cannot reach it.
        """
        result = self.seed(
            {
                "count": 7,
                "outcome": "created",
                "conforms": True,
                "stats": {"count": 9999},
            }
        )
        self.assertEqual(OK, result.returncode, result.stdout + result.stderr)
        self.assertIn("count 7", result.stdout)
        self.assertNotIn("count 9999", result.stdout)

    def test_an_unparseable_answer_is_could_not_tell_not_success(self):
        result = self.seed(b"<html>502 Bad Gateway</html>")
        self.assertEqual(OK, result.returncode, result.stdout + result.stderr)
        self.assertIn("unconfirmed", result.stdout)


if __name__ == "__main__":
    unittest.main()
