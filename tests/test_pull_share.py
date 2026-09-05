"""Tests for scripts/pull_share.py — the Camayoc share pull verb.

The load-bearing arm is the QUARANTINE one. A share whose vocabulary this store
does not govern is the DEFAULT outcome of pulling from anyone else, so a suite
that only covers an already-governed share would pass on a verb that cannot do
the thing it exists for (aegis-ltaypw condition B).

Stubs are written as fresh files, never symlinked to a real binary: redirection
follows a symlink and writes THROUGH it into the real tool (aegis-ydrml).
"""

from __future__ import annotations

import importlib.util, json, os, stat, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pull_share", ROOT / "scripts/pull_share.py")
pull_share = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules["pull_share"] = pull_share
SPEC.loader.exec_module(pull_share)


def stub(path: Path, body: str, log: Path | None = None) -> str:
    """A fake quipu. A fresh regular file — never a link to the real one.

    With `log`, it records every invocation's argv. That is what lets a test
    assert `quipu shapes load` was NEVER CALLED, rather than assert that the
    verdict says it was not — the report is a field the function fills in about
    itself, so asserting it proves the report and not the behaviour (malcolm).
    """
    rec = f'printf "%s\\n" "$*" >> {log}\n' if log else ""
    path.write_text("#!/usr/bin/env bash\n" + rec + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def share_dir(root: Path, *, shapes: str = "", share_id: str = "sha256:" + "b" * 64) -> Path:
    d = root / "share"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"share_id": share_id, "producer": {"name": "quipu"}}))
    (d / "export.nt").write_text("")
    (d / "shapes.ttl").write_text(shapes)
    return d


class VersionGuard(unittest.TestCase):
    """Condition A: refuse naming the version needed, never surface
    `unrecognized subcommand` — which reads as 'the feature is broken'."""

    def test_an_old_quipu_is_refused_and_the_needed_version_is_named(self):
        with tempfile.TemporaryDirectory() as t:
            q = stub(Path(t) / "quipu", 'echo "quipu 0.3.7"\n')
            with self.assertRaises(pull_share.PullError) as cm:
                pull_share.require_quipu(q)
            msg = str(cm.exception)
            self.assertIn("0.3.7", msg)
            self.assertIn("0.3.30", msg, "the refusal must name the version it NEEDS")
            self.assertIn("--quipu-bin", msg, "and the flag that fixes it")

    def test_a_new_enough_quipu_passes(self):
        with tempfile.TemporaryDirectory() as t:
            q = stub(Path(t) / "quipu", 'echo "quipu 0.3.36"\n')
            self.assertEqual(pull_share.require_quipu(q), (0, 3, 36))

    def test_a_binary_that_reports_no_version_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            q = stub(Path(t) / "quipu", 'echo "not a version"\n')
            with self.assertRaises(pull_share.PullError):
                pull_share.require_quipu(q)


class QuarantineIsSuccess(unittest.TestCase):
    """Condition B + wu's ruling: staging is the CORRECT outcome and exits 0.

    If it exited nonzero, every wrapper downstream would treat the correct
    outcome as a failure, and the eventual 'fix' is auto-promotion — the exact
    silent vocabulary widening quarantine exists to prevent.
    """

    def _quarantining_quipu(self, t: Path, log: Path | None = None) -> str:
        return stub(t / "quipu", f'''
case "$1" in
  --version) echo "quipu 0.3.36" ;;
  import) echo '{json.dumps({"outcome": "quarantined", "share_id": "sha256:" + "b"*64,
                             "staging_graph": "urn:quipu:import:quarantine:x",
                             "triples": {"accepted": 0, "quarantined": 6},
                             "promotion": {"blockers": ["off_vocabulary"]},
                             "resolution": {"unmatched": ["ex:alpha"]}})}' ;;
  *) exit 0 ;;
esac
''', log=log)

    def test_a_quarantined_pull_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            rc = pull_share.main([str(share_dir(t, shapes="ex:S a sh:NodeShape .")),
                                  "--db", str(t / "x.db"), "--quipu-bin", self._quarantining_quipu(t)])
            self.assertEqual(rc, 0, "a quarantine is a SUCCESS; nonzero is for failed verification")

    def test_next_names_the_adopt_flag_when_the_bundle_HAS_shapes(self):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            v = pull_share.pull(str(share_dir(t, shapes="ex:S a sh:NodeShape .")),
                                str(t / "x.db"), self._quarantining_quipu(t), False)
            self.assertEqual(v["outcome"], "quarantined")
            self.assertIn("--adopt-shapes", v["next"])

    def test_next_is_ABSENT_when_the_bundle_ships_empty_shapes(self):
        """The remedy would not work, so no command is offered.

        A discovery tool that hands you an action contradicting its own finding
        is worse than one that offers none (aegis-sosiaa / quipu #151).
        """
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            v = pull_share.pull(str(share_dir(t, shapes="")), str(t / "x.db"),
                                self._quarantining_quipu(t), False)
            self.assertIsNone(v["next"])
            self.assertIn("EMPTY shapes.ttl", v["next_reason"])

    def test_pull_NEVER_invokes_shapes_load_without_the_flag(self):
        """The load-bearing rule, pinned by invocation rather than by report.

        Before this, moving the `if do_adopt:` guard — or defaulting it to
        true — passed the whole suite: the no-adopt path was exercised and
        nothing asserted about it (malcolm's reader pass).
        """
        with tempfile.TemporaryDirectory() as td:
            t = Path(td); log = t / "calls.log"
            q = self._quarantining_quipu(t, log=log)
            pull_share.pull(str(share_dir(t, shapes="ex:S a sh:NodeShape .")),
                            str(t / "x.db"), q, False)
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertTrue(calls, "the stub recorded nothing — the log is not wired")
            self.assertFalse([c for c in calls if c.startswith("shapes load")],
                             f"pull WIDENED the vocabulary without --adopt-shapes: {calls}")

    def test_pull_DOES_invoke_shapes_load_with_the_flag(self):
        """The other half of the pair: proves the assertion above can fail."""
        with tempfile.TemporaryDirectory() as td:
            t = Path(td); log = t / "calls.log"
            q = self._quarantining_quipu(t, log=log)
            pull_share.pull(str(share_dir(t, shapes="ex:S a sh:NodeShape .")),
                            str(t / "x.db"), q, True)
            calls = log.read_text().splitlines()
            self.assertTrue([c for c in calls if c.startswith("shapes load")],
                            f"--adopt-shapes did not reach `quipu shapes load`: {calls}")

    def test_next_names_the_binary_that_WORKED_not_a_literal_quipu(self):
        """wu's finding, and it breaks in exactly the case the version guard exists for.

        A caller only reaches here with --quipu-bin because the PATH quipu was
        refused as too old. Emitting a literal `quipu` hands them a command
        that dies `unrecognized subcommand`.
        """
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            q = stub(t / "newer-quipu", f'''
case "$1" in
  --version) echo "quipu 0.3.36" ;;
  import) echo '{json.dumps({"outcome": "staged", "share_id": "sha256:" + "d"*64,
                             "triples": {"accepted": 6, "quarantined": 0}})}' ;;
  *) exit 0 ;;
esac
''')
            v = pull_share.pull(str(share_dir(t)), str(t / "x.db"), q, False)
            self.assertIn(q, v["next"], "next must name the binary that actually works")
            self.assertFalse(v["next"].startswith("quipu "),
                             "next hardcoded a bare `quipu` the caller was just refused")

    def test_the_emitted_next_actually_RUNS_with_a_non_default_binary(self):
        """wu asked for this arm specifically, and it is the one that would have
        caught the defect: asserting the string CONTAINS the binary is weaker
        than running it. My own pre-merge acceptance ran the emitted command as
        ${NEXT/#quipu/$Q} — I substituted the binary by hand, which is exactly
        the bug, performed instead of detected."""
        import shlex, subprocess
        with tempfile.TemporaryDirectory() as td:
            t = Path(td); log = t / "calls.log"
            q = stub(t / "newer-quipu", f'''
printf "%s\\n" "$*" >> {log}
case "$1" in
  --version) echo "quipu 0.3.36" ;;
  import) echo '{json.dumps({"outcome": "staged", "share_id": "sha256:" + "e"*64,
                             "triples": {"accepted": 6, "quarantined": 0}})}' ;;
  *) exit 0 ;;
esac
''')
            v = pull_share.pull(str(share_dir(t)), str(t / "x.db"), q, False)
            r = subprocess.run(shlex.split(v["next"]), capture_output=True, text=True)
            self.assertEqual(r.returncode, 0,
                             f"the emitted next did not run: {r.stderr.strip()!r}")
            self.assertIn("import promote", log.read_text(),
                          "next ran, but not against the binary we were told to use")

    def test_the_adopt_shapes_retry_also_names_the_binary(self):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            q = self._quarantining_quipu(t)
            v = pull_share.pull(str(share_dir(t, shapes="ex:S a sh:NodeShape .")),
                                str(t / "x.db"), q, False)
            self.assertIn("--adopt-shapes", v["next"])
            self.assertIn(f"--quipu-bin {q}", v["next"])

    def test_promote_command_is_emitted_once_nothing_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            q = stub(t / "quipu", f'''
case "$1" in
  --version) echo "quipu 0.3.36" ;;
  import) echo '{json.dumps({"outcome": "staged", "share_id": "sha256:" + "c"*64,
                             "triples": {"accepted": 6, "quarantined": 0}})}' ;;
  *) exit 0 ;;
esac
''')
            v = pull_share.pull(str(share_dir(t)), str(t / "x.db"), q, False)
            self.assertEqual(v["next"], f"{q} import promote sha256:{'c'*64} --db {t / 'x.db'}")


class VerificationFailsLoudly(unittest.TestCase):
    """The one case that MUST be nonzero."""

    def test_a_pack_that_fails_verification_refuses_before_loading(self):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            pack = t / "bad.qpack.db"; pack.write_bytes(b"not a pack")
            q = stub(t / "quipu", '''
case "$1" in
  --version) echo "quipu 0.3.36" ;;
  pack) echo "pack: content hash mismatch" >&2; exit 1 ;;
  unpack) echo "SHOULD NOT REACH UNPACK"; exit 0 ;;
esac
''')
            rc = pull_share.main([str(pack), "--db", str(t / "x.db"), "--quipu-bin", q])
            self.assertEqual(rc, 2)

    def test_a_directory_without_a_manifest_is_not_a_share(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "notashare"; d.mkdir()
            with self.assertRaises(pull_share.PullError) as cm:
                pull_share.classify(str(d))
            self.assertIn("manifest.json", str(cm.exception))

    def test_a_missing_source_is_refused(self):
        with self.assertRaises(pull_share.PullError):
            pull_share.classify("/nonexistent/share/path")


class AdoptShapesIsExplicit(unittest.TestCase):
    def test_empty_shapes_are_not_adopted_and_say_so(self):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td); s = t / "shapes.ttl"; s.write_text("")
            r = pull_share.adopt_shapes("quipu-unused", s, "n", str(t / "x.db"))
            self.assertFalse(r["adopted"])
            self.assertIn("no shapes.ttl content", r["reason"])

    def test_a_failed_shape_load_is_a_refusal_not_a_warning(self):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td); s = t / "shapes.ttl"; s.write_text("ex:S a sh:NodeShape .")
            q = stub(t / "quipu", 'echo "shape parse error" >&2; exit 1\n')
            with self.assertRaises(pull_share.PullError):
                pull_share.adopt_shapes(q, s, "n", str(t / "x.db"))


if __name__ == "__main__":
    unittest.main()
