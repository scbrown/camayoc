# Request cost attribution

**Status: implemented locally; scheduled delivery and live acceptance pending.**

Q16 now asks for per-work model and disjoint token counts. Camayoc owns the
arithmetic. Shantytown supplies versioned focus intervals containing the rig,
bead, agent, session, start, end and boundary evidence. Neither global assignment
nor a session-wide bead guess is allocation evidence.

`retrieve_metric.py` accepts the `session_usage` system and `work_cost` query,
with `params.sources` (path, harness, agent) and `params.bindings`. It parses
Claude request identities and Codex response identities, including compaction.
Identical repeated rows count once; conflicting rows abstain. Missing models or
counts stay unknown. Reasoning and cache TTL details are retained as metadata.

Intervals are half-open. A request matching no interval or conflicting intervals
remains unattributed. Repeated identical bindings do not double-charge a request.
Totals describe the supplied sources, never an unmeasured lifetime cost.

`publish_work_cost.py` uses that same parser and replaces only its own session
snapshot in the observed plane. Request IRIs retain the existing usage producer's
identity. The existing `inSession` and `attributedTo` edges join requests to
sessions and canonical WorkItems. The tracker producer must have populated those
WorkItems first. No separate bead twins or new session predicate are introduced.

The optional breakdown shapes travel with the producer's write. They extend
UsageRecord; no new entity class is needed. Reads store no metric sample. USD is
not estimated without a governed applicable price record.

Rollback disables the scheduled projection and retains evidence. It does not
rewrite tracker close reasons or silently delete prior cost observations.

## First-rollout load budget

Each invocation permits at most one changed session snapshot, eight distinct
attributed WorkItems, 1,000 requests and 4 MiB of serialized snapshot body.
Exceeding any limit refuses before network access; partition backfills explicitly.
Unchanged snapshots issue no request. The changed snapshot makes at most three
requests: one bounded conjunctive ASK preserving asserted-only FILTERs, one
snapshot write, one read-back. Starts are spaced at least one second apart.
The initial schedule must be no more frequent than once per minute. Every cost
request carries `X-Quipu-Client: camayoc-cost`; other plane helper callers use
`ingest-cron`. Raising these limits requires a reviewed load budget.

Read-back checks the sampled request's exact attribution set as well as its total,
so a corrected focus retaining an old WorkItem edge leaves the pending marker
unresolved instead of reporting success. This samples one request, not the entire
snapshot; rollout acceptance must include a deliberately re-attributed request.
