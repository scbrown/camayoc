"""Shell scripts must survive bash 3.2, because macOS /bin/bash IS bash 3.2.

THE BUG THIS EXISTS TO STOP RECURRING (aegis-qqutu3). Under `set -u`, bash
3.2.57 treats the expansion of an EMPTY array as an unbound variable:

    bash -uc 'A=(); printf "[%s]" "${A[@]}"'
      bash 5.x (vati, homebrew)  -> prints nothing, exit 0
      /bin/bash 3.2.57 (macOS)   -> A[@]: unbound variable, dies

Our auth arrays are declared empty and populated ONLY when a token exists:

    AUTH=()
    [ -n "${QUIPU_AUTH_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer ...")

so the no-token path is exactly the empty-array case. The tests invoke these
scripts with PATH scrubbed to /usr/bin:/bin, which on macOS selects the 2007
system bash — so `just test` reported 73 failures on a Mac and 0 on vati, and
the repo's own green-before-push gate was unmeetable on a Mac for ANY change.

WHY A LINT AND NOT A BEHAVIOURAL TEST. This cannot be reproduced on Linux:
`BASH_COMPAT=3.2` does NOT restore the old nounset behaviour (measured — it
still prints nothing and exits 0), and no bash 3.2 is installed here. So a
test that ran the scripts would pass on this host whether or not the bug was
present, which is the shape of test that lets a regression through while
reporting green. Checking the SOURCE for the portable idiom is the thing that
is actually decidable on the machine running the suite.

The idiom `${A[@]+"${A[@]}"}` expands to nothing when unset/empty and to the
quoted elements otherwise, on both 3.2 and 5.x, and keeps `set -u`.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRS = ("scripts", "hooks", "commands")

#: `NAME=()` — an array that starts empty, so it CAN be empty at expansion.
EMPTY_DECL = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)=\(\)\s*$', re.M)
#: `set -u` in any of its spellings (-u, -eu, -euo pipefail, set -o nounset).
NOUNSET = re.compile(r'^\s*set\s+-[a-z]*u|^\s*set\s+-o\s+nounset', re.M)


def bare_expansion(name: str) -> re.Pattern:
    """`"${NAME[@]}"` NOT already wrapped in the `+` guard."""
    return re.compile(r'(?<!\+)"\$\{' + re.escape(name) + r'\[@\]\}"')


def shell_scripts() -> list[Path]:
    out: list[Path] = []
    for d in DIRS:
        p = ROOT / d
        if p.is_dir():
            out.extend(sorted(p.rglob("*.sh")))
    return out


def violations(text: str) -> list[str]:
    """Names of empty-declared arrays expanded barely under `set -u`."""
    if not NOUNSET.search(text):
        return []
    return [n for n in set(EMPTY_DECL.findall(text)) if bare_expansion(n).search(text)]


class EmptyArrayExpansionsAreGuarded(unittest.TestCase):
    def test_no_script_expands_a_possibly_empty_array_barely(self):
        bad = {}
        for f in shell_scripts():
            names = violations(f.read_text())
            if names:
                bad[str(f.relative_to(ROOT))] = sorted(names)
        self.assertEqual(bad, {}, "\n".join(
            [f"{p}: {ns} — use ${{NAME[@]+\"${{NAME[@]}}\"}}; bare expansion of an "
             f"empty array dies under set -u on macOS /bin/bash 3.2 (aegis-qqutu3)"
             for p, ns in bad.items()]))

    def test_the_suite_actually_looks_at_some_scripts(self):
        # A lint over an empty file list passes vacuously and forever.
        self.assertGreater(len(shell_scripts()), 5)

    def test_the_scripts_the_bug_was_measured_in_are_covered(self):
        covered = {str(p.relative_to(ROOT)) for p in shell_scripts()}
        for f in ("scripts/gate_probe.sh", "scripts/seed_knowledge.sh"):
            self.assertIn(f, covered)


class TheDetectorCanDetect(unittest.TestCase):
    """POSITIVE CONTROL. A lint that has only ever been observed passing is
    indistinguishable from one whose pattern never matches anything."""

    def test_it_flags_the_exact_pre_fix_shape(self):
        pre_fix = (
            '#!/usr/bin/env bash\nset -u\nAUTH=()\n'
            '[ -n "${TOK:-}" ] && AUTH=(-H "Authorization: Bearer $TOK")\n'
            'curl -s "$URL" "${AUTH[@]}" -d @-\n'
        )
        self.assertEqual(violations(pre_fix), ["AUTH"])

    def test_it_passes_the_fixed_shape(self):
        fixed = (
            '#!/usr/bin/env bash\nset -u\nAUTH=()\n'
            '[ -n "${TOK:-}" ] && AUTH=(-H "Authorization: Bearer $TOK")\n'
            'curl -s "$URL" ${AUTH[@]+"${AUTH[@]}"} -d @-\n'
        )
        self.assertEqual(violations(fixed), [])

    def test_an_array_that_can_never_be_empty_is_not_flagged(self):
        # reconcile_metrics.sh's ARGS is built with three elements. Guarding it
        # would imply a hazard it does not have.
        never_empty = ('#!/usr/bin/env bash\nset -u\n'
                       'ARGS=("$SRC" -o "$TTL")\npython3 x.py "${ARGS[@]}"\n')
        self.assertEqual(violations(never_empty), [])

    def test_a_script_without_set_u_is_not_flagged(self):
        no_u = '#!/usr/bin/env bash\nAUTH=()\ncurl -s "$URL" "${AUTH[@]}"\n'
        self.assertEqual(violations(no_u), [])


if __name__ == "__main__":
    unittest.main()
