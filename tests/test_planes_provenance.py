"""planes.provenance_headers (aegis-7zp4rc): every camayoc write says who wrote
it, from the environment, never typed; an unknown field is omitted."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import planes


class Provenance(unittest.TestCase):
    def test_a_cron_names_itself(self):
        with mock.patch("socket.gethostname", return_value="vati"):
            h = planes.provenance_headers("camayoc-ingress", env={})
        self.assertEqual(h, {"X-Quipu-Agent": "camayoc-ingress", "X-Quipu-Harness": "cron",
                             "X-Quipu-Host": "vati"})

    def test_an_agent_session_is_named_as_the_agent(self):
        env = {"CLAUDECODE": "1", "SHANTY_AGENT": "ian", "CLAUDE_CODE_SESSION_ID": "s-1"}
        h = planes.provenance_headers("camayoc-ingress", env=env)
        self.assertEqual((h["X-Quipu-Agent"], h["X-Quipu-Harness"], h["X-Quipu-Session"]),
                         ("ian", "claude", "s-1"))
        self.assertNotIn("X-Quipu-Model", h, "never guessed")

    def test_overrides_win_and_values_cannot_inject(self):
        env = {"QUIPU_AGENT": "a\r\nX-Evil: 1", "QUIPU_HARNESS": "service", "QUIPU_HOST": "h"}
        h = planes.provenance_headers("c", env=env)
        self.assertEqual((h["X-Quipu-Agent"], h["X-Quipu-Harness"]), ("aX-Evil: 1", "service"))
        self.assertNotIn("\n", "".join(h.values()))

    def test_codex_session_fallback_does_not_borrow_claude_identity(self):
        env = {"CODEX_HOME": "/tmp/codex", "CODEX_THREAD_ID": "thread",
               "CLAUDE_CODE_SESSION_ID": "stale-claude"}
        self.assertEqual(planes.provenance_headers("c", env)["X-Quipu-Session"], "thread")
        env["CODEX_SESSION_ID"] = "session"
        self.assertEqual(planes.provenance_headers("c", env)["X-Quipu-Session"], "session")
        env.pop("CODEX_SESSION_ID")
        env.pop("CODEX_THREAD_ID")
        self.assertNotIn("X-Quipu-Session", planes.provenance_headers("c", env))

    def test_selected_harness_and_explicit_session_win(self):
        env = {"CLAUDECODE": "1", "CODEX_HOME": "/tmp/codex",
               "CLAUDE_CODE_SESSION_ID": "claude", "CODEX_SESSION_ID": "codex"}
        self.assertEqual(planes.provenance_headers("c", env)["X-Quipu-Session"], "claude")
        env["QUIPU_HARNESS"] = "codex"
        self.assertEqual(planes.provenance_headers("c", env)["X-Quipu-Session"], "codex")
        env["QUIPU_SESSION"] = "explicit"
        self.assertEqual(planes.provenance_headers("c", env)["X-Quipu-Session"], "explicit")

    def test_post_sends_them_with_the_client_label(self):
        seen = {}

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"{}"

        def fake(req, timeout=None):
            seen.update({k.lower(): v for k, v in req.header_items()})
            return Resp()

        with mock.patch("urllib.request.urlopen", fake), mock.patch.dict("os.environ", {}, clear=True):
            planes._post("/episode", {}, client="camayoc-ingress")
        self.assertEqual((seen["x-quipu-client"], seen["x-quipu-agent"], seen["x-quipu-harness"]),
                         ("camayoc-ingress", "camayoc-ingress", "cron"))


if __name__ == "__main__":
    unittest.main()
