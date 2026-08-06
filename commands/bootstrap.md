---
description: Bootstrap governed memory from nothing — install/start quipu if needed, write the gate config, load the camayoc ontology + shapes, prove the SHACL gate, then offer the optional stack (bobbin, hank, shantytown).
---

## Step 1 — core: quipu + ontology + gate

Run the camayoc bootstrap script and report its output faithfully:

```!
${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap.sh
```

The script is idempotent and does, in order, only what is missing: reach the
quipu at $QUIPU_SERVER (default localhost:3030) — or install one (write
.bobbin/config.toml with validate_on_write = true, download the latest quipu
release binary — sha256-checked — or cargo-install it, start it against
.quipu/store.db, gitignore .quipu/); load ontology/core.ttl and
shapes/core.shapes.ttl; then PROVE the gate by sending an untagged probe the
store must refuse.

If it reports the gate NOT PROVEN or nothing could be installed, relay that
verbatim and STOP — do not ingest into an ungated store, do not offer step 2,
and do not treat "could not reach quipu" as "no knowledge exists".

## Step 2 — offer the optional stack (only after step 1 succeeds)

Ask the user (use the question tool, multi-select) which optional components
to set up, briefly describing each:

- **bobbin** — semantic code search + task-aware context bundles, exposed to
  agents over MCP (`cargo install bobbin`, indexes this project).
- **hank** — structural code facts: defs/refs, call graph, blast radius,
  over MCP (pre-release; installs from git, can take minutes).
- **shantytown (st)** — a crew harness for running multiple coding agents
  (Python + tmux; its own `st init` stays interactive and is left to the
  user).

For each selected component run, one at a time, reporting output faithfully:

```text
${CLAUDE_PLUGIN_ROOT}/scripts/setup_component.sh <bobbin|hank|st>
```

Cargo installs take minutes — say so up front rather than looking hung. A
component that fails to install is reported and skipped, never retried in a
loop, and never blocks the others. After st installs, remind the user to run
`st init` themselves — it asks five questions and shows every path before
writing; the script deliberately does not answer them on the user's behalf.

## After

Governed memory is ready: query before re-deciding, record decisions at the
moment they happen, tag sourceKind honestly (observed | declared |
inferred). If MCP servers were added to .mcp.json, mention that Claude Code
picks them up on next session start (or /mcp reconnect).

For installs that skipped the plugin, `bootstrap.sh --with-claude-hooks`
additionally merges the SessionStart status hook into the project's
.claude/settings.json (non-clobbering, idempotent).
