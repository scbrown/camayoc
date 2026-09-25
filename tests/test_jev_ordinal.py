"""Offline controls for ordinal agreement; synthetic labels are not calibration."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import jev
import jev_bench
import jev_ordinal as ordinal


def item(ident="one", score=1):
    return {"id": ident, "item": {"text": "one bounded item"},
            "rubric": {"instructions": "Rate evidence", "levels": ["none", "some", "full"]},
            "labels": {"reference": {"score": score, "judge": "fixture-only",
                                      "source": "synthetic test control"}},
            "private_note": "NEVER SEND", "why": "ANSWER KEY"}


def client(scores):
    calls = []
    def transport(body, key):
        calls.append(body)
        value = scores[len(calls) - 1]
        if isinstance(value, Exception):
            raise value
        return {"model": "fixture-only", "answers": {"q": {"score": value, "confidence": .7}},
                "usage": {"input_tokens": 12}}
    return jev.JevClient(api_key="fake", transport=transport), calls


class OrdinalTest(unittest.TestCase):
    def test_known_fractional_scores_and_kappa(self):
        result = ordinal.statistics([(0, 0), (1, 2), (2, 1)], 3)
        self.assertAlmostEqual(result["quadratic_weighted_kappa"], .5)
        self.assertEqual(result["exact"], 1 / 3)
        self.assertEqual(result["within_one"], 1)
        self.assertEqual(result["mae"], 2 / 3)
        self.assertEqual(ordinal.statistics([(0, 2), (2, 0)], 3)["quadratic_weighted_kappa"], -1)
        fractional = ordinal.statistics([(.49, 0), (.5, 0)], 3)
        self.assertEqual(fractional["exact"], .5)
        self.assertEqual(fractional["mae"], .495)

    def test_empty_and_constant_kappa_are_undefined(self):
        self.assertIsNone(ordinal.statistics([], 3)["exact"])
        result = ordinal.statistics([(1, 1)] * 5, 3)
        self.assertEqual(result["exact"], 1)
        self.assertIsNone(result["quadratic_weighted_kappa"])

    def test_label_leakage_and_replay(self):
        fake, calls = client([1.2])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "responses.jsonl"
            live = ordinal.run([item()], None, True, 1, path, fake)
            with patch.object(jev.JevClient, "__init__", side_effect=AssertionError("network")):
                replay = ordinal.run([item()], path, False, None, None)
            self.assertEqual(live, replay)
            self.assertEqual(live["observed"], 1)
            self.assertEqual(live["input_tokens"], 12)
            comparison = live["groups"][0]["comparisons"]
            self.assertEqual(comparison["reference"]["exact"], 1)
            self.assertIsNone(comparison["human"]["exact"])
            self.assertEqual(comparison["human"]["missing_labels"], 1)
            raw = path.read_text()
            self.assertIn('"model": "fixture-only"', raw)
            self.assertIn('"input_tokens": 12', raw)
        self.assertEqual(calls[0]["state"], item()["item"])
        self.assertNotIn("ANSWER KEY", json.dumps(calls))
        self.assertNotIn("NEVER SEND", json.dumps(calls))
        self.assertNotIn("labels", json.dumps(calls))

    def test_dry_run_is_keyless(self):
        with patch.object(ordinal, "JevClient") as cls:
            cls.score_q = jev.JevClient.score_q
            result = ordinal.run([item()], None, False, None, None)
            cls.assert_not_called()
        self.assertFalse(result["sent"])

    def test_caps_and_existing_output_refuse_before_paid_call(self):
        fake, calls = client([1])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "responses.jsonl"
            for cap in (None, 0):
                with self.assertRaises(ValueError):
                    ordinal.run([item()], None, True, cap, path, fake)
            path.write_text("preserve me")
            with self.assertRaises(FileExistsError):
                ordinal.run([item()], None, True, 1, path, fake)
            self.assertEqual(path.read_text(), "preserve me")
        self.assertEqual(calls, [])

    def test_partial_error_preserves_paid_records_stops_without_retry(self):
        fake, calls = client([1, TimeoutError("provider secret"), 2])
        items = [item("a"), item("b"), item("c")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "responses.jsonl"
            result = ordinal.run(items, None, True, 3, path, fake)
            self.assertEqual(result["observed"], 1)
            self.assertEqual(result["unavailable"], 2)
            self.assertEqual(len(calls), 2)
            self.assertEqual(len(path.read_text().splitlines()), 2)
            self.assertNotIn("provider secret", path.read_text())
            self.assertEqual(ordinal.run(items, path, False, None, None), result)

    def test_missing_is_not_disagreement_or_abstention(self):
        result = ordinal.report([item()], [])
        self.assertEqual(result["status"], "NOT RUN")
        self.assertIsNone(result["abstain_rate"])
        comparison = result["groups"][0]["comparisons"]["reference"]
        self.assertEqual(comparison["labelled"], 1)
        self.assertEqual(comparison["n"], 0)
        self.assertIsNone(comparison["exact"])

    def test_bad_labels_validated_before_any_call(self):
        for bad in (True, "1", None, -1, 3, float("nan"), float("inf")):
            fake, calls = client([1])
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    ordinal.run([item(score=bad)], None, True, 1, Path(tmp) / "out", fake)
                self.assertEqual(calls, [])

    def test_bad_scores_are_unavailable(self):
        for bad in (True, "1", None, -1, 3, float("nan"), float("inf")):
            fake, _ = client([bad])
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                result = ordinal.run([item()], None, True, 1, Path(tmp) / "out", fake)
                self.assertEqual(result["observed"], 0)
                self.assertEqual(result["unavailable"], 1)

    def test_stale_rubric_item_and_foreign_or_duplicate_response_refuse(self):
        fake, _ = client([1])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "responses.jsonl"
            ordinal.run([item()], None, True, 1, path, fake)
            record = json.loads(path.read_text())
            changed = item()
            changed["rubric"]["levels"][1] = "different"
            with self.assertRaisesRegex(ValueError, "stale"):
                ordinal.report([changed], [record])
            changed = item()
            changed["item"] = "different"
            with self.assertRaisesRegex(ValueError, "stale"):
                ordinal.report([changed], [record])
            with self.assertRaises(ValueError):
                ordinal.report([item()], [record, record])
            with self.assertRaises(ValueError):
                ordinal.report([item("other")], [record])
            record["result"]["request"]["state"] = "foreign request"
            with self.assertRaisesRegex(ValueError, "does not match"):
                ordinal.report([item()], [record])

    def test_different_rubrics_never_pooled(self):
        second = item("second")
        second["rubric"]["levels"] = ["absent", "partial", "complete", "independent"]
        result = ordinal.report([item(), second], [])
        self.assertEqual(len(result["groups"]), 2)

    def test_independent_label_update_reuses_request_but_changes_dataset_digest(self):
        fake, _ = client([1])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "responses.jsonl"
            first = ordinal.run([item()], None, True, 1, path, fake)
            second = ordinal.run([item(score=2)], path, False, None, None)
        self.assertNotEqual(first["dataset_sha256"], second["dataset_sha256"])
        self.assertEqual(second["groups"][0]["comparisons"]["reference"]["exact"], 0)

    def test_cli_replay_failure_is_nonzero_and_default_is_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "items.jsonl"
            path.write_text(json.dumps(item()) + "\n")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(jev_bench.main([str(path), "--slot", "ordinal"]), 0)
            self.assertFalse(json.loads(out.getvalue())["sent"])
            responses = Path(tmp) / "responses.jsonl"
            responses.write_text("")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(jev_bench.main([str(path), "--slot", "ordinal",
                                              "--responses", str(responses)]), 1)

    def test_empty_duplicate_and_bad_provenance_refuse(self):
        invalid = [[], [item(), item()]]
        broken = item()
        broken["labels"]["reference"]["source"] = ""
        invalid.append([broken])
        for items in invalid:
            with self.assertRaises(ValueError):
                ordinal.validate(items)

    def test_both_pilot_datasets_are_valid_and_unlabelled(self):
        root = Path(__file__).resolve().parents[1] / "bench" / "ordinal"
        for filename, count in (("na-htm.jsonl", 28), ("quipu-evidence.jsonl", 8)):
            items = [json.loads(line) for line in (root / filename).read_text().splitlines()]
            ordinal.validate(items)
            self.assertEqual(len(items), count)
            self.assertTrue(all(not row["labels"] for row in items))
            report = ordinal.report(items, [])
            self.assertEqual(report["observed"], 0)
            self.assertFalse(report["trusted"])
            for group in report["groups"]:
                for comparison in group["comparisons"].values():
                    self.assertIsNone(comparison["exact"])


if __name__ == "__main__":
    unittest.main()
