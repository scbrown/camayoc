"""`scripts/beads-jsonl.py` — the tracker is the file, so the guards are the tracker.

This repo has no Dolt database: `.beads/issues.jsonl` IS the issue tracker, not
an export of one, so a bad write here is silent data loss committed as an
ordinary-looking diff. The script's value is therefore almost entirely in what
it refuses, and until now none of those refusals had ever been observed to
fire — the same defect shape `scripts/gate_probe.sh` exists to prevent one
layer down. Most of the tests below assert a refusal.

`retitle` is the verb these tests were written for. It is the one write that
CHANGES an existing field rather than appending to one, which makes it the one
verb that could be lossy — so the property that matters is not "the title
changed" but "the old title survived the change", and that is asserted
directly rather than inferred from the exit status.

Every test runs against a temporary copy of the file. Nothing here touches the
real tracker.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_script():
    spec = importlib.util.spec_from_file_location(
        "beads_jsonl", ROOT / "scripts" / "beads-jsonl.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


beads = load_script()

SEED = [
    {"id": "camayoc-aaa", "title": "a title that went stale", "status": "open",
     "priority": 2, "issue_type": "task", "notes": "an existing note"},
    {"id": "camayoc-bbb", "title": "no notes yet", "status": "open",
     "priority": 3, "issue_type": "task"},
    {"id": "camayoc-ccc", "title": "settled", "status": "closed",
     "priority": 3, "issue_type": "task"},
]


class ScriptTestCase(unittest.TestCase):
    """Points the script at a throwaway JSONL for the duration of one test."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        path = Path(self._dir.name) / "issues.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in SEED))
        self._real, beads.JSONL = beads.JSONL, path
        self.addCleanup(lambda: setattr(beads, "JSONL", self._real))
        self.path = path

    def invoke(self, *argv) -> int:
        argv_before, sys.argv = sys.argv, ["beads-jsonl.py", *argv]
        try:
            return beads.main()
        finally:
            sys.argv = argv_before

    def record(self, issue_id: str) -> dict:
        return beads.find(beads.load(), issue_id)


class RetitleTests(ScriptTestCase):
    def test_the_title_changes(self):
        self.assertEqual(0, self.invoke("retitle", "camayoc-aaa", "--title", "the true scope"))
        self.assertEqual("the true scope", self.record("camayoc-aaa")["title"])

    def test_the_old_title_survives_in_the_notes(self):
        """THE POINT OF THE VERB. A corrected title that erases the wrong one
        hides how long the record misled — which is why hand-editing the field
        was not an option and this exists instead."""
        self.invoke("retitle", "camayoc-aaa", "--title", "the true scope")
        self.assertIn("a title that went stale", self.record("camayoc-aaa")["notes"])

    def test_the_existing_notes_are_not_replaced(self):
        self.invoke("retitle", "camayoc-aaa", "--title", "the true scope")
        self.assertIn("an existing note", self.record("camayoc-aaa")["notes"])

    def test_it_works_on_an_issue_with_no_notes_at_all(self):
        self.invoke("retitle", "camayoc-bbb", "--title", "renamed")
        self.assertIn("no notes yet", self.record("camayoc-bbb")["notes"])
        self.assertEqual("renamed", self.record("camayoc-bbb")["title"])

    def test_two_retitles_keep_both_previous_titles(self):
        """Notes only ever grow, so the whole chain of corrections stays
        readable. A second retitle that dropped the first would be the same
        loss one step removed."""
        self.invoke("retitle", "camayoc-aaa", "--title", "second")
        self.invoke("retitle", "camayoc-aaa", "--title", "third")
        notes = self.record("camayoc-aaa")["notes"]
        self.assertIn("a title that went stale", notes)
        self.assertIn("second", notes)

    def test_updated_at_is_bumped(self):
        self.invoke("retitle", "camayoc-aaa", "--title", "the true scope")
        self.assertIn("updated_at", self.record("camayoc-aaa"))

    def test_a_blank_title_is_refused(self):
        """It would lose the old title and put nothing in its place."""
        self.assertEqual(1, self.invoke("retitle", "camayoc-aaa", "--title", "   "))
        self.assertEqual("a title that went stale", self.record("camayoc-aaa")["title"])

    def test_a_no_op_retitle_is_refused_rather_than_noted(self):
        """A note recording that nothing changed is noise dressed as
        provenance, and it would grow the notes on every accidental repeat."""
        self.assertEqual(
            1, self.invoke("retitle", "camayoc-aaa", "--title", "a title that went stale")
        )
        self.assertEqual("an existing note", self.record("camayoc-aaa")["notes"])

    def test_an_unknown_id_is_refused(self):
        with self.assertRaises(SystemExit):
            self.invoke("retitle", "camayoc-zzz", "--title", "x")

    def test_no_other_record_is_touched(self):
        """The file is rewritten whole on every write, so 'the other lines came
        back unchanged' is a property worth asserting rather than assuming."""
        self.invoke("retitle", "camayoc-aaa", "--title", "the true scope")
        self.assertEqual(3, len(beads.load()))
        self.assertEqual("settled", self.record("camayoc-ccc")["title"])
        self.assertEqual("closed", self.record("camayoc-ccc")["status"])


class LossRefusalTests(ScriptTestCase):
    """The guards `retitle` relies on. Each is asserted to actually fire."""

    def test_a_disappearing_record_is_refused(self):
        before = beads.load()
        with self.assertRaises(SystemExit) as caught:
            beads.save([r for r in before if r["id"] != "camayoc-bbb"], before)
        self.assertIn("would disappear", str(caught.exception))

    def test_shrinking_notes_are_refused(self):
        """The guard that makes retitle safe. If this did not fire, a verb
        that replaced the notes instead of appending would pass every test
        above except the ones that read the notes back."""
        before = beads.load()
        after = json.loads(json.dumps(before))
        beads.find(after, "camayoc-aaa")["notes"] = ""
        with self.assertRaises(SystemExit) as caught:
            beads.save(after, before)
        self.assertIn("notes would shrink", str(caught.exception))

    def test_reopening_a_closed_issue_is_refused(self):
        before = beads.load()
        after = json.loads(json.dumps(before))
        beads.find(after, "camayoc-ccc")["status"] = "open"
        with self.assertRaises(SystemExit) as caught:
            beads.save(after, before)
        self.assertIn("would reopen", str(caught.exception))

    def test_a_retitle_that_replaced_notes_would_be_caught(self):
        """Adversarial: the refusal is proven against the exact mistake the
        verb could make, not only against a synthetic empty string."""
        before = beads.load()
        after = json.loads(json.dumps(before))
        beads.find(after, "camayoc-aaa")["notes"] = "retitled"
        beads.find(after, "camayoc-aaa")["title"] = "the true scope"
        with self.assertRaises(SystemExit):
            beads.save(after, before)


class NoteAndCloseStillWorkTests(ScriptTestCase):
    """`retitle` shares `append_note` with `note`; neither may drift."""

    def test_note_appends(self):
        self.invoke("note", "camayoc-aaa", "--text", "a second note")
        notes = self.record("camayoc-aaa")["notes"]
        self.assertIn("an existing note", notes)
        self.assertIn("a second note", notes)

    def test_closing_records_the_reason(self):
        self.assertEqual(0, self.invoke("close", "camayoc-bbb", "--reason", "done"))
        self.assertEqual("closed", self.record("camayoc-bbb")["status"])
        self.assertEqual("done", self.record("camayoc-bbb")["close_reason"])

    def test_closing_an_already_closed_issue_is_refused(self):
        self.assertEqual(1, self.invoke("close", "camayoc-ccc", "--reason", "again"))


if __name__ == "__main__":
    unittest.main()
