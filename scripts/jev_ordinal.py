"""Ordinal slot for jev_bench: item-only requests and offline paired statistics.

No graph writes or promotion. Reference labels are external observations, never
generated here and never supplied to the judge. Missing labels stay missing.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from jev import JevClient


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def number(value, maximum: int | float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("score/confidence must be numeric")
    if not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError("score/confidence outside rubric range")
    return float(value)


def request(item: dict) -> dict:
    """Whitelist the one item and rubric; exclude ids, labels and surrounding logs."""
    rubric = item["rubric"]
    return {"state": item["item"], "questions": {
        "q": JevClient.score_q(rubric["instructions"], rubric["levels"])}}


def validate(items: list[dict]) -> None:
    if not items:
        raise ValueError("empty ordinal dataset")
    ids = set()
    for item in items:
        if not isinstance(item, dict) or not {"id", "item", "rubric"} <= item.keys():
            raise ValueError("each row needs id, item, rubric")
        if not isinstance(item["id"], str) or not item["id"] or item["id"] in ids:
            raise ValueError("item ids must be nonempty and unique")
        ids.add(item["id"])
        rubric = item["rubric"]
        if not isinstance(rubric, dict) or set(rubric) != {"instructions", "levels"}:
            raise ValueError("rubric needs only instructions and levels")
        levels = rubric["levels"]
        if (not isinstance(levels, list) or not 2 <= len(levels) <= 10
                or not all(isinstance(x, str) and x.strip() for x in levels)
                or len(set(levels)) != len(levels)):
            raise ValueError("rubric needs 2..10 distinct nonempty ordered levels")
        if not isinstance(rubric["instructions"], str) or not rubric["instructions"].strip():
            raise ValueError("rubric instructions required")
        labels = item.get("labels", {})
        if not isinstance(labels, dict) or set(labels) - {"reference", "human"}:
            raise ValueError("labels may contain reference and human only")
        for label in labels.values():
            if not isinstance(label, dict) or not {"score", "judge", "source"} <= label.keys():
                raise ValueError("labels require score, judge and source provenance")
            number(label["score"], len(levels) - 1)
            if not all(isinstance(label[k], str) and label[k].strip() for k in ("judge", "source")):
                raise ValueError("label provenance must be nonempty")
        digest(request(item))  # reject non-JSON and non-finite item values before any call


def statistics(pairs: list[tuple[float, float]], levels: int) -> dict:
    """Half-up bins for ordinal agreement/kappa; MAE uses untouched raw scores."""
    n = len(pairs)
    if not n:
        return {"n": 0, "exact": None, "within_one": None, "mae": None,
                "quadratic_weighted_kappa": None}
    bins = [(math.floor(a + .5), math.floor(b + .5)) for a, b in pairs]
    left = Counter(a for a, _ in bins)
    right = Counter(b for _, b in bins)
    observed = sum((a - b) ** 2 for a, b in bins) / n
    expected = sum(left[a] * right[b] * (a - b) ** 2
                   for a in range(levels) for b in range(levels)) / n ** 2
    return {"n": n, "exact": sum(a == b for a, b in bins) / n,
            "within_one": sum(abs(a - b) <= 1 for a, b in bins) / n,
            "mae": sum(abs(a - b) for a, b in pairs) / n,
            "quadratic_weighted_kappa": 1 - observed / expected if expected else None}


def report(items: list[dict], records: list[dict]) -> dict:
    validate(items)
    by_id = {}
    expected = {it["id"]: it for it in items}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("response row must be an object")
        ident = record.get("id")
        if ident not in expected or ident in by_id:
            raise ValueError("unknown or duplicate response id")
        it = expected[ident]
        req = request(it)
        if record.get("request_sha256") != digest(req) or record.get("request") != req:
            raise ValueError("stale response: item or rubric differs")
        if record.get("status") == "observed":
            result = record.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("answers"), dict):
                raise ValueError("response must retain result and answers")
            answer = result["answers"].get("q")
            if not isinstance(answer, dict):
                raise ValueError("missing score answer")
            number(answer.get("score"), len(it["rubric"]["levels"]) - 1)
            confidence = answer.get("confidence")
            if confidence is not None:
                number(confidence, 1)
            if not isinstance(result.get("model"), str) or not result["model"]:
                raise ValueError("response must retain model identity")
            actual = result.get("request", {})
            if not isinstance(actual, dict) or {k: actual.get(k) for k in req} != req:
                raise ValueError("response request does not match item and rubric")
        elif record.get("status") != "unavailable":
            raise ValueError("unknown response status")
        by_id[ident] = record
    groups = {}
    for it in items:
        key = digest(it["rubric"])
        groups.setdefault(key, []).append(it)
    summaries = []
    for key, group in groups.items():
        comparisons = {}
        for kind in ("reference", "human"):
            pairs, rows = [], []
            labelled = sum(kind in it.get("labels", {}) for it in group)
            for it in group:
                record = by_id.get(it["id"], {})
                label = it.get("labels", {}).get(kind)
                if label is None or record.get("status") != "observed":
                    continue
                answer = record["result"]["answers"]["q"]
                score, target = answer["score"], label["score"]
                pairs.append((score, target))
                rows.append({"id": it["id"], "score": score, "label": label,
                             "confidence": answer.get("confidence"),
                             "exact": math.floor(score + .5) == math.floor(target + .5)})
            stats = statistics(pairs, len(group[0]["rubric"]["levels"]))
            for hit, name in ((True, "conf_agree"), (False, "conf_miss")):
                values = [r["confidence"] for r in rows
                          if r["exact"] == hit and r["confidence"] is not None]
                stats[name] = sum(values) / len(values) if values else None
                stats[name + "_n"] = len(values)
            comparisons[kind] = {**stats, "labelled": labelled,
                                 "missing_labels": len(group) - labelled, "rows": rows}
        summaries.append({"rubric_sha256": key, "rubric": group[0]["rubric"],
                          "n": len(group), "comparisons": comparisons})
    observed = sum(r["status"] == "observed" for r in records)
    usage = [r["result"].get("usage", {}) for r in records if r["status"] == "observed"]
    input_tokens = [u.get("input_tokens") for u in usage if isinstance(u, dict)]
    usage_complete = len(input_tokens) == observed and all(
        isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in input_tokens)
    return {"slot": "ordinal", "status": "NOT RUN" if not records else "advisory",
            "sourceKind": "inferred", "plane": "quarantine", "trusted": False,
            "n": len(items), "observed": observed, "unavailable": len(items) - observed,
            "dataset_sha256": digest(items), "rounding": "nearest level, ties upward",
            "input_tokens": sum(input_tokens) if usage_complete and observed else None,
            "usage_scope": "observed responses only; failed calls may still be billed",
            "abstain_rate": None, "abstention": "score has no abstain option",
            "groups": summaries}


def run(items, responses: Path | None, live: bool, max_calls: int | None,
        output: Path | None, client=None) -> dict:
    validate(items)
    if responses:
        if live or output or max_calls is not None:
            raise ValueError("replay cannot be combined with live/output/max-calls")
        records = [json.loads(line) for line in responses.read_text().splitlines() if line.strip()]
        return report(items, records)
    if not live:
        if output or max_calls is not None:
            raise ValueError("output/max-calls require --live")
        return {"slot": "ordinal", "status": "DRY RUN", "sent": False,
                "calls": len(items), "requests": [request(it) for it in items]}
    if max_calls is None or max_calls < len(items) or output is None:
        raise ValueError("live requires --max-calls covering the dataset and a new --output")
    records = []
    # Reserve before constructing a client. A refusal must cost zero calls.
    with output.open("x") as stream:
        client = client or JevClient()
        for it in items:
            req = request(it)
            record = {"id": it["id"], "request": req, "request_sha256": digest(req),
                      "sourceKind": "inferred", "plane": "quarantine"}
            try:
                result = client.score(it["item"], it["rubric"]["instructions"],
                                      it["rubric"]["levels"])
                record.update(status="observed", result=result)
                report([it], [record])  # validate before crediting this observation
            except Exception as exc:
                # Preserve earlier paid answers; no automatic retry and no provider text.
                record = {**record, "status": "unavailable", "error": type(exc).__name__}
                record.pop("result", None)
            records.append(record)
            stream.write(json.dumps(record, allow_nan=False) + "\n")
            stream.flush()
            if record["status"] == "unavailable":
                break
    return report(items, records)
