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
requests: one bounded VALUES SELECT preserving an asserted-only FILTER, one
snapshot write, one read-back. Starts are spaced at least one second apart.
The initial schedule must be no more frequent than once per minute. Every cost
request carries `X-Quipu-Client: camayoc-cost`; other plane helper callers use
`camayoc-ingress` or `camayoc-planes`. Raising these limits requires a reviewed load budget.

Read-back checks the sampled request's exact attribution set as well as its total,
so a corrected focus retaining an old WorkItem edge leaves the pending marker
unresolved instead of reporting success. This samples one request, not the entire
snapshot; rollout acceptance must include a deliberately re-attributed request.

## Resilience gate and recovery

The caller label is required: cost sends `camayoc-cost`, tracker ingress sends
`camayoc-ingress`, and plane/window administration sends `camayoc-planes`.
Preflight uses one bounded VALUES SELECT and asserted-type FILTER. A partial
result names missing IDs. Zero rows trigger one single-item control and return
INDETERMINATE, never an instruction to repeat ingress. A 408 or transport timeout
aborts before writing.

Every publication attempt writes a sibling `.receipt.json` and `.prom` next to
its state, and emits the receipt to stderr. Receipts distinguish OK, UNKNOWN,
STALLED and OPERATOR_ACTION, list observed items per changed snapshot, and name
read-back as a last-record sample. The scheduled wrapper must surface nonzero
exit to the coordinator and retain stderr; an unmonitored cron logfile is not
an acceptable schedule. The status metric file is available for a textfile
collector, but its existence alone does not establish a scrape.

Calls are spaced one second apart and capped at three per attempt. Persisted
receipts enforce at least sixty seconds between network-bearing attempts. A
write taking over ten seconds, or summed request wall time over fifteen seconds,
sets a fifteen-minute cooldown. Request wall time is a conservative budget
proxy; it is not measured server lock occupancy. Cooldown survives restart.

A pending marker means **the write may have landed**. It contains the exact
canonical JSON body sent on the wire. Automatic runs preserve it and report
STALLED; they never retry that write. Franklin (or the coordinator's explicitly
assigned recovery operator) owns reconciliation:

1. Stop the scheduled cost publisher while retaining the marker, state, receipt
   and source inputs. Record their SHA-256 values on the task.
2. Inspect the stored Turtle for the snapshot identity and request facts. Query
   one previously known canonical WorkItem using the asserted-type FILTER as a
   control. If the control fails or reads time out, leave the marker in place.
3. Read the marked snapshot's expected request totals and attribution sets,
   including the corrected assignment if this was a correction. Repeat after a
   gap. An extra attribution edge is a mismatch, not success. A sample is only a
   sample; record precisely which requests were checked.
4. If reads prove the expected snapshot, write its SHA-256 (of the marker bytes)
   under the marker's `snapshot` key in the local state atomically, then remove
   the marker. This is the same cursor/digest format as normal publication.
   Retain the evidence on the task before resuming.
5. If two controlled reads show absence, a recovery operator may replay the
   **unchanged marker bytes** to `/knot` with `X-Quipu-Client: camayoc-cost` and
   write authorization. Respect the recorded cooldown and at most three
   requests per minute. Do not regenerate it from a growing transcript or edit
   its wording. Acceptance still requires the controlled read-back in step 3;
   another timeout leaves the same marker and the schedule stopped.

Narrow sources when a snapshot exceeds eight items, one thousand requests or
four MiB; do not silently drop records to fit. Report the first scheduled run's
actual items-per-snapshot distribution before asking to enlarge that budget.
