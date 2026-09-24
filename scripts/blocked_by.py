#!/usr/bin/env python3
"""Which work is blocked, which just became unblocked, and which we cannot tell (aegis-c0awwp).

`aegis:blockedOn` points a WorkItem at what it waits on: another WorkItem (a
tracker dependency) or a Blocker condition with a checkable resolution. Whether
a blocker still holds is evaluated HERE, at read time, and never stored:

  WorkItem target   resolved when its current status is closed: the latest
                    Observation's observedStatus is "closed", or the WorkItem
                    carries aegis:closedAt. No status at all -> unknown.
  Blocker, date     resolved from aegis:resolvesOn onward.
  Blocker, query    resolved when its aegis:resolutionQuery ASK answers true;
                    false -> unresolved; an error or a malformed answer -> unknown.
  Blocker, neither  unknown: a stated reason nobody can check.

A work item is UNBLOCKED when every target is resolved, BLOCKED when any is
unresolved, and UNKNOWN otherwise. "Could not tell" never rounds to
"unblocked": that is the one direction an event consumer would act on.
Items whose own current status is closed are left out.

Reads only, with SINGLE-PATTERN queries (any join, even a bound-subject one,
exceeded quipu's 10 s budget live), across
the default graph and the observed-records plane.

    python3 scripts/blocked_by.py            # JSON: one verdict per blocked item
    python3 scripts/blocked_by.py --item aegis-bgk9ho

Each verdict is the adapter record an emitter consumes (aegis-2qo001): item,
verdict (BLOCKED / UNBLOCKED / UNKNOWN), evidence (a stable digest of the
blocker targets and their states), assignee, and the blockers. This script
holds no memory between runs: transitions, baselines and delivery belong to
the emitter, which must treat UNKNOWN as "keep the last known verdict".
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import planes  # noqa: E402
from ingest_work_items import BASE_NS  # noqa: E402

CLIENT = "camayoc-ingress"
A = BASE_NS
TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RESOLVED, UNRESOLVED, UNKNOWN = "resolved", "unresolved", "unknown"
BLOCKED, UNBLOCKED = "BLOCKED", "UNBLOCKED"


def graphs() -> list[str | None]:
    """Where blocking facts live: the default graph, the observed records (the
    tracker projection) and the DECLARED plane (condition blockers someone
    declared). Not the inferred plane: an inferred blocker is quarantined
    guesswork and must not hold work up."""
    return [None, planes.plane_for("observed"), planes.plane_for("declared")]


def _iri(term: str) -> str:
    if term.startswith("aegis:"):
        return A + term[len("aegis:"):]
    return term


def _local(term: str) -> str:
    return _iri(term)[len(A):] if _iri(term).startswith(A) else term


def select(post, query: str) -> list[dict]:
    """Rows from every graph a record can live in, de-duplicated."""
    seen, rows = set(), []
    for graph in graphs():
        result = post("/query", {"query": query, **({"graph": graph} if graph else {})})
        if not isinstance(result.get("rows"), list) or result.get("truncated"):
            raise ValueError(f"query unproven in {graph or 'default'}: {query[:80]}")
        for row in result["rows"]:
            key = json.dumps(row, sort_keys=True)
            if key not in seen:
                seen.add(key)
                rows.append(row)
    return rows


def current_status(post, item: str) -> str | None:
    """The tracker status of a WorkItem from its LATEST Observation; "closed"
    also when the WorkItem carries aegis:closedAt; None when nothing says."""
    if select(post, f"SELECT ?c WHERE {{ <{A}{item}> <{A}closedAt> ?c }}"):
        return "closed"
    obs = latest_observation(post, item)
    if obs is None:
        return None
    rows = select(post, f"SELECT ?st WHERE {{ <{A}{obs}> <{A}observedStatus> ?st }}")
    if rows:
        return str(rows[0]["st"]).strip('"')
    # Older Observations carry status only inside their JSON snapshot.
    return snapshot(post, obs).get("status")


def snapshot(post, obs: str) -> dict:
    """The tracker record an Observation captured (its observedValue JSON), or {}."""
    rows = select(post, f"SELECT ?v WHERE {{ <{A}{obs}> <{A}observedValue> ?v }}")
    try:
        raw = str(rows[0]["v"])
        raw = raw[1:-1].encode().decode("unicode_escape") if raw.startswith('"') else raw
        value = json.loads(raw)
    except (IndexError, ValueError, AttributeError):
        return {}
    return value if isinstance(value, dict) else {}


def current_assignee(post, item: str) -> str | None:
    """Who the tracker says holds the item now (latest Observation), or None."""
    obs = latest_observation(post, item)
    return (snapshot(post, obs).get("assignee") or None) if obs else None


def evidence_id(item: str, judged: list[tuple[str, str]]) -> str:
    """A stable identity for the evidence behind one verdict: the item and each
    blocker target with its state. The same facts give the same id on every
    run, so a consumer can key an outbox on it; any blocker changing state
    changes it."""
    basis = json.dumps([item, sorted(judged)], separators=(",", ":"))
    return "sha256:" + hashlib.sha256(basis.encode()).hexdigest()


def latest_observation(post, item: str) -> str | None:
    """The WorkItem's Observation with the latest observedAt, or None."""
    # Two BOUND single-pattern queries, never a join: quipu plans even a
    # bound-subject two-pattern query from its unbound side and 408s it live.
    stamped = []
    for row in select(post, f"SELECT ?obs WHERE {{ <{A}{item}> <{A}observes> ?obs }}"):
        obs = _local(row["obs"])
        at = select(post, f"SELECT ?at WHERE {{ <{A}{obs}> <{A}observedAt> ?at }}")
        if at:
            stamped.append((str(at[0]["at"]), obs))
    return max(stamped)[1] if stamped else None


# ---- typed probes: FIXED code, parameters from the graph (aegis-c0awwp) ----
# Every probe returns True (resolved), False (unresolved) or None (could not
# tell). Parameters are re-validated here, independent of the SHACL shape, and
# nothing is ever run through a shell.
import re
import subprocess

_PR = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#([0-9]+)$")
_TOOL = re.compile(r"^[A-Za-z0-9_.-]+$")
_VER = re.compile(r"^[0-9]+(\.[0-9]+)*$")
_REPO = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)@([A-Za-z0-9_./-]+)$")


def _run(argv: list[str]) -> str | None:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def probe_pr_merged(ref: str):
    m = _PR.match(ref)
    if not m:
        return None
    out = _run(["gh", "api", f"repos/{m[1]}/{m[2]}/pulls/{m[3]}", "--jq", ".merged"])
    return None if out is None else out.strip() == "true"


def _version_tuple(text: str):
    m = re.search(r"([0-9]+(?:\.[0-9]+)+)", text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def probe_release_installed(tool: str, min_version: str):
    if not _TOOL.match(tool) or not _VER.match(min_version):
        return None
    have = _version_tuple(_run([tool, "--version"]) or "")
    if have is None:
        return None
    want = tuple(int(x) for x in min_version.split("."))
    width = max(len(have), len(want))
    return have + (0,) * (width - len(have)) >= want + (0,) * (width - len(want))


def probe_ci_green(ref: str):
    m = _REPO.match(ref)
    if not m:
        return None
    out = _run(["gh", "run", "list", "-R", f"{m[1]}/{m[2]}", "-b", m[3], "--status", "completed",
                "-L", "1", "--json", "conclusion", "--jq", ".[0].conclusion"])
    return None if not out or not out.strip() else out.strip() == "success"


PROBES = {"pr-merged": probe_pr_merged, "release-installed": probe_release_installed,
          "ci-green": probe_ci_green}


def _prop(post, target: str, name: str) -> str | None:
    rows = select(post, f"SELECT ?v WHERE {{ <{A}{target}> <{A}{name}> ?v }}")
    return str(rows[0]["v"]).split("^^")[0].strip('"') if rows else None


def blocker_state(post, target: str, today: dt.date, probes=None) -> tuple[str, str]:
    """(state, why) for one blockedOn target."""
    types = {_iri(r["t"]) for r in select(post, f"SELECT ?t WHERE {{ <{A}{target}> a ?t }}")}
    if A + "WorkItem" in types:
        status = current_status(post, target)
        if status is None:
            return UNKNOWN, f"{target}: no tracker status in the graph"
        return (RESOLVED if status == "closed" else UNRESOLVED), f"{target}: {status}"
    if A + "Blocker" in types:
        probes = PROBES if probes is None else probes
        kind = _prop(post, target, "blockerKind")
        if kind in ("pr-merged", "release-installed", "ci-green"):
            args = {"pr-merged": ["prRef"], "release-installed": ["tool", "minVersion"],
                    "ci-green": ["repoRef"]}[kind]
            values = [_prop(post, target, a) for a in args]
            if None in values:
                return UNKNOWN, f"{target}: {kind} blocker missing {args}"
            answer = probes[kind](*values)
            if answer is None:
                return UNKNOWN, f"{target}: {kind} {' '.join(values)} could not be checked"
            return (RESOLVED if answer else UNRESOLVED), f"{target}: {kind} {' '.join(values)} -> {answer}"
        dates = select(post, f"SELECT ?d WHERE {{ <{A}{target}> <{A}resolvesOn> ?d }}")
        asks = select(post, f"SELECT ?q WHERE {{ <{A}{target}> <{A}resolutionQuery> ?q }}")
        if dates:
            raw = str(dates[0]["d"]).split("^^")[0].strip('"')
            try:
                when = dt.date.fromisoformat(raw[:10])
            except ValueError:
                return UNKNOWN, f"{target}: unreadable resolvesOn {raw!r}"
            return (RESOLVED if today >= when else UNRESOLVED), f"{target}: date {when}"
        if asks:
            ask = str(asks[0]["q"]).strip('"').encode().decode("unicode_escape")
            try:
                answer = post("/query", {"query": ask})
            except Exception as error:  # an ASK we could not run is not an answer
                return UNKNOWN, f"{target}: resolution query failed ({type(error).__name__})"
            if isinstance(answer.get("result"), bool):
                return (RESOLVED if answer["result"] else UNRESOLVED), f"{target}: ASK {answer['result']}"
            return UNKNOWN, f"{target}: resolution query gave no boolean"
        return UNKNOWN, f"{target}: a Blocker with no checkable resolution"
    return UNKNOWN, f"{target}: not a WorkItem or Blocker in the graph"


def verdict(states: list[str]) -> str:
    if states and all(s == RESOLVED for s in states):
        return UNBLOCKED
    if any(s == UNRESOLVED for s in states):
        return BLOCKED
    return UNKNOWN.upper()


def evaluate(post, *, item: str | None = None, today: dt.date | None = None,
             probes=None) -> list[dict]:
    today = today or dt.date.today()
    scope = f"<{A}{item}>" if item else "?w"
    # Declared by an agent on the WorkItem ...
    edges = select(post, f"SELECT {'?w ' if not item else ''}?t WHERE {{ {scope} <{A}blockedOn> ?t }}")
    by_item: dict[str, list[str]] = {}
    for row in edges:
        w = item or _local(row["w"])
        by_item.setdefault(w, []).append(_local(row["t"]))
    # ... and projected from the tracker onto the LATEST Observation only, so a
    # removed dependency (absent from the newest Observation) no longer blocks.
    # Single-pattern or bound-subject queries only: the two-pattern join over
    # the whole store exceeded quipu's 10 s budget live (HTTP 408).
    if item:
        latest = latest_observation(post, item)
        if latest:
            for row in select(post, f"SELECT ?t WHERE {{ <{A}{latest}> <{A}observedBlockedOn> ?t }}"):
                by_item.setdefault(item, []).append(_local(row["t"]))
    else:
        owner: dict[str, str | None] = {}
        for row in select(post, f"SELECT ?obs ?t WHERE {{ ?obs <{A}observedBlockedOn> ?t }}"):
            obs = _local(row["obs"])
            if obs not in owner:
                found = select(post, f"SELECT ?w WHERE {{ ?w <{A}observes> <{A}{obs}> }}")
                owner[obs] = _local(found[0]["w"]) if found else None
            w = owner[obs]
            if w and latest_observation(post, w) == obs:
                by_item.setdefault(w, []).append(_local(row["t"]))
    out = []
    for w, targets in sorted(by_item.items()):
        if current_status(post, w) == "closed":
            continue
        names = sorted(set(targets))
        judged = [blocker_state(post, t, today, probes) for t in names]
        out.append({"item": w, "verdict": verdict([s for s, _ in judged]),
                    "evidence": evidence_id(w, [(t, s) for t, (s, _) in zip(names, judged)]),
                    "assignee": current_assignee(post, w),
                    "blockers": [{"target": t, "state": s, "why": why}
                                 for t, (s, why) in zip(names, judged)]})
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--item", help="one work item id (e.g. aegis-bgk9ho)")
    args = parser.parse_args(argv)
    post = lambda endpoint, body: planes._post(endpoint, body, client=CLIENT)  # noqa: E731
    print(json.dumps(evaluate(post, item=args.item), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
