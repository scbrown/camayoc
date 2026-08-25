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


class IriLaneTests(unittest.TestCase):
    """The base is the whole edge.

    An `aegis:modifies` edge is only worth writing if it lands on a CodeModule
    that exists. This script shipped for a while pointing at
    `http://aegis.gastown.local/code/`, which quipu measured at ZERO live
    subjects against 10,425 under the ontology base — so every edge it wrote
    joined to nothing, which reads exactly like the unbuilt adapter this script
    was written to replace. These tests are what stop that recurring, and they
    fail loudly rather than drifting quietly.
    """

    ONTO = "http://aegis.gastown.local/ontology/"

    def test_a_module_iri_is_the_one_the_live_code_graph_uses(self):
        self.assertEqual(
            mod.iri("bobbin", "src/lib.rs"),
            f"{self.ONTO}code/bobbin/src%2Flib.rs",
        )

    def test_the_dead_lane_is_not_minted_under_any_shape(self):
        """The specific regression: a bare `/code/` base with no `ontology/`."""
        for built in (
            mod.iri("bobbin", "src/lib.rs"),
            mod.iri("bobbin", "commit", "abc123"),
            mod.iri("bead", "camayoc-7lt"),
        ):
            self.assertTrue(built.startswith(f"{self.ONTO}code/"), built)
            self.assertNotIn("gastown.local/code/", built)

    def test_a_commit_iri_matches_yupanas_producer(self):
        """yupana `export::commit_iri` mints `{ONTO}code/{repo}/commit/{sha}`.

        Both lanes emit a GitCommit node for the same commit; identical IRIs
        mean `/knot` supersedes per (s, p, o) rather than landing a second,
        disjoint population of the same referent.
        """
        self.assertEqual(
            mod.iri("yupana", "commit", "0123456789ab"),
            f"{self.ONTO}code/yupana/commit/0123456789ab",
        )

    def test_the_two_producers_agree_on_every_realistic_source_path(self):
        """yupana's `module_iri` replaces only `/`. For the path alphabet these
        repos contain, that is the same string this script builds."""
        for path in ("src/lib.rs", "src/cli/hook.rs", "README.md",
                     "scripts/beads-jsonl.py", "docs/design/ingress.md"):
            self.assertEqual(
                mod.iri("r", path),
                f"{self.ONTO}code/r/" + path.replace("/", "%2F"),
                path,
            )

    def test_the_encoders_diverge_outside_that_alphabet_and_this_side_is_right(self):
        """Pinned as a known divergence, not smoothed over.

        yupana would emit a raw space here, which is not a legal IRI character;
        this script percent-encodes it. Recorded so nobody "fixes" the mismatch
        by copying the weaker encoder — the unification belongs upstream.
        """
        built = mod.iri("r", "src/foo bar.rs")
        self.assertEqual(built, f"{self.ONTO}code/r/src%2Ffoo%20bar.rs")
        self.assertNotIn(" ", built)


if __name__ == "__main__":
    unittest.main()
