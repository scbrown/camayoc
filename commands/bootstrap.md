---
description: Bootstrap governed memory from nothing — install/start quipu if needed, write the gate config, load the camayoc ontology + shapes, and prove the SHACL gate is live.
---

Run the camayoc bootstrap script and report its output faithfully:

```!
${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap.sh
```

The script is idempotent and does, in order, only what is missing: reach the
quipu at $QUIPU_SERVER (default localhost:3030) — or install one (write
.bobbin/config.toml with validate_on_write = true, download the latest quipu
release binary for this platform or cargo-install it, start it against
.quipu/store.db, gitignore .quipu/); load ontology/core.ttl and
shapes/core.shapes.ttl; then PROVE the gate by sending an untagged probe the
store must refuse.

If it reports the gate NOT PROVEN or nothing could be installed, relay that
verbatim and stop — do not ingest into an ungated store, and do not treat
"could not reach quipu" as "no knowledge exists". If it succeeds, governed
memory is ready: query before re-deciding, record decisions at the moment
they happen, tag sourceKind honestly (observed | declared | inferred).

For installs that skipped the plugin, `--with-claude-hooks` additionally
merges the SessionStart status hook into the project's
.claude/settings.json (non-clobbering, idempotent).
