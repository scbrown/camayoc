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
just test            # placeholder until slice 1
```

## Before Every Push

Run `just check`. Do not push on failure. Work is not complete until
`git push` succeeds.

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
