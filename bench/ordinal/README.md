# Ordered rubric judge pilot

Status: implemented offline, **uncalibrated and advisory**. No independent
reference or human labels, or paid Jev observations, are included. The existing
NA evaluator and deterministic Quipu conformance/provenance gates remain the
authorities. These fixtures establish no agreement percentage or cost saving.

This is the ordinal slot of `scripts/jev_bench.py`, the same runner as the
competency benchmark. `scripts/jev.py` remains the only API client.

## Inputs and reference labels

`na-htm.jsonl` contains 28 fact/action-menu items from NeuralAmplifier's pinned
multi-decision grounding eval. It reuses the existing five-level relevance
rubric, selecting the first eight facts per decision (all when fewer exist).
This is a reproducible pilot selection, not a random sample. Citation labels
are not ordinal relevance scores and have not been converted into them.

`quipu-evidence.jsonl` contains one pinned single-test ledger claim and seven
explicitly synthetic variants with evidence removed or contradicted. Its new,
proposed rubric measures evidence sufficiency. It does **not** order the
categorical passed/failed/error/unsupported outcomes, establish execution, or
replace any conformance check. File URLs, revision and SHA256 provenance live
outside the judge input. The fixture uses a historical ledger snapshot;
agreement on it would say nothing about a newer implementation.

The five proposed evidence levels are: absent/contradictory evidence, assertion
only, a matching result row, row plus pinned identities, and those plus a
producer and reproduction procedure. Even the highest level is documentary
support, not independently verified execution. Owner review and independent
labels are prerequisites for calibration.

Each JSONL row has `id`, `item`, `rubric: {instructions, levels}`, and optional
`labels`. Only `item` and `rubric` enter a model request; ids, provenance,
annotation rationale and other samples do not. The caller is responsible for
keeping the item's own content limited to the object being judged.

Independent annotators may add either or both label channels:

```json
{
  "reference": {"score": 2, "judge": "model/version or named existing judge", "source": "reference-run artifact"},
  "human": {"score": 2, "judge": "annotator identity", "source": "annotation artifact"}
}
```

Scores are zero-based level positions. Preserve the source artifacts and label
before viewing Jev responses. A reference LLM should receive the same isolated
item and rubric. Do not call an agent-generated label a human label. Missing
labels remain missing, and synthetic test controls are never calibration data.

## Run and replay

Keyless preview is the default; it emits exact requests and their call count:

```sh
just jev-bench bench/ordinal/na-htm.jsonl --slot ordinal
just jev-bench bench/ordinal/quipu-evidence.jsonl --slot ordinal
```

Only after a recorded spend decision with a per-run cap, collect observations
into a **new** file. The examples below permit at most 28 and 8 calls respectively;
the call ceiling is not a dollar cap. Pricing and reference-judge costs must be
accounted for in the spend decision. No live run is part of CI.

```sh
just jev-bench bench/ordinal/na-htm.jsonl --slot ordinal --live --max-calls 28 --output /tmp/na-ordinal.jsonl
just jev-bench bench/ordinal/quipu-evidence.jsonl --slot ordinal --live --max-calls 8 --output /tmp/quipu-ordinal.jsonl
```

The runner flushes every response, stops on the first failure, never retries and
never overwrites an existing output. Preserve partial runs: failed or timed-out
calls may have been billed. Response artifacts retain model, request, confidence
when supplied, usage, and `sourceKind=inferred` / `plane=quarantine`. They are
local records, not graph writes. No result promotes facts or changes a gate.

Replay requires no key and makes no calls:

```sh
just jev-bench bench/ordinal/na-htm.jsonl --slot ordinal --responses /tmp/na-ordinal.jsonl
```

Responses bind to exact item and rubric hashes; changed inputs, duplicate or
foreign ids refuse. Labels can be added without recollecting model responses;
the report's dataset hash changes so annotation revisions remain distinguishable.

## What the report means

Reference and human agreement are reported separately, grouped by the exact
rubric. Different scales are never pooled. Each comparison includes paired
count, label coverage, every paired row, exact agreement, within-one agreement,
MAE and quadratic weighted Cohen's kappa. Missing labels produce null metrics,
not zero disagreement or perfect agreement. Missing responses remain in the
overall denominator, and live/replay commands return nonzero for unavailable
observations. A complete response set without labels is still uncalibrated.

Jev scores can be fractional. Exact/within-one/kappa use nearest-level bins with
half ties upward; MAE uses raw scores. Kappa is null when the expected disagreement
is zero (including a constant identical pair), and every metric is null without
pairs. Confidence means and sample counts are split by exact agreement. Score
has no abstain option: abstention rate is null, and an error is not an abstention.

Input-token totals cover observed responses only. Raw usage is retained; no cost
ratio is fabricated without comparable reference-run usage and dated pricing.
No threshold is selected and `trusted` remains false even at perfect agreement.
