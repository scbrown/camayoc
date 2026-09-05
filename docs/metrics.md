# Metrics: functional counters without a server

camayoc is a CLI toolkit. Every entry point in the `justfile` is
`python3 scripts/<x>.py`, nothing listens, and the service name it would answer on
returns 404 because there is no service behind it. That is not a gap to be closed by adding a daemon —
it is what camayoc is.

So the work reports itself as it happens, to a Pushgateway. This is creel's
resolution to the same problem (`creel/docs/metrics.md`), and the shape
aegis-wou8k asks for.

## What is exported

| job | pushed | carries |
|---|---|---|
| `camayoc_producer` | **every run, unconditionally** | `camayoc_producer_run_timestamp_seconds`, `camayoc_producer_duration_seconds`, `camayoc_producer_exit_status` |
| `camayoc` | **only on a successful run** | the functional samples below |

| metric | moves when |
|---|---|
| `camayoc_ingest_commits_scanned{adapter}` | an ingest reads more history |
| `camayoc_ingest_items_linked{adapter}` | commits carry work-item ids |
| `camayoc_ingest_commits_unlinked{adapter}` | they do not — the denominator |
| `camayoc_ingest_edges_written{adapter}` | `modifies` edges are produced |

## Why two groups

A gap in a pushed series has two causes that are identical at the gateway:

    the producer DIED          vs      the producer RAN and had nothing to say

`camayoc_producer` going stale means nothing is running it. `camayoc` going stale
while the producer group stays fresh means camayoc ran and did no work. Collapse
them into one job and a pipeline can go quiet while everything reports healthy —
which is the `up=1`-while-dead class this exists to close, and which this fleet
has been bitten by (a watcher sat `up=1` for three hours observing a store nobody
was writing to).

## Why these counters and not `up`

`up 1` says a scrape succeeded. It is true of a tool that has done nothing for a
week. A **functional** counter moves when real work happens and stays put when it
does not, so the difference between two readings IS the work. The numbers above
are the ingest's own totals — the same ones it prints for a human — pushed
unchanged. Counting separately from the work lets the count drift from it, and
then the metric is measuring the metric.

## Running it

    CAMAYOC_METRICS_PUSHGATEWAY=http://[user:pass@]host[:port] \
      python3 scripts/ingest_git_provenance.py <repo> --project <prefix>

Unset the variable and nothing is pushed — the ingest is unaffected and says
`metrics: CAMAYOC_METRICS_PUSHGATEWAY is unset` on stderr. That direction is
deliberate: the ingest is the point and the metric is the observation of it, so a
missing gateway must never fail a run. It is never SILENT about it either, because
a metrics pipeline that quietly does nothing is the thing being guarded against.

The credential arrives at run time and is never written to the repo.

## Verified

2026-09-04, two runs against a live gateway, same command, different `--limit`:

| | run 1 | run 2 |
|---|---|---|
| `camayoc_ingest_commits_scanned` | 5 | **40** |
| `camayoc_ingest_items_linked` | 1 | **15** |
| `camayoc_ingest_edges_written` | 2 | **76** |

read back from Prometheus, not from the pushing script:

    camayoc_ingest_commits_scanned{adapter="git_provenance", job="camayoc"} => 40
    camayoc_producer_exit_status{adapter="git_provenance", job="camayoc_producer"} => 0

A moving value read from the scrape target is the claim; a push returning 200 is
not, and neither is a gauge that is always 0.
