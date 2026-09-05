#!/usr/bin/env python3
"""Functional counters for camayoc, pushed — because camayoc has no server.

WHY A PUSHGATEWAY AND NOT A `/metrics` ENDPOINT. camayoc is a CLI toolkit, not a
service: every entry point in the justfile is `python3 scripts/<x>.py`, there is
no process to scrape, and its would-be service name 404s because nothing serves
it. Giving it
a server to hold a metrics endpoint would invent a daemon nobody asked for and
that nothing else in the stack needs. So the work reports itself as it happens,
which is creel's resolution to the same problem (creel/docs/metrics.md) and the
shape aegis-wou8k asks for.

WHAT MAKES A COUNTER FUNCTIONAL. `up 1` is not evidence that anything worked —
that is the failure class the parent bead exists to close, and this fleet has
been bitten by it repeatedly (a reactor sat `up=1` for three hours watching a
store nobody was writing to). A functional counter MOVES when the tool does real
work and stays put when it does not, so the difference between two readings is
the work. Here that is commits scanned, items linked, edges written — numbers
that come from the ingest's own totals rather than from the fact that it ran.

TWO GROUPS, and this is the load-bearing part rather than tidiness (creel's
metrics.md argues it first and the argument transfers exactly). A gap in a pushed
series has two causes that look identical at the gateway:

    the producer DIED                 vs   the producer RAN and had nothing to say

    job=camayoc_producer   pushed EVERY run, unconditionally. Carries the exit
                           status, the run timestamp and the duration. Its
                           staleness means the producer stopped running.
    job=camayoc            pushed ONLY on a successful run, carrying the
                           functional samples themselves. Its staleness with a
                           fresh producer group means camayoc ran and did no work.

Collapsing them is how a metric goes quiet while everything reports healthy.

FAILS OPEN, LOUDLY. An unreachable gateway, a missing credential or an unset
environment variable must NEVER fail an ingest — the ingest is the point and the
metric is the observation. So every path here returns a status and prints why,
and no caller is expected to care. But it is never SILENT: a push that did not
happen says so on stderr, because a metrics pipeline that quietly does nothing is
the thing being guarded against.

CONFIGURATION. `CAMAYOC_METRICS_PUSHGATEWAY` holds the whole address including
any credential, the same contract creel uses:

    CAMAYOC_METRICS_PUSHGATEWAY=http://[user:pass@]host[:port]

The credential arrives at run time and is never written to the repo: the variable
carries it, an operator's secret store supplies it, and nothing here logs it.
"""
from __future__ import annotations

import base64
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ENV = "CAMAYOC_METRICS_PUSHGATEWAY"
JOB_SAMPLES = "camayoc"
JOB_PRODUCER = "camayoc_producer"
TIMEOUT_S = 10


def _escape(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def exposition(metrics: list[tuple[str, dict, float]]) -> str:
    """Prometheus text exposition for (name, labels, value) triples.

    Deliberately hand-rolled rather than taking a prometheus_client dependency:
    camayoc's scripts run from a bare `python3` with no virtualenv, and a metrics
    helper that makes an ingest un-runnable on a fresh checkout has traded the
    thing for the observation of it.
    """
    lines = []
    for name, labels, value in metrics:
        if labels:
            rendered = ",".join(f'{k}="{_escape(v)}"' for k, v in sorted(labels.items()))
            lines.append(f"{name}{{{rendered}}} {value}")
        else:
            lines.append(f"{name} {value}")
    return "\n".join(lines) + "\n"


def push(job: str, body: str, url: str | None = None,
         grouping: dict[str, str] | None = None) -> tuple[bool, str]:
    """Send exposition to the gateway. -> (ok, why). NEVER raises.

    `grouping` becomes extra /label/value segments in the URL — the pushgateway
    GROUPING KEY — and this is not a stylistic choice.

    A pushgateway group is REPLACED WHOLESALE by each push to the same grouping
    key. So a distinguishing label carried in the BODY does not partition
    anything: the second adapter to push destroys the first adapter's series and
    the gateway reports success to both. Measured live by gennaro on the sibling
    desire-path collector, which I wrote the same way on the same night: pushing
    `source=claude-code` then `source=codex` left only codex, of four plugins,
    and the surviving total was 4 where the truth was 2214. The old number was
    WRONG, not stale — which is the dangerous kind, because a plausible small
    number invites no investigation.

    Anything that must produce its own independent series belongs here, in the
    key. Anything that merely annotates one series belongs in the body.
    """
    url = (url if url is not None else os.environ.get(ENV, "")).strip()
    if not url:
        return False, f"{ENV} is unset — nothing pushed (set it to enable metrics)"
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError as e:
        return False, f"{ENV} is not a URL ({e}) — nothing pushed"
    if not parsed.hostname:
        return False, f"{ENV} names no host — nothing pushed"

    netloc = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
    path = parsed.path.rstrip("/") + f"/metrics/job/{urllib.parse.quote(job, safe='')}"
    for k, v in (grouping or {}).items():
        path += f"/{urllib.parse.quote(k, safe='')}/{urllib.parse.quote(str(v), safe='')}"
    target = urllib.parse.urlunparse((parsed.scheme or "http", netloc, path, "", "", ""))

    req = urllib.request.Request(target, data=body.encode(), method="POST")
    req.add_header("Content-Type", "text/plain; version=0.0.4")
    if parsed.username:
        cred = f"{parsed.username}:{parsed.password or ''}"
        req.add_header("Authorization",
                       "Basic " + base64.b64encode(cred.encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return True, f"pushed job={job} ({r.status})"
    except urllib.error.HTTPError as e:
        # The gateway ANSWERED and refused: auth, or a malformed body. Naming the
        # status is the difference between "fix your credential" and "fix your
        # exposition", and a bare "push failed" sends the reader to neither.
        return False, f"gateway refused job={job}: HTTP {e.code} {e.reason}"
    except Exception as e:                                   # noqa: BLE001
        return False, f"gateway unreachable for job={job}: {e}"


def report(adapter: str, samples: dict[str, float], *, started: float,
           status: int = 0, instance: str | None = None) -> None:
    """Push one run's functional samples and its producer liveness. Never raises.

    `samples` are the adapter's OWN totals — the numbers it already computed to
    report to a human. Reusing them is deliberate: a counter derived separately
    from the work can drift from it, and then the metric is measuring the metric.
    """
    # adapter (and instance) PARTITION the series, so they are grouping-key
    # segments, not body labels. As body labels every adapter would push into one
    # group and each push would wipe the previous adapter's numbers — see push().
    # Today only one adapter calls this, so the defect is latent rather than
    # live; it would first appear as the SECOND adapter silently deleting the
    # first, which is exactly how it is hardest to notice.
    grouping = {"adapter": adapter}
    if instance:
        grouping["instance"] = instance
    labels: dict[str, str] = {}
    now = time.time()

    # The producer group goes out on EVERY run, including a failed one — its
    # whole job is to distinguish "did not run" from "ran and found nothing".
    ok, why = push(JOB_PRODUCER, exposition([
        ("camayoc_producer_run_timestamp_seconds", labels, round(now, 3)),
        ("camayoc_producer_duration_seconds", labels, round(now - started, 3)),
        ("camayoc_producer_exit_status", labels, status),
    ]), grouping=grouping)
    print(f"metrics: {why}", file=sys.stderr)

    if status != 0:
        # Samples from a failed run would be a partial count presented as a
        # measurement. The producer group already said the run failed.
        print("metrics: run failed — functional samples NOT pushed "
              "(the producer group carries the failure)", file=sys.stderr)
        return
    ok, why = push(JOB_SAMPLES, exposition(
        [(name, labels, value) for name, value in sorted(samples.items())]),
        grouping=grouping)
    print(f"metrics: {why}", file=sys.stderr)
