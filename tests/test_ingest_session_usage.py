#!/usr/bin/env python3
"""Tests for scripts/ingest_session_usage.py — harness logs → the §D vocabulary.

The property under test is that the COUNT IS RIGHT, and specifically that it
is not inflated. Every §D question (Q16–Q21) is an arithmetic claim about real
spend, and the failure mode this parser was built around is not a crash: it is
a plausible number that is 2.5x too large, because the claude harness repeats
one request's `usage` object across every content block of the turn. A cost
ingest that overcounts is worse than none, since a dashboard built on it looks
authoritative.

The second property is ABSTENTION, on the same reasoning as the git ingest: a
record that cannot be counted honestly is dropped and said out loud, so the
total is a visible floor rather than a silent estimate.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_spec = importlib.util.spec_from_file_location(
    "ingest_session_usage",
    Path(__file__).resolve().parent.parent / "scripts" / "ingest_session_usage.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def usage(inp=10, out=5, creation=100, read=1000):
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_creation_input_tokens": creation,
        "cache_read_input_tokens": read,
    }


def entry(request_id, stamp="2026-08-24T22:46:31.805Z", session="s-1", **over):
    body = {
        "type": "assistant",
        "sessionId": session,
        "uuid": f"{request_id}-{stamp}",
        "requestId": request_id,
        "timestamp": stamp,
        "message": {"usage": usage()},
    }
    body.update(over)
    return body


def write(directory: Path, name: str, entries: list[dict]) -> Path:
    path = directory / name
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return path


class RequestIsTheUnitTests(unittest.TestCase):
    """THE MEASURED DEFECT, pinned.

    Against a real 2026-08-24 session log: 237 entries carrying usage, 92
    distinct requestIds, the usage object byte-identical across every entry
    sharing one. Per-entry summing reported 39,467,766 tokens for a session
    that consumed 15,653,391.
    """

    def _read(self, entries):
        with TemporaryDirectory() as tmp:
            path = write(Path(tmp), "s.jsonl", entries)
            return mod.read_claude(path)

    def test_one_request_spread_over_three_entries_is_counted_once(self):
        session, records, abstained = self._read([
            entry("req_a", "2026-08-24T22:46:31.805Z"),
            entry("req_a", "2026-08-24T22:46:33.207Z"),
            entry("req_a", "2026-08-24T22:46:33.737Z"),
        ])
        self.assertEqual("s-1", session)
        self.assertEqual(0, abstained)
        self.assertEqual(1, len(records))
        self.assertEqual(1115, records[0]["tokens"])

    def test_distinct_requests_are_all_counted(self):
        _, records, _ = self._read([entry("req_a"), entry("req_b"), entry("req_c")])
        self.assertEqual([1115, 1115, 1115], [r["tokens"] for r in records])

    def test_the_iterations_restatement_is_not_added_on_top(self):
        """`usage.iterations` repeats the same counts inside the same object.
        Summing both double-counts every single request."""
        payload = usage()
        payload["iterations"] = [usage(), usage()]
        _, records, _ = self._read([entry("req_a", message={"usage": payload})])
        self.assertEqual(1115, records[0]["tokens"])

    def test_cache_reads_are_consumption_and_are_counted(self):
        """Cache-read input is billed input. Dropping it understates spend by
        the largest term in a long session."""
        _, records, _ = self._read(
            [entry("req_a", message={"usage": usage(read=50_000)})]
        )
        self.assertEqual(50_115, records[0]["tokens"])

    def test_records_come_out_in_a_stable_order(self):
        """Deterministic: run it twice, get byte-identical Turtle."""
        _, first, _ = self._read([entry("req_b", "2026-08-24T02:00:00Z"),
                                  entry("req_a", "2026-08-24T01:00:00Z")])
        self.assertEqual(["req_a", "req_b"], [r["id"] for r in first])


class AbstentionTests(unittest.TestCase):
    def _read(self, entries):
        with TemporaryDirectory() as tmp:
            return mod.read_claude(write(Path(tmp), "s.jsonl", entries))

    def test_an_entry_with_no_request_id_is_abstained_not_counted(self):
        """It cannot be deduplicated against its siblings, so counting it
        risks the overcount this whole module exists to prevent."""
        _, records, abstained = self._read([
            entry("req_a"), entry("req_a", requestId=None),
        ])
        self.assertEqual(1, len(records))
        self.assertEqual(1, abstained)

    def test_a_usage_object_missing_its_counts_is_abstained_never_zeroed(self):
        """A missing measurement that aggregates as 0 is wrong in the
        flattering direction — competency §D Q19's exact point."""
        _, records, abstained = self._read(
            [entry("req_a", message={"usage": {"input_tokens": 5}})]
        )
        self.assertEqual([], records)
        self.assertEqual(1, abstained)

    def test_a_record_with_no_timestamp_is_abstained(self):
        """Burn rate (Q20) is a read-time judgment over these timestamps; an
        undated record silently degrades every rate it lands in."""
        _, records, abstained = self._read([entry("req_a", timestamp=None)])
        self.assertEqual([], records)
        self.assertEqual(1, abstained)

    def test_a_foreign_jsonl_is_not_recognised_at_all(self):
        """Recognition is by shape, not suffix. This repo's own tracker is a
        .jsonl sitting in the same tree as everything else."""
        with TemporaryDirectory() as tmp:
            path = write(Path(tmp), "issues.jsonl",
                         [{"id": "camayoc-0d3", "status": "open"}])
            self.assertIsNone(mod.read_claude(path))

    def test_only_verified_formats_have_readers(self):
        """Codex is named in competency §D but no real rollout file was
        available to measure a reader against. A parser written from a format
        description is a guess, and the requestId defect above is exactly what
        a description does not tell you. When a rollout can be measured, this
        assertion is what should change first."""
        self.assertEqual(["claude"], sorted(mod.READERS))


class EmissionTests(unittest.TestCase):
    def _emit(self, records, principal="strider"):
        out: list[str] = []
        written = mod.emit("s-1", principal, "anthropic", "claude", records, out)
        return written, "\n".join(out)

    def test_a_session_with_no_usage_is_still_emitted(self):
        """Q19: 'which sessions carry NO usage record' needs the session stored
        independently of its records, or the question is unanswerable by
        construction and the answer reads as zero cost."""
        written, turtle = self._emit([])
        self.assertEqual(0, written)
        self.assertIn("Session", turtle)
        self.assertNotIn("UsageRecord", turtle)

    def test_every_emitted_node_is_tagged_observed(self):
        """The shape pins sourceKind to `observed` for both classes: a declared
        or inferred usage number is an estimate wearing an account's clothes."""
        _, turtle = self._emit([{"id": "req_a", "tokens": 11, "at": "2026-08-24T00:00:00Z"}])
        self.assertEqual(2, turtle.count('sourceKind> "observed"'))

    def test_the_record_carries_every_property_its_shape_requires(self):
        _, turtle = self._emit([{"id": "req_a", "tokens": 11, "at": "2026-08-24T00:00:00Z"}])
        for required in ("inSession", "provider", "tokensConsumed", "observedAt"):
            self.assertIn(required, turtle)
        self.assertIn("tokensConsumed> 11 ;", turtle)

    def test_tokens_are_emitted_as_a_bare_integer(self):
        """The shape requires xsd:integer. Quoting it makes every SUM in
        Q16–Q21 return nothing, which reads as 'this work was free'."""
        _, turtle = self._emit([{"id": "req_a", "tokens": 11, "at": "2026-08-24T00:00:00Z"}])
        self.assertNotIn('tokensConsumed> "11"', turtle)

    def test_a_principal_with_a_slash_cannot_break_the_iri(self):
        _, turtle = self._emit([], principal="aegis/crew/ian")
        self.assertIn("principal/aegis%2Fcrew%2Fian>", turtle)


class SummaryTests(unittest.TestCase):
    def test_unrecognised_files_are_counted_rather_than_ignored(self):
        """The denominator rule: a run covering a tenth of the logs must not
        look like one covering all of them."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "s.jsonl", [entry("req_a")])
            write(root, "other.jsonl", [{"unrelated": True}])
            out: list[str] = []
            stats = mod.ingest(mod.session_files([root]), "strider", None, out)
        self.assertEqual(1, stats["sessions"])
        self.assertEqual(1, stats["unrecognised"])
        self.assertEqual(1115, stats["tokens"])

    def test_sessions_without_records_are_reported_separately(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "s.jsonl", [{"sessionId": "s-1", "type": "user"}])
            out: list[str] = []
            stats = mod.ingest(mod.session_files([root]), "strider", None, out)
        self.assertEqual(1, stats["sessions"])
        self.assertEqual(1, stats["empty"])
        self.assertEqual(0, stats["records"])

    def test_the_provider_override_reaches_the_records(self):
        """The on-disk record does not say whether the harness was proxied;
        consumption billed by one provider must not be filed under another."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "s.jsonl", [entry("req_a")])
            out: list[str] = []
            mod.ingest(mod.session_files([root]), "strider", "bedrock", out)
        self.assertIn('provider> "bedrock"', "\n".join(out))


if __name__ == "__main__":
    unittest.main()
