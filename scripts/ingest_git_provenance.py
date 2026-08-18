#!/usr/bin/env python3
"""Walk git history and emit the work-item provenance chain as Turtle.

    Bead  <--aegis:implements--  GitCommit  --aegis:modifies-->  CodeModule

THE GAP THIS CLOSES
===================

docs/design/ingress.md §3.3 claims this adapter — "Commit history → work-item
linkage (aegis:implements, aegis:modifies). Pure observed." Nothing implemented
it. That mattered more than an unbuilt adapter usually does, because three
consumers outside this repo read that chain and none of them owns it:

  * yupana's WORK_ITEM_SCOPE_QUERY builds the OBSERVED rung of the capability
    ladder from it — the only rung that was live until the derived one landed;
  * yupana's work-item briefing reads it for an item's ground;
  * quipu's entity_work / cochanged_with / cooccurrence traverse it, and quipu's
    own named_query.rs carries the caveat that they "return nothing until
    Phase-4 promotion populates the modifies/implements edges".

So a repository this never ran against produces UNKNOWN scope for every agent
working in it — correctly, and uselessly.

DETERMINISTIC, WHICH IS THE WHOLE POINT
=======================================

Ingress rule: deterministic-first, and anything a model inferred lands
quarantined. There is no inference here. A commit is linked to a work item only
by an explicit id in its message; the file paths come from `git diff-tree`. Run
it twice on the same history and you get byte-identical Turtle.

ABSTAIN, NEVER GUESS. A commit whose message names no work item emits NOTHING —
not a commit node with no linkage, not a guess from the branch name. These edges
become an agent's capability scope, and a commit attributed to the wrong item
would widen some other item's ground silently. An unlinked commit costs one row
of coverage; a wrongly-linked one corrupts a scope.

FACTS TRUE AT WRITE TIME. A commit touched the paths it touched, forever; that
is why this is `observed` and why nothing here decays. No status, no "is this
still the current implementation" — those are read-time questions.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

BASE = "http://aegis.gastown.local/code/"
ONTOLOGY = "http://aegis.gastown.local/ontology/"

# A work-item id is `<project>-<suffix>`: aegis-1q14, bobbin-052, quipu-mq7,
# camayoc-7lt. The PROJECT PREFIX is the discriminator and it must be declared —
# there is no pattern that separates an id from ordinary hyphenated English.
#
# THIS WAS MEASURED, NOT REASONED. The first version of this script used
# `\b([a-z][a-z0-9]*-[0-9a-z]{2,6})\b` and, run against this repo's own history,
# read `work-item`, `advise-mode`, `authored-by`, `pre-push` and `force-push` as
# work-item ids — writing paths into the ground of five items that do not exist.
# A digit test does not save it either: `bobbin-bbe` is a real id with no digit.
#
# So: abstain unless the prefix is a project somebody named. Widening this to
# catch more commits is the wrong trade in the only direction that matters —
# every false match silently widens some item's scope, and a too-wide scope
# simply stops advising, which looks exactly like a well-behaved agent.
def item_pattern(projects: list[str]) -> re.Pattern:
    alt = "|".join(re.escape(p.lower()) for p in sorted(set(projects)))
    return re.compile(rf"\b(?:{alt})-[0-9a-z]{{2,6}}\b")

# Paths whose changes say nothing about where an item's work lives. A commit
# that also touched a lockfile should not scope its item to the lockfile.
SKIP_PREFIXES = ("target/", "node_modules/", "dist/", "build/", ".git/")
SKIP_SUFFIXES = (".lock", ".min.js", ".map")


def iri(*parts: str) -> str:
    return BASE + "/".join(quote(p, safe="") for p in parts)


def run(repo: Path, *args: str) -> str:
    """git, or an empty string. A repo we cannot read contributes nothing and
    says so on stderr — it must not abort an ingest across several repos."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"  ! {repo}: git {' '.join(args)} failed: {e}", file=sys.stderr)
        return ""


def interesting(path: str) -> bool:
    if path.startswith(SKIP_PREFIXES) or path.endswith(SKIP_SUFFIXES):
        return False
    return bool(path.strip())


def commits(repo: Path, since: str | None, limit: int):
    """Yield (sha, subject+body, [paths]) newest-first.

    `-z` and a record separator rather than line parsing: commit messages
    contain newlines, and a parser that assumed otherwise would silently
    mis-attribute every multi-paragraph commit.
    """
    sep = "\x1e"
    args = ["log", f"--max-count={limit}", f"--pretty=format:{sep}%H%x1f%B%x1f",
            "--name-only", "--no-merges"]
    if since:
        args.append(f"--since={since}")
    out = run(repo, *args)
    for record in out.split(sep):
        if not record.strip():
            continue
        try:
            sha, message, files_blob = record.split("\x1f", 2)
        except ValueError:
            continue
        paths = [p for p in (l.strip() for l in files_blob.splitlines()) if interesting(p)]
        yield sha.strip(), message, paths


def emit(repo_name: str, sha: str, items: list[str], paths: list[str], out: list[str]) -> None:
    commit_iri = iri(repo_name, "commit", sha)
    out.append(f"<{commit_iri}> a <{ONTOLOGY}GitCommit> ;")
    out.append(f'    rdfs:label "{repo_name}@{sha[:12]}" ;')
    out.append(f'    <{ONTOLOGY}sourceKind> "observed" ;')
    for item in items:
        out.append(f'    <{ONTOLOGY}implements> <{iri("bead", item)}> ;')
    for i, path in enumerate(paths):
        term = " ;" if i < len(paths) - 1 else " ."
        out.append(f'    <{ONTOLOGY}modifies> <{iri(repo_name, path)}>{term}')
    if not paths:
        # Trailing `;` with nothing after it is invalid Turtle. A commit with
        # items but no interesting paths still records the linkage.
        out[-1] = out[-1].rstrip(" ;") + " ."
    out.append("")
    # The bead and the module must exist as typed nodes or the range shapes
    # have nothing to check. Repeated across commits, which is fine — Turtle
    # is a set, and quipu's fact log is idempotent on identical assertions.
    for item in items:
        out.append(f'<{iri("bead", item)}> a <{ONTOLOGY}Bead> ; '
                   f'<{ONTOLOGY}identifier> "{item}" .')
    for path in paths:
        out.append(f'<{iri(repo_name, path)}> a <{ONTOLOGY}CodeModule> ; '
                   f'<{ONTOLOGY}filePath> "{path}" .')
    out.append("")


def ingest(repo: Path, since: str | None, limit: int, out: list[str],
           pattern: re.Pattern) -> dict:
    name = repo.resolve().name
    stats = {"commits": 0, "linked": 0, "unlinked": 0, "edges": 0}
    for sha, message, paths in commits(repo, since, limit):
        stats["commits"] += 1
        items = sorted(set(pattern.findall(message.lower())))
        if not items:
            # ABSTAIN. See the module note: a guess here corrupts a scope.
            stats["unlinked"] += 1
            continue
        stats["linked"] += 1
        stats["edges"] += len(paths)
        emit(name, sha, items, paths, out)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repos", nargs="+", type=Path)
    ap.add_argument("--since", help="git --since (e.g. '6 months ago')")
    ap.add_argument("--limit", type=int, default=2000,
                    help="max commits per repo (default 2000)")
    ap.add_argument("--project", action="append", default=[], metavar="NAME",
                    help="tracker project prefix to recognise (repeatable). "
                         "Defaults to the names of the repos being ingested. "
                         "REQUIRED to be right: an undeclared project's commits "
                         "are silently unlinked, and a wrong one writes paths "
                         "into a scope that does not exist.")
    args = ap.parse_args()

    projects = args.project or [r.resolve().name for r in args.repos]
    pattern = item_pattern(projects)
    print(f"recognising work-item prefixes: {', '.join(sorted(set(projects)))}",
          file=sys.stderr)

    out = [f"@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .", ""]
    totals = {"commits": 0, "linked": 0, "unlinked": 0, "edges": 0}
    for repo in args.repos:
        if not (repo / ".git").exists():
            print(f"  ! {repo}: not a git repository — skipped", file=sys.stderr)
            continue
        stats = ingest(repo, args.since, args.limit, out, pattern)
        print(f"  {repo.resolve().name}: {stats['linked']} linked, "
              f"{stats['unlinked']} unlinked, {stats['edges']} modifies edge(s)",
              file=sys.stderr)
        for k in totals:
            totals[k] += stats[k]

    print("".join(f"{l}\n" for l in out), end="")

    # THE DENOMINATOR, on stderr, always. A coverage number that reported only
    # what it linked would let an ingest matching 5% of commits look like one
    # matching 95% — and downstream, a thin scope is indistinguishable from a
    # narrow one. Whoever reads a work-item's ground needs to know how much of
    # the history it was built from.
    print(f"\ntotal: {totals['linked']} of {totals['commits']} commit(s) carried a "
          f"work-item id ({totals['unlinked']} did not), {totals['edges']} modifies edge(s)",
          file=sys.stderr)
    if totals["unlinked"] and totals["commits"]:
        pct = 100 * totals["unlinked"] // totals["commits"]
        print(f"NOTE: {pct}% of commits name no work item under the recognised "
              f"prefixes and are therefore absent from every item's ground. That is "
              f"the ingest abstaining, not the history being empty — a scope built "
              f"from this is a floor. If that share looks high, check --project "
              f"before concluding the commits are unlabelled.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
