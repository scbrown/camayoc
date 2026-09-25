# Design: Jev — typed decisions in the ingress path (exploration)

> **Status: EXPLORATION, FIRST ARM BUILT (2026-09-21).** Stiwi has a TypeSafe
> account (console.typesafe.ai, created 2026-09-20). Slot 2 below ships as
> `competency.py --method jev` over `scripts/jev.py`; nothing is decided. This doc exists so the question stays open in the repo rather than in
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
| 2 | Question mapping onto the competency suite / NO COVERAGE (`competency.py`, camayoc-b6h) | lexical; embedding path blocked by network policy (HF CDN denied) | `choice` over parsed competency questions + "none of these"; confidence floor → NO COVERAGE | strong | the semantic matcher b6h asked for, without weights on disk |
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

**Built 2026-09-21 (slot 2, question mapping):** `scripts/jev.py` is the only Jev client (bearer
key from `TYPESAFE_API_KEY`; no key -> `JevUnavailable`, never a silent
fallback). `competency.py --method jev` poses ONE `choice` per asked question
with the 91 suite questions plus a reserved `none-of-these` option; the verdict
carries `method: jev-latest-choice-v1`, `semantic: true`, the instructions, the
model, the confidence, the none probability, and `abstained`, which forces
`Empty`. Tests: `tests/test_jev.py` (fake transport, no network). Slot 1
(settled-decision collision, `noul`) is next.

Run it:

```bash
export TYPESAFE_API_KEY=...   # from your secret store
python3 scripts/competency.py --method jev "what did we decide about the build-host reboot?"
python3 scripts/competency.py --method lexical "what did we decide about the build-host reboot?"
```

## 6. Blockers before any of it

- ~~Jev API access (waitlist)~~ Account exists (2026-09-20). The key lives in
  Infisical as `TYPESAFE_API_KEY` (aegis-6016ma rule); scripts read it from the
  environment only.
- ~~Egress~~ Measured 2026-09-21: `POST api.typesafe.ai/v1/systemone` answers
  403 (reachable, unauthenticated) in 0.24 s from both crew hosts. The database host
  is still unmeasured.
- Quipu "deliberately contains no LLM" — Jev calls live in camayoc scripts (the
  ingress layer), never in the store.

## 7. Open questions

- Should a Jev verdict be its own episode kind (`camayoc:TypedVerdict`) or a
  property set on the existing collision/coverage verdict records?
- Confidence floors: measured per slot, not one global number.
- Does a `score` over the promotion queue need a rubric per plane?

Tracked: aegis-sfg5vb.

## 8. Across the stack (added 2026-09-21, Stiwi: "make progress on all of these")

Jev fits one job: a bounded decision with a state to judge, made often, where a
calibrated probability beats a rationale. The stack has that shape in more
places than camayoc. Each row is a bead under the epic named at the bottom.

| Where | Decision | Shape | Fit | Existing bead |
|---|---|---|---|---|
| camayoc | settled-decision collision | `noul` per standing decision | strong | camayoc-7lt (lexical today) |
| camayoc | promotion-queue triage | `score` on evidence quality | good | aegis-f8efkn (quipu side) |
| camayoc | entity-mention disambiguation | `choice` + neither | cautious | camayoc-0c8 (abstains today) |
| bobbin | retrieval floor: does this chunk answer the query | `noul` per chunk | strong | aegis-xd2nko (insufficient context) |
| yupana | grounded-predicate evaluator for edit policies | `noul` per predicate | strong | aegis-vwvjwl |
| shantytown | board hygiene: route by domain, duplicate?, escalation severity | `choice` / `noul` / `score` | strong (volume) | aegis-cvd2xu context |
| homelab ops | alert triage: severity + owner; governor stop deliberate-or-fault | `score` + `choice` | good | — |
| NeuralAmplifier | grounding-fact rank, tier routing, semantic guard | `score` / `choice` / `noul` | good | na-htm |
| evals | rubric judge for NA evals and quipu conformance | `score` | good | — |
| resume (hammond) | recruiter inbound disposition | `choice` + `noul`s | immediate | job-patrol skill |

**Never:** inside quipu (no model in the store), plane routing by `sourceKind`,
promotion itself. Jev ranks and flags; humans and deterministic code decide.

### 8.1 Fleet tooling: one way for any st agent to ask Jev

Every row above needs the same three calls. They must not each grow a client.

- **`scripts/jev.py` stays the single client** (camayoc owns ingress and the
  ingress discipline that every Jev answer is `inferred`).
- **`jev-mcp`**: a stdio MCP server in camayoc exposing `jev_noul`, `jev_choice`,
  `jev_score`, `jev_dry_run` (the request without sending) and `map_question`
  (an asked question -> competency id, probability, confidence, abstention,
  stored-query name; floor 0.75, never a guess below it). **Delivered through
  the camayoc plugin** (Stiwi 2026-09-21): declared in
  `.claude-plugin/plugin.json` `mcpServers`, so `/plugin install camayoc@camayoc`
  is the whole registration; shantytown only projects the manifest at launch
  (aegis-b08zsc). The skill's *query first* move becomes map, then run the
  stored query, then file an abstained question as a candidate competency
  question. `/camayoc:bootstrap` offers the Jev step like it offers bobbin and
  yupana: asks where `TYPESAFE_API_KEY` lives, proves a dry run and one live
  `noul`, reports unreachable/unauthorized honestly. Never a key in a card or
  a template.
- **CLI parity**: `python3 scripts/jev.py {noul,choice,score}` for shells and
  cron. Both surfaces log `usage.input_tokens` and the model string.
- **Guardrails baked in, not documented**: `choice` always accepts a
  `none_text` and the MCP tool defaults it on; every result carries the
  request; a missing key is an error the agent can read, not a fallback.
- **Cost line**: at ~$0.0004 per decision, 10k decisions/day is ~$4. The MCP
  server counts calls per agent so the governor can see it.

### 8.2 The benchmark that must exist before any arm is trusted

A labelled set per slot (≈30 items with the human-correct answer), then per arm:
agreement with the label, confidence distribution on agreements vs
disagreements, abstain rate. Thresholds come from that, never from a default.
The competency slot's first three live calls (2026-09-21) already produced one
"confident but arguable" pick; that is the item type the set needs most.

### 8.3 Question-mapping results, 2026-09-21 (35 labelled items, hammond as ontology owner)

| arm | agreement | conf when right | conf when wrong | abstain | input tokens |
|---|---|---|---|---|---|
| lexical | 54% | — | — | 0% | 0 |
| jev (flat, 91 options) | **94%** | 0.96 | 0.64 | 17% | 163,920 |
| jev-hier (file then question, +examples) | 74% | 0.84 | 0.45 | 31% | 76,426 |

Rulings from this: **flat stays the default**; a **confidence floor of 0.75**
turns below-floor verdicts into "a human reads it" rather than a filed gap
(the 0.96/0.64 split is what makes the floor meaningful); the two-stage
variant halves the tokens but loses 20 points, almost all at the file stage,
so it is kept as a measured option and not used. Cost of the default:
~4.7k input tokens (< $0.01) per asked question at list price.

### 8.4 Vocabulary (Stiwi 2026-09-21)

**Mapping, not coverage.** Jev maps an asked question onto the competency
suite (or abstains). *Coverage* is the deterministic question — does a
competency question have a stored query that answers it — and stays with
`query_coverage.py`. The verdict's `coverage: Empty|Partial|Full` field keeps
its pre-Jev name (camayoc-b6h) because other tools read it; read it as "how
well the asked question maps".
