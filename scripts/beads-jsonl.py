#!/usr/bin/env python3
"""Update `.beads/issues.jsonl` directly — this repo has no Dolt database.

## Why this exists

`bd` 1.2.1 says it plainly: "Dolt is the default and only supported storage
backend." This repository has `.beads/issues.jsonl` and no Dolt database, and
`bd init` would create one — minting a second identity alongside the
`project_id` already in `.beads/metadata.json` rather than adopting it.

So for this repo the JSONL **is** the tracker, not an export of one. That is a
deliberate choice (see CLAUDE.md), and it matches what the history already does:
commits titled `chore(beads): … (jsonl export)` have been editing this file
directly since before the Dolt backend was absent.

The managed beads block calls hand-editing the JSONL an anti-pattern. It is —
*when a Dolt store exists*, because then the edit is to a derived artifact and
the next export silently reverts it. With no store there is nothing to derive
from and nothing to revert it, and the warning does not apply.

## Why a script rather than an editor

Every write here is one careless keystroke away from deleting a record, and the
file is one line per issue with no schema enforcement. So this refuses to write
anything that loses information:

  * a record may never disappear
  * notes and comments may only grow (`--notes` on real `bd` REPLACES, which
    destroyed a 1510-char audit earlier in this project's history)
  * a closed issue may not silently reopen
  * a title may only be replaced by `retitle`, which writes the old one into
    the notes first — see below

## Why `retitle` and not an editor keystroke

A title is the only field a reader sees in `list`, and it is the field most
likely to go stale: `camayoc-0d3` read "blocked on quipu's refusal log" for
three days after that block lifted. Hand-editing the `title` field would fix
the staleness and lose the record that it was ever wrong, which is exactly
the lossy write this script exists to refuse — so the fix has to be a verb
that cannot be lossy. `retitle` appends the previous title to the notes
before replacing it. That is what makes the write safe under this script's
own rules rather than an exception carved out of them: nothing is lost, the
correction is dated, and the notes still only grow.

Field names and shapes match what real `bd` emits, taken from a Dolt-backed
sibling repo, so a future import sees nothing unusual.

## Usage

    scripts/beads-jsonl.py create "Title" [--description ...] [--priority 3] [--type task] [--label pitch]
    scripts/beads-jsonl.py close   <id> --reason "..."
    scripts/beads-jsonl.py note    <id> --text   "..."
    scripts/beads-jsonl.py retitle <id> --title  "..."
    scripts/beads-jsonl.py list [--status open]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
JSONL = REPO / ".beads" / "issues.jsonl"

#: `bd` writes compact JSON, one issue per line. Matching it keeps diffs to the
#: lines actually changed instead of reformatting the whole file.
SEPARATORS = (",", ":")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load() -> list[dict]:
    return [json.loads(line) for line in JSONL.read_text().splitlines() if line.strip()]


def save(records: list[dict], before: list[dict]) -> None:
    """Write, but only if nothing was lost."""
    old = {r["id"]: r for r in before}
    new = {r["id"]: r for r in records}

    for lost in sorted(set(old) - set(new)):
        raise SystemExit(f"refusing to write: {lost} would disappear")

    for issue_id in sorted(set(old) & set(new)):
        a, b = old[issue_id], new[issue_id]
        if a.get("status") == "closed" and b.get("status") != "closed":
            raise SystemExit(f"refusing to write: {issue_id} would reopen; that is a human action")
        if len(b.get("notes") or "") < len(a.get("notes") or ""):
            raise SystemExit(f"refusing to write: {issue_id} notes would shrink")
        if len(b.get("comments") or []) < len(a.get("comments") or []):
            raise SystemExit(f"refusing to write: {issue_id} comments would shrink")

    JSONL.write_text(
        "".join(json.dumps(r, separators=SEPARATORS, ensure_ascii=False) + "\n" for r in records)
    )


def append_note(record: dict, text: str) -> None:
    """Append to an issue's notes. Never replaces — that is the whole guard.

    Shared by `note` and `retitle` so there is exactly one way notes are
    written and a second verb cannot quietly grow a second policy.
    """
    existing = record.get("notes") or ""
    record["notes"] = (existing + "\n\n" + text).strip() if existing else text


def find(records: list[dict], issue_id: str) -> dict:
    for record in records:
        if record.get("id") == issue_id:
            return record
    raise SystemExit(f"no such issue: {issue_id}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_close = sub.add_parser("close", help="close an issue with a reason")
    p_close.add_argument("id")
    p_close.add_argument("--reason", required=True)

    p_note = sub.add_parser("note", help="append to an issue's notes")
    p_note.add_argument("id")
    p_note.add_argument("--text", required=True)

    p_retitle = sub.add_parser(
        "retitle", help="replace a title, preserving the old one in the notes"
    )
    p_retitle.add_argument("id")
    p_retitle.add_argument("--title", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--status")

    p_create = sub.add_parser("create", help="file a new issue")
    p_create.add_argument("title")
    p_create.add_argument("--description", default="")
    p_create.add_argument("--priority", type=int, default=3)
    p_create.add_argument("--type", dest="issue_type", default="task")
    p_create.add_argument("--label", action="append", default=[],
                          help="repeatable; e.g. --label pitch")

    args = ap.parse_args()
    records = load()
    before = json.loads(json.dumps(records))  # deep copy for the loss check

    if args.cmd == "list":
        for record in records:
            if args.status and record.get("status") != args.status:
                continue
            print(f"{record['id']:<14} {record.get('status', '?'):<11} {record.get('title', '')}")
        return 0

    stamp = now()

    if args.cmd == "create":
        # Suffix from a hash of title+time, collision-checked — matches the
        # {prefix}-{short} shape of every existing id. Creation adds a record
        # and can never lose one, so the save() guard passes trivially.
        import hashlib

        prefix = records[0]["id"].rsplit("-", 1)[0] if records else "issue"
        existing = {r["id"] for r in records}
        digest = hashlib.sha256((args.title + stamp).encode()).hexdigest()
        for i in range(0, len(digest) - 3):
            candidate = f"{prefix}-{digest[i:i + 3]}"
            if candidate not in existing:
                break
        else:
            raise SystemExit("could not derive a fresh id")
        record = {
            "id": candidate,
            "title": args.title,
            "description": args.description,
            "status": "open",
            "priority": args.priority,
            "issue_type": args.issue_type,
            "owner": "noreply@anthropic.com",
            "created_at": stamp,
            "created_by": "Claude",
            "updated_at": stamp,
        }
        if args.label:
            record["labels"] = sorted(args.label)
        records.append(record)
        save(records, before)
        print(f"created {candidate}")
        return 0

    record = find(records, args.id)

    if args.cmd == "close":
        if record.get("status") == "closed":
            print(f"{args.id} is already closed", file=sys.stderr)
            return 1
        record["status"] = "closed"
        record["closed_at"] = stamp
        record["close_reason"] = args.reason
        record["updated_at"] = stamp
        print(f"closed {args.id}")

    elif args.cmd == "note":
        # Append, never replace. The whole point of the guard above.
        append_note(record, args.text)
        record["updated_at"] = stamp
        print(f"noted {args.id}")

    elif args.cmd == "retitle":
        new_title = args.title.strip()
        old_title = record.get("title") or ""
        if not new_title:
            print("refusing to write: a blank title loses the old one for nothing",
                  file=sys.stderr)
            return 1
        if new_title == old_title:
            # Not an error worth a traceback, but not a success either: a
            # no-op retitle would append a note recording that nothing
            # changed, which is noise dressed as provenance.
            print(f"{args.id} already has that title", file=sys.stderr)
            return 1
        # The old title goes into the notes BEFORE the field is replaced.
        # This ordering is the safety property, not a formality: the append
        # is what makes a title change a non-lossy write, and save()'s
        # notes-may-only-grow guard is what proves it happened.
        append_note(
            record,
            f"{stamp} retitled. PREVIOUS TITLE: {old_title!r}. "
            f"The old title is kept here because a corrected title that "
            f"erases the wrong one hides how long the record misled.",
        )
        record["title"] = new_title
        record["updated_at"] = stamp
        print(f"retitled {args.id}")

    save(records, before)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
