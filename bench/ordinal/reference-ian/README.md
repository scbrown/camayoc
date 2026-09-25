# Independent reference annotations

These 36 agent reference labels apply to fixtures pinned at
`261592b8111495fcd102e73a116cefbc866b583d`: 28 NA items and eight Quipu evidence
items. The judge is Ian / GPT-6 Codex. These are not human labels or calibrated
truth, and no agreement with a model response has been measured.

Judgments used only each item and its rubric. All scores and reasons were frozen
before reading control metadata; no Jev response was viewed or requested.
`blind-judgments.json` preserves that frozen artifact, SHA-256:
`d236466100c676a450e05b58f2752eb7525eadb02f8047bda962e9279833a7b4`.

`annotations.jsonl` maps those judgments to the original item IDs, records each
rationale, and marks the seven synthetic Quipu variants as controls excluded from
calibration. Eligibility records exclusion of synthetic controls only; it does
not establish a calibrated reference set. `summary.json` records score counts.
The fixture files retain all original non-label fields.

Verification: all 36 scores and references matched their annotations; original
non-label fields matched the pinned input; zero human labels; `git diff --check`
and `just check` passed. Both ordinal runner previews reported `DRY RUN` and
`sent: false` (28 and eight planned calls). A live run requires its separate
recorded spend decision.
