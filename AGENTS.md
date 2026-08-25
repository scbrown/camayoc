# camayoc - Agent Instructions

## Project Overview

The knot-keeper: bootstrap ontology, knowledge ingress discipline, and
knowledge-pack production for the quipu stack. Camayoc owns what facts MEAN
and how they EARN their way into the graph; it is deliberately not a store
(quipu), not a harness (shantytown), and not retrieval (bobbin).

Sibling repos: scbrown/quipu (governed store), scbrown/shantytown (crew
harness), scbrown/hank (code structure), scbrown/bobbin (retrieval).

## Conventions

- **Competency questions before classes.** No ontology term without a question
  in competency/ that needs it; the question suite is the test suite.
- **Reuse before minting** — aegis:/prov:/quipu:/bobbin: vocabularies first;
  camayoc: only for genuinely unowned terms. Namespaces are parameters, never
  hardcoded hostnames.
- **rdfs:range only, never rdfs:domain** on shared predicates.
- **Facts true at write time; judgments at read time.** Nothing stored that
  decays.
- **Deterministic-first ingress**; model-inferred facts land quarantined in
  low-trust planes, tagged, never masquerading.
- Design docs live in docs/design/ with an implementation-status banner in
  the quipu house style.

## Build Commands

```bash
just check           # markdown lint (grows the competency eval gate)
just test            # metrics slice + gate-probe refusal tests
```

## Git Workflow — trunk-based, straight to `main`

**Work on `main` and push to `main`.** Do not create feature branches, and do
not open pull requests, unless you are explicitly asked for one. Stated by
Stiwi, 2026-08-18.

```bash
git pull --rebase origin main     # before starting, and again before pushing
# ... work, with `just check` and `just test` green ...
git add -A && git commit && git push origin main
```

**What this costs, stated plainly, because the cost is the reason the rules
below exist.** There is no review step between a commit and the history
everyone else pulls, so **the quality gates are the only gate**. A red `main`
is immediately everyone's problem and there is no pull request standing
between you and it.

- **Run the gates before every push, not once at session end.** `just check` and `just test`.
  The pre-push gate this file specifies is not advisory here; it is the
  entire safety net.
- **Never force-push `main`.** If a push is rejected the remote has work you do
  not have; `git pull --rebase` and resolve it. A force-push discards someone
  else's commits silently, which is exactly the failure that has no undo.
- **Prefer small complete commits to one large end-of-session commit.** Each
  one lands live, so each one has to stand on its own.
- **Work that cannot pass the gates does not get pushed.** There is no branch
  to park it on — finish it, or leave it uncommitted and say so at handoff.

**On the managed "Agent Context Profiles" block below.** It sets a
Conservative default that forbids commits and pushes without explicit
instruction, and its Session Completion steps say to report proposed commands
and wait for approval. **Where that block and this section disagree, this
section governs** — the standing instruction above IS the explicit authority
that block asks for, given once so it does not have to be re-granted every
session. Everything else in that block still holds: an active "do not commit"
or "do not push" from the current user still wins, and a blocked push is still
reported with its exact command and error rather than worked around.

## Before Every Push

Run `just check` and `just test`. Do not push on failure. Work is not
complete until `git push` succeeds.

The gate proofs (`scripts/gate_probe.sh`) must be able to FAIL, and
`tests/test_gate_probe.py` is what holds them to it — a probe that cannot
distinguish a refusal from an unreachable store is not a gate.

## Beads: this repo is JSONL-only, no Dolt

**Do not run `bd init` here, and do not create a Dolt database.**

`.beads/issues.jsonl` **is** this repo's tracker — not an export of one. There
is no Dolt database and `bd` 1.2.1 states that "Dolt is the default and only
supported storage backend", so `bd` commands cannot read or write this tracker.
`bd init` would create a second identity alongside the `project_id` already in
`.beads/metadata.json` rather than adopting it.

Use the script:

```bash
scripts/beads-jsonl.py list [--status open]
scripts/beads-jsonl.py close   <id> --reason "..."
scripts/beads-jsonl.py note    <id> --text   "..."
scripts/beads-jsonl.py retitle <id> --title  "..."
```

It refuses any write that loses information — a record disappearing, a closed
issue reopening, notes or comments shrinking — because the file has no schema
enforcement and one bad write is a silent data loss committed as a normal diff.
`note` appends and never replaces. `retitle` writes the old title into the
notes before replacing it, which is what makes changing a title a non-lossy
write rather than an exception to the rule — hand-editing the `title` field
fixes the staleness and loses the record that it was ever wrong.

Commit these changes normally, with `chore(beads): … (jsonl export)` in the
subject, matching the convention already in this repo's history.

**On the managed block below.** It describes a Dolt-backed architecture and
calls hand-editing the JSONL an anti-pattern. That warning is correct *when a
Dolt store exists*, because then the JSONL is derived and the next export
reverts the edit. Here there is no store to derive from and nothing to revert
it. Where that block and this section disagree, this section governs.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:46cd31e7 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See <https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md> for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:

   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```

5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**

- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
