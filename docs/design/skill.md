# Design: The Skill Is the Interface

> **Implementation status (2026-08-22):** 🟡 **The skill ships in this repo
> (`skills/camayoc/SKILL.md`); the quipu substrate it leans on is partly
> landed.** Labels (#65) are no longer the gap they were: quipu's
> `/graph/create` + `/graph/label` routes exist and `scripts/planes.py` uses
> them to label the quarantine planes (camayoc-s0h). Server-side stored
> queries (#79) remain pending as far as this repo can verify — camayoc's
> half is done ahead of them: `queries/` ships 21 named query definitions,
> executed against fixture graphs in tests, ready to load when #79 lands.
> Where machinery is unbuilt the skill still says so and gives the raw-SPARQL
> fallback — it never pretends.

## 1. The usage model

Camayoc's primary consumer is **an agent in a session**, not a pipeline. The
unit of distribution is therefore a **skill**: a package of instructions an
agent loads that teaches it how to use governed memory — when to query, when
to record, how to tag, and how to stand a store up from nothing. Harness
adapters and record parsers are *optional enrichment*; the skill is the
first-class surface.

This kills two design risks at once:

- **No hard dependency on any harness.** Shantytown, Claude Code, a bare
  script — any agent that can speak HTTP to a quipu can follow the skill.
  Shantytown's reserved `knowledge` adapter remains a welcome *integration*
  (and its none-adapter proves the independence in the other direction), but
  nothing in camayoc requires it.
- **Guidance and enforcement stay separate.** The skill *guides* the agent
  (record decisions at the moment they happen, tag honestly, query before
  deciding). The SHACL shapes *enforce* (an untagged write is refused by the
  store, whatever the agent believed). A well-behaved agent rarely sees a
  refusal; a misbehaving one cannot do damage the shapes prohibit. The skill
  is UX; the shapes are the contract.

## 2. The four pillars, as the skill enables them

| Pillar | What the skill has the agent do |
|---|---|
| **Bootstrap** | Stand up governed memory from nothing: check the quipu is reachable, load `ontology/` + `shapes/` (idempotent), verify with a probe write that SHACL refusal is live — *prove the gate is on, not assume it*. |
| **Query first** | Before deciding or re-deriving: run the competency questions (stored queries once quipu #79 lands; the skill carries raw-SPARQL equivalents until then). "What did we decide about X and why" is asked *before* X is re-decided. |
| **Record at the moment** | When a decision happens, write it then — an episode carrying a `Decision` (what was chosen, over what, why, under which work item), tagged with its honest `sourceKind`. Work items and outcomes likewise. Session end = outcomes recorded, not summarized into oblivion. |
| **Tag honestly** | `observed` = a record exists and was parsed; `declared` = a human said so (quote them); `inferred` = the agent concluded it — and inferred lands in the inferred plane, low-trust, promotable later. Never up-tag. The store refuses untagged writes; the skill makes the honest tag the path of least resistance. |

## 3. What the skill is not

- **Not a wrapper library.** It contains instructions and canonical request
  shapes (quipu's `/episode`, `/query`, `/shapes` — branch on `outcome`,
  never on `count`), not code to vendor. An agent with Bash and HTTP has
  everything it needs.
- **Not a harness hook.** It does not assume stop-hooks, inboxes, or any
  lifecycle. A harness that *has* those (shantytown) can invoke the same
  moves automatically; that is that harness's integration, not the skill's
  concern.
- **Not a substitute for the shapes.** Nothing in the skill is
  load-bearing for integrity. Delete the skill and the store is exactly as
  safe — just harder to use well.

## 4. Consequences for the rest of the repo

- **Record parsers demote to enrichment.** The task-lifecycle slice's spine
  is the skill-guided agent recording its own work; deterministic parsers
  (git history, a harness's task records) *backfill and corroborate* — they
  are `observed`-tier enrichment, valuable and optional.
- **The competency suite doubles as the skill's query cheat-sheet.** One
  file, two consumers: the eval gate runs the questions; the skill quotes
  them.
- **Packs carry the skill.** When quipu #81 lands, a domain pack's manifest
  references the skill version it was authored against — attach a pack, get
  told how to use it.

## 5. Related

- [`skills/camayoc/SKILL.md`](../../skills/camayoc/SKILL.md) — the artifact.
- [ingress.md](ingress.md) — the discipline the skill teaches; the shapes
  that enforce it.
- [task-lifecycle-slice.md](task-lifecycle-slice.md) — the first slice,
  re-centered on the skill.
- [competency/crew-task-lifecycle.md](../../competency/crew-task-lifecycle.md)
  — the questions the skill tells an agent to ask.
