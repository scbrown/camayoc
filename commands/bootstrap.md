---
description: Bootstrap governed memory — load the camayoc ontology + shapes into the quipu store and prove the SHACL gate is live.
---

Run the camayoc bootstrap script and report its output faithfully:

```!
${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap.sh
```

If it reports the gate NOT PROVEN or quipu unreachable, relay that verbatim
and stop — do not ingest into an ungated store, and do not treat
"could not reach quipu" as "no knowledge exists". If it succeeds, governed
memory is ready: query before re-deciding, record decisions at the moment
they happen, tag sourceKind honestly (observed | declared | inferred).
