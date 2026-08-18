#!/usr/bin/env python3
"""Tests for scripts/ingest_git_provenance.py — the git → provenance ingest.

The property under test is ABSTENTION, not extraction. These edges become an
agent's capability scope in yupana, so a commit linked to the wrong work item
does not mislabel one row — it silently widens some item's ground, and a
too-wide scope simply stops advising, which looks exactly like a well-behaved
agent.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ingest_git_provenance",
    Path(__file__).resolve().parent.parent / "scripts" / "ingest_git_provenance.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

PROJECTS = ["aegis", "bobbin", "quipu", "camayoc"]


def ids(message: str, projects=None):
    pattern = mod.item_pattern(projects or PROJECTS)
    return sorted(set(pattern.findall(message.lower())))


class ItemMatchTests(unittest.TestCase):
    def test_real_ids_are_recognised(self):
        self.assertEqual(ids("fix(guard): close bobbin-052"), ["bobbin-052"])
        self.assertEqual(ids("feat: camayoc-b6h and quipu-mq7"),
                         ["camayoc-b6h", "quipu-mq7"])

    def test_an_id_with_no_digits_is_still_an_id(self):
        """bobbin-bbe is real. Any rule keyed on 'the suffix contains a digit'
        would drop it — which is why the PREFIX is the discriminator."""
        self.assertEqual(ids("chore: bobbin-bbe"), ["bobbin-bbe"])

    def test_ORDINARY_HYPHENATED_ENGLISH_IS_NOT_A_WORK_ITEM(self):
        """THE MEASURED DEFECT. The first version of this script used a loose
        `[a-z][a-z0-9]*-[0-9a-z]{2,6}` and, run against this repo's own history,
        read every one of these as a work-item id — writing paths into the
        ground of items that do not exist.

        This is the assertion that would have caught it, and it is the reason
        the project prefix must be declared rather than inferred: there is no
        pattern separating an id from a hyphenated word.
        """
        prose = ("advise-mode work-item authored-by pre-push force-push "
                 "read-only fail-open two-sided")
        self.assertEqual(ids(prose), [])

    def test_an_undeclared_project_is_NOT_matched(self):
        """Abstention, not a guess. A commit naming a project nobody declared is
        unlinked — and the runner's summary says how many, so a misconfigured
        --project shows up as a coverage number rather than as silence."""
        self.assertEqual(ids("fix: shantytown-9kk", projects=["bobbin"]), [])

    def test_a_word_boundary_is_required_on_both_sides(self):
        """`see-bobbin-052` names the item; `xbobbin-052` does not."""
        self.assertEqual(ids("see-bobbin-052"), ["bobbin-052"])
        self.assertEqual(ids("xbobbin-052"), [])


class PathFilterTests(unittest.TestCase):
    def test_build_output_and_lockfiles_do_not_enter_a_scope(self):
        """A commit that also touched a lockfile must not scope its item to the
        lockfile — that is a path an agent would then be advised about forever."""
        for path in ("target/debug/foo", "node_modules/x/y.js", "Cargo.lock",
                     "app.min.js", "bundle.map"):
            self.assertFalse(mod.interesting(path), path)

    def test_the_control_ordinary_source_paths_ARE_interesting(self):
        """Without this the filter could reject everything and the test above
        would still pass."""
        for path in ("src/main.rs", "docs/design/ingress.md", "scripts/planes.py"):
            self.assertTrue(mod.interesting(path), path)


if __name__ == "__main__":
    unittest.main()
