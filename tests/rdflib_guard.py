"""Whether rdflib is importable — and the rule that says when absence is allowed.

The query suites execute their stored queries with rdflib rather than against a
live quipu, so without it they skip *entirely*: three files, every execution
test in them. That is the right behaviour on a contributor's laptop, where the
alternative is a hard failure over a dependency the repo deliberately does not
vendor.

It is the wrong behaviour in CI, and this repo has already paid for the lesson
once. `.github/workflows/ci.yml` carries it in a comment on the `test` job:

    camayoc-045: the gate proofs used to run only inside the installer, on a
    machine that already had a quipu, which meant nobody ran them.

A suite that skips itself is the same failure wearing a green check. It is also
the shape this project names elsewhere in its own words — "an uncounted question
is a gap unreported" (`docs/design/implemented-set.md`), and gate_probe's
"could not look is not zero". The competency questions *are* this repo's test
suite, per the first rule in AGENTS.md; a CI run that silently executes none of
them reports a pass it did not earn.

So: skip when a human is running, refuse when a machine is. `CI` is set by
GitHub Actions (and by every other runner worth naming), which is exactly the
boundary between the two.
"""

from __future__ import annotations

import os
import unittest

try:
    import rdflib  # noqa: F401

    HAVE_RDFLIB = True
except ImportError:  # pragma: no cover - environment-dependent
    HAVE_RDFLIB = False

#: True when something automated is running us — GitHub Actions sets `CI=true`.
IN_CI = os.environ.get("CI", "").lower() in {"1", "true", "yes"}

_MISSING = (
    "rdflib is not installed, so the stored-query suites cannot execute. "
    "On a laptop this skips. In CI it fails, because a skipped query suite is "
    "an unreported gap wearing a green check — install it "
    "(`pip install rdflib`) in the workflow rather than reading this as a pass."
)


def requires_rdflib(cls):
    """Skip a query-execution suite without rdflib — but never silently in CI.

    Use in place of `@unittest.skipUnless(HAVE_RDFLIB, ...)` on any suite that
    cannot run without rdflib.
    """
    if HAVE_RDFLIB:
        return cls
    if IN_CI:
        # Not a skip: a class whose one test fails, so the run goes red and the
        # reason is the failure message rather than a line nobody reads.
        class RdflibMissingInCI(unittest.TestCase):
            def test_rdflib_must_be_installed_in_ci(self):
                self.fail(f"{_MISSING} (suite: {cls.__name__})")

        RdflibMissingInCI.__name__ = f"{cls.__name__}_RdflibMissingInCI"
        RdflibMissingInCI.__qualname__ = RdflibMissingInCI.__name__
        return RdflibMissingInCI
    return unittest.skip(_MISSING)(cls)
