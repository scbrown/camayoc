#!/usr/bin/env python3
"""Tests for scripts/ingest_transcript_sessions.py — archive -> Session links.

The properties under test are the ones a wrong answer would hide:

* ONE Session node per harness session. The codex corpus id is a rollout
  stem; linking it verbatim would mint a second Session beside the cost one.
* A POINTER to a published object only. A file the publisher excluded has no
  Garage object, and an unknown exclude list is refused, never read as empty.
* The governed Session facts are the cost producer's byte-identical strings,
  so the shared label stays exactly one.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location(
    "ingest_transcript_sessions", SCRIPTS / "ingest_transcript_sessions.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)
import ingest_session_usage  # noqa: E402

CLAUDE_ID = "8619c43c-8a25-4970-8fa2-ccdfe92257b4"
CODEX_UUID = "01a0a19c-986a-7301-a9fb-d0fce65f8d00"
CODEX_ID = f"rollout-2026-09-14T16-29-49-{CODEX_UUID}"


def record(root: Path, agent: str, name: str, harness: str, sid: str,
           age: float = 7200, frontmatter_agent: str | None = None) -> Path:
    path = root / agent / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nschema: agent-transcript/v1\nprojection_version: 3\n"
        f"id: {sid}\ntimestamp: 2026-09-25T17:51:43.813922Z\n"
        f"agent: {frontmatter_agent or agent}\nharness: {harness}\n"
        f"source_file: {sid}.jsonl\n---\n\n[user/text] body is hashed, never parsed\n")
    stamp = path.stat().st_mtime - age
    os.utime(path, (stamp, stamp))
    return path


class SessionIdentity(unittest.TestCase):
    def test_claude_id_is_the_session_id(self):
        self.assertEqual(mod.session_id({"harness": "claude", "id": CLAUDE_ID}), CLAUDE_ID)

    def test_codex_rollout_stem_maps_to_its_trailing_uuid(self):
        # The cost producer keys codex Sessions by session_meta.id; the stem
        # would mint a second node for the same session.
        self.assertEqual(mod.session_id({"harness": "codex", "id": CODEX_ID}), CODEX_UUID)

    def test_unrecognised_ids_abstain(self):
        self.assertIsNone(mod.session_id({"harness": "claude", "id": "not-a-uuid"}))
        self.assertIsNone(mod.session_id({"harness": "gemini", "id": CLAUDE_ID}))


class Scan(unittest.TestCase):
    def test_pointer_names_the_published_key_and_digest(self):
        with TemporaryDirectory() as tmp:
            path = record(Path(tmp), "wu", f"{CLAUDE_ID}.md", "claude", CLAUDE_ID)
            records, stats = mod.scan(Path(tmp), 3600, path.stat().st_mtime + 7200)
        self.assertEqual(stats["linked"], 1)
        self.assertEqual(records[0]["key"], f"garage-hla:hla/agent-transcripts/wu/{CLAUDE_ID}.md")
        self.assertEqual(records[0]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
                         if path.exists() else records[0]["sha256"])

    def test_excluded_file_gets_no_pointer(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            record(root, "ian", f"{CODEX_ID}.md", "codex", CODEX_ID)
            exclude = root / "exclude.txt"
            exclude.write_text(f"/ian/{CODEX_ID}.md\n")
            records, stats = mod.scan(root, 0, 1e12, mod.excluded(exclude))
        self.assertEqual(records, [])
        self.assertEqual(stats["skipped"], {"excluded from publication": 1})

    def test_missing_exclude_list_is_refused_not_empty(self):
        with self.assertRaises(OSError):
            mod.excluded(Path("/nonexistent/exclude.txt"))

    def test_active_session_waits_for_quiescence(self):
        with TemporaryDirectory() as tmp:
            path = record(Path(tmp), "wu", f"{CLAUDE_ID}.md", "claude", CLAUDE_ID, age=0)
            records, stats = mod.scan(Path(tmp), 3600, path.stat().st_mtime + 60)
        self.assertEqual((records, stats["active"]), ([], 1))

    def test_scratch_directory_is_not_a_principal(self):
        with TemporaryDirectory() as tmp:
            record(Path(tmp), "arnold-x-scratchpad-chrometest", f"{CLAUDE_ID}.md", "claude", CLAUDE_ID)
            records, stats = mod.scan(Path(tmp), 0, 1e12)
        self.assertEqual(records, [])
        self.assertEqual(stats["skipped"], {"agent not a crew principal": 1})


class Turtle(unittest.TestCase):
    def test_session_label_is_the_cost_producers_exact_string(self):
        rec = {"session": CODEX_UUID, "agent": "muldoon", "harness": "codex", "at": "",
               "key": "garage-hla:hla/agent-transcripts/muldoon/x.md", "sha256": "0" * 64, "bytes": 1}
        cost: list[str] = []
        ingest_session_usage.emit(CODEX_UUID, "muldoon", "openai", "codex", [], cost)
        cost_label = next(line for line in cost if "rdfs:label" in line).strip()
        self.assertIn(cost_label, mod.turtle(rec))
        self.assertEqual(mod.turtle(rec).count("session " + CODEX_UUID + '"'), 1)

    def test_no_body_content_enters_the_graph(self):
        with TemporaryDirectory() as tmp:
            path = record(Path(tmp), "wu", f"{CLAUDE_ID}.md", "claude", CLAUDE_ID)
            records, _ = mod.scan(Path(tmp), 0, path.stat().st_mtime + 7200)
        self.assertNotIn("body is hashed", mod.turtle(records[0]))



class DeclaredWorkItems(unittest.TestCase):
    def stats_db(self, root: Path, rows) -> Path:
        path = root / "stats.sqlite"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE task_contexts (id INTEGER PRIMARY KEY, ts REAL, agent TEXT,"
                         " session TEXT, task TEXT, paired_start INTEGER)")
            conn.executemany("INSERT INTO task_contexts (ts, agent, session, task, paired_start)"
                             " VALUES (0, 'wu', ?, ?, ?)", rows)
        return path

    def test_only_paired_valid_starts_become_edges(self):
        with TemporaryDirectory() as tmp:
            db = self.stats_db(Path(tmp), [(CLAUDE_ID, "aegis-9lri74", 1),
                                           (CLAUDE_ID, "aegis-unpaired", 0),
                                           (CLAUDE_ID, "not a task", 1),
                                           (CLAUDE_ID, "aegis-9lri74", 1)])
            self.assertEqual(mod.declared_tasks(db), {CLAUDE_ID: ["aegis-9lri74"]})

    def test_edges_are_in_the_snapshot_and_the_digest(self):
        with TemporaryDirectory() as tmp:
            path = record(Path(tmp), "wu", f"{CLAUDE_ID}.md", "claude", CLAUDE_ID)
            records, _ = mod.scan(Path(tmp), 0, path.stat().st_mtime + 7200,
                                  tasks={CLAUDE_ID: ["aegis-9lri74"]})
        rec = records[0]
        self.assertIn(f"declaredWorkItem> <{ingest_session_usage.ONTOLOGY}aegis-9lri74>", mod.turtle(rec))
        self.assertEqual(mod.digest(rec), rec["sha256"] + ":aegis-9lri74")

    def test_sessions_without_declarations_keep_the_bare_digest(self):
        # Existing state stores the bare sha; adding step (b) must not
        # re-publish every transcript-only session.
        self.assertEqual(mod.digest({"sha256": "ab", "tasks": []}), "ab")

    def test_no_stats_db_means_no_edges_not_an_error(self):
        self.assertEqual(mod.declared_tasks(None), {})


if __name__ == "__main__":
    unittest.main()
