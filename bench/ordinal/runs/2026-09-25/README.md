# One capped advisory ordinal run

On 2026-09-25, Sattler authorized exactly one run of 28 NA and eight Quipu
items, with new output files and no retries, on aegis-4hhqoe.8. All 36 calls
returned observations from `jev-1.13.0`. No second run occurred.

Reference labels were frozen independently by `ian / GPT-6 Codex` before any
Jev response (source commit `cdb5f6fa731dc8e6e1b56a5b2e9282deabe14751`,
cherry-picked as `878cede`). There are **zero human labels**. Original item and
rubric fields were compared to `261592b` and are unchanged. Only each item and
rubric entered the requests; labels and annotation reasons stayed out.

| Set | n | Exact | Within one | Raw MAE | Quadratic weighted kappa |
| --- | ---: | ---: | ---: | ---: | ---: |
| NA pilot | 28 | 5/28 (17.86%) | 28/28 | 0.726786 | -0.018987 |
| Quipu, all | 8 | 5/8 (62.5%) | 8/8 | 0.302500 | 0.920000 |
| Quipu synthetic controls only | 7 | 4/7 (57.14%) | 7/7 | 0.344286 | 0.896552 |
| Quipu historical example only | 1 | 1/1 | 1/1 | 0.010000 | undefined |

Exact and within-one use nearest-level bins with half-up ties; MAE preserves
fractional scores. Synthetic controls are excluded from calibration. One
historical example cannot establish reliability, and a single identical binned
pair has undefined kappa. The NA selection is not random. These observations
compare against one agent annotator, not a calibrated gold standard.

NA confidence averaged 0.7100 on the five exact matches and 0.4974 on the 23
misses. Jev compressed NA scores into 1.20–2.29 against labels spanning 1–3.
Within-one success therefore does not offset the near-zero kappa. For Quipu,
missing producer and reproduction evidence still scored 3.86 and 3.88 against
reference level 3: high scores do not establish reproducibility.

## Usage and cost

The raw API responses report **60,659 input tokens and 612 output tokens**:
55,536/476 for NA and 5,123/136 for Quipu. All responses and requests are retained
in the JSONL files, with exact request hashes and model identifiers.

[TypeSafe's model page](https://docs.typesafe.ai/models), checked 2026-09-25,
lists $0.042 per million input tokens and free output. Applied to observed usage,
that is **$0.002547678**. This is list-price arithmetic, not an observed invoice
debit: response artifacts contain no monetary charge. Reference-judge billing
is unavailable, so no comparative cost-saving ratio is claimed.

## Decision and replay

Keep the existing NA reference judge and deterministic Quipu gates. Results
remain advisory, `sourceKind=inferred`, `plane=quarantine`, `trusted=false`.
No graph promotion, gate change or threshold tuning follows from this run.

The full reports include individual scores, confidence, label provenance and
missing-human coverage. The split Quipu reports use only the corresponding
records from the same eight-call run; they made no additional calls.

Recompute either full report without credentials or network calls:

```sh
just jev-bench bench/ordinal/na-htm.jsonl --slot ordinal --responses bench/ordinal/runs/2026-09-25/na-responses.jsonl
just jev-bench bench/ordinal/quipu-evidence.jsonl --slot ordinal --responses bench/ordinal/runs/2026-09-25/quipu-responses.jsonl
```
