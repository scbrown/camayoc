# Design: Jev — typed decisions in the ingress path (exploration)

> **Status: OPEN EXPLORATION (2026-09-20, Stiwi).** Nothing here is built or
> decided. This doc exists so the question stays open in the repo rather than in
> a chat. It records what Jev is, where a typed decision would slot into camayoc
> and into NeuralAmplifier, what the ingress discipline demands of it, and what
> has to be true before the first experiment runs. Tracked on the aegis board;
> see the bead named at the bottom.

## 1. What Jev is (measured from public sources, not from use)

Jev is TypeSafe AI's first "System One" model (announced 2026-09-15). It
generates no text. A request carries a `state` (string, object or array) and a
map of named questions; the reply carries every answer in one parallel pass.

| Primitive | Input | Output |
|---|---|---|
| `noul` | a yes/no proposition | one probability in [0,1] |
| `choice` | up to 255 named options | winner, probability per option, confidence |
| `score` | 2–10 ordered rubric levels | probability-weighted position, distribution, confidence |

`POST https://api.typesafe.ai/v1/systemone`, bearer key, model `jev-latest`.
Questions in one request are evaluated independently. Public figures: 70–500 ms
per call; input $0.042 per million tokens, output unmetered; ~$0.0004 per
decision. TypeSafe's classification benchmark: Jev 67.8% vs Claude Opus 5 73.1%.
Langfuse's 6,003-check eval benchmark: 91.5% agreement with Claude Fable 5.1 at
$160 per million answers vs $33,000. Early access behind a waitlist as of
2026-09-20.

Three properties shape every use below:

1. **It cannot abstain.** A `choice` with no fitting option still picks one.
   Every choice we pose carries an explicit "none of these" option, and a
   confidence floor decides whether the answer is used at all.
2. **It gives no rationale.** An auditable decision must reconstruct its trace
   from the state and the question, which is why the verdict record must carry
   both verbatim.
3. **It degrades on long, noisy state** ("context rot", Langfuse). State is
   assembled by deterministic code, minimal, and its size recorded.

## 2. What the ingress discipline demands

A Jev answer is a model judgment. Ingress rule 4 applies without exception:

- Every verdict is tagged `aegis:sourceKind "inferred"` and routed through
  `planes.plane_for("inferred")`. Never ROOT, never an observed plane.
- The verdict record carries `method: "jev-latest"`, `semantic: true`, the
  question text, the criteria as posed, the raw probabilities, the confidence,
  the threshold used, and the state watermark — the same honesty
  `settled_decisions.py` and `competency.py` already enforce on their lexical
  scorers. A lexical verdict may not masquerade as semantic; a semantic one may
  not hide its numbers.
- **Jev never promotes.** Plane promotion stays behind
  `config/plane-authority.json` and `scripts/promote_plane.py`. Jev may *rank*
  the promotion queue for a human; it holds no authority.
- **Routing by `sourceKind` stays deterministic.** No model decides which plane
  a fact enters.

## 3. Candidate uses in camayoc, ranked by fit

| # | Slot | Today | Jev shape | Fit | Why |
|---|---|---|---|---|---|
| 1 | Settled-decision collision (`settled_decisions.py`, camayoc-7lt) | lexical, advisory, says so | one `noul` per standing decision: "does the new Decision duplicate or conflict with this one" | strong | advisory posture already tolerates error; verdict shape exists |
| 2 | Competency coverage / NO COVERAGE (`competency.py`, camayoc-b6h) | lexical; embedding path blocked by network policy (HF CDN denied) | `choice` over parsed competency questions + "none of these"; confidence floor → NO COVERAGE | strong | the semantic matcher b6h asked for, without weights on disk |
| 3 | Promotion-queue triage | nothing ranks the quarantine plane | `score` "how well evidenced is this fact" over a fixed rubric | good | orders human review; authority untouched |
| 4 | Entity-mention disambiguation (`extract_entities.py`) | abstains on a label naming two entities | `choice` among the candidates + "neither" | cautious | doc's stance: a wrong mention is worse than a missing one; keep the abstain path, high floor |
| 5 | Plane routing (`planes.plane_for`) | deterministic | — | **no** | must stay deterministic |

## 4. Candidate uses in NeuralAmplifier

NeuralAmplifier's value is a brain that explains its moves; Jev gives no reasons,
so the LLM-tier action choice is the wrong first target. Three other slots:

- **Grounding-fact ranking** — the open na-htm question is whether ranking facts
  by `information_value` predicts citation. A `score` per fact ("how
  decision-relevant to this action space") is a third arm the existing eval can
  score against the same MRR / top-k baselines.
- **Surface-tier routing** — deterministic tier vs LLM tier vs bigger model per
  decision (the LangChain harness pattern); cheap enough per turn.
- **A semantic guard** behind the `Guard` protocol — a `noul` "does this order
  contradict the active directive", advisory only, never a denial (StateGuard
  checks arithmetic; this would check intent).

## 5. First experiment

Slots 1 and 2 in camayoc: both already record method and threshold, so a Jev arm
is a scorer selection plus a benchmark against the lexical arm on the same
inputs. Report agreement, confidence distribution, and the NO COVERAGE rate.

## 6. Blockers before any of it

- Jev API access (waitlist) — who holds the key, where it lives (see
  aegis-6016ma for the credential-discoverability rule this must follow).
- Egress: the network policy that denied the HF CDN may also deny
  `api.typesafe.ai` from vati/kota. Measure, do not assume.
- Quipu "deliberately contains no LLM" — Jev calls live in camayoc scripts (the
  ingress layer), never in the store.

## 7. Open questions

- Should a Jev verdict be its own episode kind (`camayoc:TypedVerdict`) or a
  property set on the existing collision/coverage verdict records?
- Confidence floors: measured per slot, not one global number.
- Does a `score` over the promotion queue need a rubric per plane?

Tracked: aegis-sfg5vb.
