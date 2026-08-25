#!/usr/bin/env python3
"""The per-question coverage tables — one per competency slice.

Split out of `scripts/query_coverage.py` when the suite reached six slices:
the tool is logic, these are a judgment, and only a human can say that
`camayoc_blockers_by_evidence_kind` answers verification Q10. What is NOT a
judgment is whether a named file exists or whether the terms it uses exist —
`query_coverage.py` checks both, so a table cannot quietly claim coverage it
does not have.

THREE STATES, KEPT APART ON PURPOSE. `query_coverage.py`'s own docstring
names EXPRESSIBLE and STORED as different levels and then, until 2026-08-25,
reported both shortfalls as one word. They are not the same finding:

    {"query": "name"}                a stored query answers it        STORED
    {"expressible": "reason"}        the ontology carries the terms;
                                     nobody has written the query     UNWRITTEN
    {"gap": "...", "needs": [...]}   the ontology cannot express it    GAP

An UNWRITTEN question is work with a known shape. A GAP is a competency gap —
camayoc-b6h's finding, reported as itself, never answered from the nearest
term. Collapsing them makes a slice of unwritten queries look like a slice of
missing vocabulary, which is the more excusable of the two and the wrong
answer.

EVERY SLICE HAS A TABLE, AND THAT IS ENFORCED. `tests/test_coverage_slices.py`
asserts set equality between this file's slice names and `competency/*.md`,
and between each table's question numbers and the questions the suite parser
finds in that file. A new competency slice cannot land without a table, and a
new question cannot land without a row. That guard exists because this repo
found the same defect twice in this same tool — see that file's header.
"""

from __future__ import annotations

#: Question -> the stored query that answers it, or None with the reason.
#:
#: Hand-maintained because the mapping is a judgment: only a human can say that
#: `camayoc_blockers_by_evidence_kind` answers Q10. What is NOT hand-maintained
#: is whether the named file exists or whether the terms exist — both are
#: checked below, so this table cannot quietly claim coverage it does not have.
#: slice name -> {question number -> coverage entry}. report() takes the slice.
COVERAGE_VL: dict[int, dict] = {
    1: {"query": "camayoc_verification_falsifier"},
    2: {"query": "camayoc_verifications_without_falsifier"},
    3: {"query": "camayoc_falsifiers_not_rerun"},
    4: {"query": "camayoc_adversarially_proven_checks"},
    5: {"query": "camayoc_check_variable_dependence"},
    6: {
        "query": None,
        "gap": "No Principal class and no observed stop/heartbeat record, so 'is "
               "this principal running' has nothing to join against. Correctly "
               "NOT a stored fact — ingress rule 5 forbids storing judgments that "
               "decay — but the read-time join needs an observed liveness record "
               "to join TO, and none is modelled. aegis:Session now exists (§D, "
               "camayoc-e29) and carries its principal via aegis:actor, but a "
               "session is not a liveness record: nothing says the session is "
               "still running. This remains the largest gap and it blocks the "
               "four-beads-one-cause family the paper leads with.",
        "needs": ["Principal", "observed stop record (frm/item/item_status/ts)"],
    },
    7: {"query": "camayoc_blocked_on_closed_dependency"},
    8: {
        "query": None,
        "gap": "No Alert or Escalation class. Same missing liveness join as Q6, "
               "plus the subject class itself.",
        "needs": ["Alert", "Escalation", "Principal liveness record"],
    },
    9: {
        "query": None,
        "gap": "Only createdAt and closedAt are modelled, so elapsed time WITHOUT "
               "a state transition is not derivable — the intermediate transitions "
               "are not recorded as facts.",
        "needs": ["StateTransition", "transitionedAt"],
    },
    10: {"query": "camayoc_blockers_by_evidence_kind"},
    11: {"query": "camayoc_execution_path_for_mechanism"},
    12: {"query": "camayoc_drifted_execution_paths"},
    13: {"query": "camayoc_single_owner_execution_paths"},
    # Section D (cost and effort accounting) numbers itself 16-21 — there is
    # no Q14/Q15 in the suite file. These rows were absent from this table
    # until 2026-08-22, which silently understated the slice's denominator —
    # the exact defect incident-corpus.md §4.2 documents. A gap uncounted is
    # a gap unreported.
    # §D became expressible with camayoc-e29 (2026-08-22): Session +
    # UsageRecord + provider/tokensConsumed/inSession/attributedTo, with
    # observedAt and actor REUSED rather than re-minted.
    16: {"query": "camayoc_work_item_token_cost"},
    17: {"query": "camayoc_principal_consumption_by_provider"},
    18: {"query": "camayoc_work_per_token"},
    19: {"query": "camayoc_sessions_without_usage"},
    20: {"query": "camayoc_provider_burn_window"},
    21: {"query": "camayoc_decision_cost"},
}


COVERAGE_GP: dict[int, dict] = {
    1: {"query": "camayoc_gp_trajectory_replay"},
    2: {"query": "camayoc_gp_trajectories_for_topic"},
    3: {"query": "camayoc_gp_admissible_exemplars"},
    4: {"query": "camayoc_gp_unverified_stretch"},
    5: {
        "query": None,
        "gap": "Per-step provenance-cone membership is computed by `quipu path "
               "cone` (quipu-gp2, design-only) and only its OMISSION verdicts "
               "are modelled (PathOmission with authority cone-analysis). A "
               "term for stored in-cone/out-of-cone status per step is "
               "deferred until that command exists — its output shape decides, "
               "and minting the term first would be modelling a mechanism's "
               "internals before the mechanism.",
        "needs": ["per-step cone-membership facts (shape decided by quipu path cone)"],
    },
    6: {"query": "camayoc_gp_omissions"},
    7: {"query": "camayoc_gp_dead_ends"},
    8: {"query": "camayoc_gp_blessing_history"},
    9: {"query": "camayoc_gp_superseded_paths"},
    10: {"query": "camayoc_gp_promotion_queue"},
    11: {"query": "camayoc_gp_paths_for_similar_work"},
    12: {"query": "camayoc_gp_conformance"},
    13: {"query": "camayoc_gp_backtest_outcomes"},
    14: {
        "query": None,
        "gap": "aegis:derivedConstraint is minted, but no Policy or capability-"
               "grant records exist to join against — the audit chain "
               "constraint <- path <- exemplars needs the L5 mechanisms "
               "(gated on verdict signing). Deferred with the later ladder "
               "levels, per the suite's acceptance note.",
        "needs": ["aegis:Policy records reachable from this graph", "grant/act records"],
    },
    15: {
        "query": None,
        "gap": "No record of individual authorized ACTS exists, so 'which acts "
               "were authorized by path-derived constraints' has nothing to "
               "join against. Same L5 dependency as Q14.",
        "needs": ["act records carrying their authorizing constraint"],
    },
    16: {
        "query": None,
        "gap": "Staleness is a read-time judgment over conformance evidence "
               "accumulated by the guard (yupana FR-41, design-only). "
               "deviatesAt is minted; the guard that writes conformance "
               "records at scale does not exist yet.",
        "needs": ["guard-written conformance records over time"],
    },
}

#: metrics-and-requirements. The slice where the omission cost the most: four
#: stored queries have answered these questions since 2026-08-07 and counted
#: toward nothing, so the tool UNDERSTATED real coverage while looking
#: complete. The remaining gaps are two families — the liveness join this
#: repo already tracks, and the fact that a requirement's CHANGE is not
#: modelled (only its current state is).
COVERAGE_MR: dict[int, dict] = {
    1: {"query": "camayoc_metrics_for_subject"},
    2: {
        "query": None,
        "gap": "The ownership half is answerable today (aegis:ownedBy is "
               "mandatory on both Metric and NonFunctionalRequirement). The "
               "second half — 'is that owner currently able to act' — is the "
               "same missing liveness join as verification Q6/Q8, and the "
               "slice says so itself: alert keepers were found pointing at "
               "stopped principals seven times out of ten. Answering only the "
               "half that is modelled, and presenting it as the answer, is "
               "precisely the adjacency defect the incident corpus catalogues.",
        "needs": ["Principal", "observed stop/heartbeat record"],
    },
    3: {"expressible": "NonFunctionalRequirement carries about, ownedBy and "
                       "createdAt, all sh:minCount 1 — 'for what service, by "
                       "whom, when' is a three-property projection. Unwritten, "
                       "not blocked."},
    4: {"query": "camayoc_unvalidated_metric_claims"},
    5: {"expressible": "Unmeasured promises: NonFunctionalRequirement with "
                       "FILTER NOT EXISTS { ?m aegis:measuresRequirement ?r }. "
                       "Every term exists."},
    6: {"expressible": "Orphan instrumentation, the mirror of Q5: Metric with "
                       "no measuresRequirement. Note that the shape makes this "
                       "mandatory, so against conforming data the honest answer "
                       "is 'none' — and the query is still worth storing, "
                       "because it is the shape's own falsifier."},
    7: {"query": "camayoc_metric_retrieval_method"},
    8: {"query": "camayoc_metric_reachability_candidates"},
    9: {
        "query": None,
        "gap": "No edge from a Decision to the Metric it cites as evidence. "
               "aegis:rationale is prose and aegis:blockerEvidence/"
               "promotionEvidence are about other subjects entirely; matching "
               "a metric to a decision by name inside the rationale string is "
               "the 'matching the description, not the thing' form (A5) that "
               "the incident corpus records. The edge is a single mint, but "
               "it is a mint, and it waits its turn.",
        "needs": ["an edge from Decision to the Metric it cites as evidence"],
    },
    10: {
        "query": None,
        "gap": "Half is free: aegis:threshold is on the requirement and quipu "
               "gives the as-of replay, so 'what was the threshold on <date>' "
               "is answerable. 'Who had changed it' is not. ownedBy names the "
               "standing owner, not whoever re-asserted the value, and the "
               "writer is episode metadata in the store rather than a fact in "
               "the graph — so the audit question this slice exists for is the "
               "half that cannot be answered.",
        "needs": ["an attribution on a threshold re-assertion, distinct from "
                  "aegis:ownedBy"],
    },
    11: {
        "query": None,
        "gap": "'Relaxed' is a comparison between two versions of a threshold, "
               "and 'in service of what decision' is an edge from that change "
               "to a Decision. Neither the change event nor the edge is "
               "modelled — only the current value is. Same root as Q10: the "
               "requirement's history is bitemporal in the store but is not a "
               "subject in the graph, so nothing can be said ABOUT a change.",
        "needs": ["a requirement-change subject", "an edge from that change to "
                  "the Decision that motivated it"],
    },
    22: {"expressible": "A regex over the requirement's rdfs:label for the "
                        "unquantified words the slice lists (quickly, large, "
                        "sufficient, as needed, reasonable). Expressible, and "
                        "the slice credits Pennant for the better answer: catch "
                        "it in a deterministic analyzer at AUTHORING time, not "
                        "at measurement time. A stored query here is the "
                        "backstop, not the fix."},
    23: {"expressible": "threshold, unit and measurementWindow all exist and "
                        "are all sh:minCount 1 on the requirement shape, so "
                        "against conforming data every requirement passes. "
                        "Storing it is still right: it is how you find the "
                        "requirements that entered before the shape did."},
}

#: crew-task-lifecycle. Slice 1, and the one with no stored queries at all —
#: the decision vocabulary is the oldest thing in the ontology and the least
#: queried. Every gap here is one of the two designs this repo has
#: deliberately deferred: Principal/liveness, and StateTransition.
COVERAGE_CTL: dict[int, dict] = {
    1: {"expressible": "Decision carries about, chose and rationale. This is "
                       "the question the whole slice exists for and it has no "
                       "stored query — the plainest instance of 'an uncounted "
                       "question is a gap unreported'."},
    2: {"expressible": "aegis:over holds the alternatives visible at the time, "
                       "and its absence is itself meaningful (the term's own "
                       "comment says so), which a stored query must render as "
                       "'none articulated' rather than as no rows."},
    3: {"expressible": "aegis:decidedIn, whose comment already admits the "
                       "looseness a stored query has to settle: it points at "
                       "'the work item (or session)' a decision was made "
                       "under, so the query must say which it accepts."},
    4: {"expressible": "aegis:decidedBy joined to aegis:decidedIn."},
    5: {"expressible": "Contested pairs are a read-time judgment over stored "
                       "facts, which is exactly what ingress rule 5 asks for: "
                       "two Decisions sharing aegis:about, differing in "
                       "aegis:chose, neither carrying supersededBy. No term is "
                       "missing; the judgment must not be stored."},
    6: {
        "query": None,
        "gap": "No class for a standing convention. A Decision tagged "
               "declared is adjacent — it is a choice made at a moment, not a "
               "rule that stands until revoked — and answering 'what "
               "conventions apply here' from it would report decisions as "
               "conventions. quipu owns aegis:Policy and camayoc reuses before "
               "minting, so the open question is a reuse decision, not a mint. "
               "Related: camayoc-95a evaluates aegis:appliesTo for the "
               "path-scoped half of exactly this question.",
        "needs": ["a standing-convention subject, or a decision to reuse "
                  "quipu's aegis:Policy", "a scope term binding one to an area"],
    },
    7: {"expressible": "aegis:supersededBy, which the term's comment describes "
                       "as saying who won without deleting the loser."},
    8: {"expressible": "WorkItem joined on aegis:about. Note the adjacent "
                       "surface: scripts/ingest_git_provenance.py emits "
                       "aegis:implements/aegis:modifies edges that answer a "
                       "sharper version of this, and neither term is declared "
                       "in ontology/core.ttl — a separate finding, not this "
                       "question's blocker."},
    9: {
        "query": None,
        "gap": "createdAt, assignedTo, closedAt and outcome give the endpoints. "
               "'Worked' — the intermediate transitions, with timestamps — is "
               "not recorded as facts at all, so the LIFECYCLE cannot be "
               "returned, only its first and last frames. Identical to "
               "verification Q9, and deliberately deferred with it: "
               "ontology/core.ttl:68-70 records the decision not to pre-empt "
               "the StateTransition design.",
        "needs": ["StateTransition", "transitionedAt"],
    },
    10: {
        "query": None,
        "gap": "Answerable only as an approximation, which is worse than not "
               "answerable. Without transitions the best available join is "
               "'assigned to this principal, with a created/closed interval "
               "overlapping the window' — under which an item assigned in June "
               "and closed in August reads as worked on in July. A plausible "
               "wrong answer is the failure mode this whole repo is built "
               "around, so this is registered as a gap rather than stored with "
               "a caveat nobody will read.",
        "needs": ["StateTransition", "transitionedAt"],
    },
    11: {"expressible": "aegis:closedAt with aegis:outcome, whose closed "
                        "vocabulary the shape already enforces."},
    12: {
        "query": None,
        "gap": "The stop payload (frm/item/item_status/ts) is an observed "
               "record no producer writes into the graph. This is verification "
               "Q6's missing liveness record seen from the work side, and it "
               "is the recursive instance the incident corpus quotes: the bead "
               "documenting invisible in-progress work was itself sitting "
               "in-progress on a stopped agent.",
        "needs": ["Principal", "observed stop record (frm/item/item_status/ts)"],
    },
    13: {"expressible": "aegis:sourceKind, mandatory on every subject the "
                        "shapes gate — aspect 1 of the paper, unqueried."},
    14: {"expressible": "A named-graph query against the plane IRIs "
                        "scripts/planes.py registers: what exists in "
                        "crew:inferred and nowhere that outranks it. The whole "
                        "quarantine mechanism is built and this question, which "
                        "is what quarantine is FOR, has no stored query."},
    15: {"expressible": "Bitemporal replay is quipu's and comes free; the "
                        "question exists to pin that the ontology never blocks "
                        "it. A stored query here is the proof of that claim."},
}

#: document-structure-and-chunks. The split is clean and worth reading: the
#: SECTION and SYMBOL half runs against a live graph (three repos, ingested
#: hourly) and is merely unwritten; the CHUNK half has no emitter, and the
#: slice's own acceptance forbids minting chunk terms until one is measured
#: live. That is a gap held open on purpose, not an oversight.
COVERAGE_DSC: dict[int, dict] = {
    1: {
        "query": None,
        "gap": "Chunk membership needs chunk nodes. bobbin:Chunk and "
               "bobbin:inDocument exist in shapes/code-entities.ttl as "
               "ADVISORY shapes only, and no emitter writes them — the slice's "
               "acceptance holds the terms at advisory 'until the emitter that "
               "writes it is measured live'. Blocked in bobbin, deliberately.",
        "needs": ["chunk facts from a measured bobbin emitter"],
    },
    2: {
        "query": None,
        "gap": "Same missing emitter, plus ordering: bobbin:chunkOrder is "
               "advisory and unwritten, so 'in what order' has nothing to sort "
               "by and would silently return document order instead.",
        "needs": ["chunk facts from a measured bobbin emitter", "bobbin:chunkOrder"],
    },
    3: {
        "query": None,
        "gap": "Sections exist and are live; the chunk-to-section containment "
               "edge does not. The answer would have to be inferred from "
               "offsets, which is a model fact wearing a parser's clothes.",
        "needs": ["chunk facts from a measured bobbin emitter",
                  "a chunk-to-section containment edge"],
    },
    4: {
        "query": None,
        "gap": "bobbin:nextChunk is advisory and unwritten. Note the shape of "
               "the wrong answer: with no adjacency edge, 'what follows' would "
               "be answered by chunk id ordering, which is adjacent to "
               "adjacency and not it.",
        "needs": ["bobbin:nextChunk written by a measured emitter"],
    },
    5: {"expressible": "Section, bobbin:headingDepth, bobbin:inDocument and "
                       "bobbin:contains are all live in the code-entity graph. "
                       "Unwritten, not blocked."},
    6: {
        "query": None,
        "gap": "'First chunk of a section' needs both halves the chunk emitter "
               "owes: containment and order.",
        "needs": ["chunk facts from a measured bobbin emitter", "bobbin:chunkOrder"],
    },
    7: {"expressible": "bobbin:contains between Sections, live."},
    8: {"expressible": "bobbin:headingDepth on Sections of a Document, live."},
    9: {
        "query": None,
        "gap": "No term distinguishes a standalone block (table, fenced code) "
               "from prose. Answering from Section containment alone would "
               "return the whole section and call it the blocks.",
        "needs": ["a block subject with its kind (table | fenced code | ...)"],
    },
    10: {"expressible": "bobbin:definedIn with bobbin:symbolKind, live against "
                        "the code-entity graph."},
    11: {"expressible": "bobbin:references / bobbin:touches from Sections to "
                        "symbols, live."},
    12: {"expressible": "bobbin:repo and bobbin:filePath, live — the plainest "
                        "question in the slice and still unwritten."},
    13: {
        "query": None,
        "gap": "Needs a per-chunk content hash recorded with a time, and the "
               "chunk emitter writes neither. aegis:contentHash exists but is "
               "carried on Metric, for reconciliation, not on chunks.",
        "needs": ["chunk facts from a measured bobbin emitter",
                  "a per-chunk content hash with its observation time"],
    },
    14: {
        "query": None,
        "gap": "The plane machinery is built and the question is right; there "
               "are simply no chunk-level facts to attribute yet. This row "
               "should flip to unwritten the moment the emitter lands, and it "
               "is the row that proves the emitter tagged its output.",
        "needs": ["chunk facts from a measured bobbin emitter"],
    },
}

#: workflow-and-archive. Landed 2026-08-24 with the vocabulary and the move
#: rule. Q1-Q12's stored queries and the shuttle fixture are camayoc-rkb,
#: dispatched separately — those rows are unwritten with a known owner. The
#: gaps are the ARCHIVE half: graph kinds, freezes and thaws are properties of
#: the store's meta-graph, answered by GET /graphs rather than by SPARQL over
#: this ontology, and a stored query cannot reach them.
COVERAGE_WA: dict[int, dict] = {
    1: {"expressible": "WorkflowRun, aegis:runOf and aegis:currentState, "
                       "window-scoped. Stored query + shuttle fixture: "
                       "camayoc-rkb."},
    2: {"expressible": "Valid-time as-of over the re-asserted currentState "
                       "facts — quipu's, and the reason currentState is "
                       "re-asserted per transition rather than mutated. "
                       "camayoc-rkb."},
    3: {"expressible": "TransitionEvent with fromState/toState/observedAt, "
                       "append-only by design. camayoc-rkb."},
    4: {"expressible": "aegis:outcome for the closed runs, non-terminal "
                       "currentState for the open ones. camayoc-rkb."},
    5: {"expressible": "aegis:hasStep on the definition against aegis:atStep "
                       "on the run's transitions — declared versus actually "
                       "traversed. camayoc-rkb."},
    6: {
        "query": None,
        "gap": "aegis:signature, VerifierRegistration, verifier and publicKey "
               "are quipu-owned aegis terms, reused not re-minted (see "
               "ontology/core.ttl's note on performedBy). So the verification "
               "join needs the identity graph, which is not reachable from "
               "camayoc's fixture — and this tool's own grounding self-check "
               "reads only ontology/core.ttl, so a query legitimately reusing "
               "them would be reported UNGROUNDED. Both halves have to be "
               "settled before a row here can be honest.",
        "needs": ["VerifierRegistration records reachable from the queried "
                  "dataset", "a grounding check that knows quipu-owned aegis "
                  "terms from undefined ones"],
    },
    7: {
        "query": None,
        "gap": "The negative form of Q6 and the more useful one — unsigned "
               "transitions, or signatures with no matching registration — and "
               "blocked on the same identity graph. Shuttle ships this as "
               "`shuttle-unverified-transitions`; the point of the question "
               "here is that it is answerable from day one, which camayoc "
               "cannot yet demonstrate.",
        "needs": ["VerifierRegistration records reachable from the queried "
                  "dataset"],
    },
    8: {"expressible": "aegis:performedBy with aegis:inRun over a time window. "
                       "The 'including frozen windows' half is dataset "
                       "composition (FROM / include_kinds), a parameter of the "
                       "query rather than a missing term. camayoc-rkb."},
    9: {
        "query": None,
        "gap": "Graph kinds and freeze state live in quipu's meta-graph and "
               "are served by GET /graphs, not by SPARQL over this ontology. "
               "The question also carries its own capability probe — a 404 "
               "means the store predates graph kinds and must read as 'cannot "
               "tell', never as 'no graphs' — which a stored query has no way "
               "to express.",
        "needs": ["the graph-kind labels as queryable facts, or a non-SPARQL "
                  "coverage level for store-surface questions"],
    },
    10: {
        "query": None,
        "gap": "Whether a dataset's composed kind label includes archive is a "
               "property of the dataset, not of any triple in it. Same "
               "store-surface boundary as Q9.",
        "needs": ["composed dataset kind labels as queryable facts"],
    },
    11: {
        "query": None,
        "gap": "quipu:lifecycleState, quipu:frozenInto (the pack's content "
               "hash) and quipu:frozenAt are meta-graph facts about a graph. "
               "Same boundary as Q9, and the authorisation half — who "
               "authorized the freeze — is the part camayoc most wants and "
               "least controls.",
        "needs": ["meta-graph freeze facts reachable from a query"],
    },
    12: {
        "query": None,
        "gap": "Half graph, half store: 'every run in the window is terminal' "
               "is a stored query, 'operational kind and not yet frozen' is a "
               "meta-graph label. It cannot be answered by either surface "
               "alone, which is the honest finding rather than a missing term.",
        "needs": ["meta-graph kind and lifecycle labels joinable against run "
                  "state"],
    },
    13: {"expressible": "camayoc:planePromotion carries promotedFrom, "
                        "promotedInto and sourceLeftOpen, written by "
                        "scripts/promote_plane.py; the as-of visibility half is "
                        "quipu's bitemporal replay. The mechanism this question "
                        "certifies is built (camayoc-913) and the certifying "
                        "query is not written — which is why the question is "
                        "here."},
    14: {
        "query": None,
        "gap": "A thaw keeps the frozen_packs row with thawed_at rather than "
               "deleting it — a store table, not graph facts. Same boundary as "
               "Q9/Q11. The question is right and camayoc is the wrong place "
               "to answer it from.",
        "needs": ["thaw records reachable from a query"],
    },
}

SLICES: dict[str, dict[int, dict]] = {
    "verification-and-liveness": COVERAGE_VL,
    "golden-paths": COVERAGE_GP,
    "metrics-and-requirements": COVERAGE_MR,
    "crew-task-lifecycle": COVERAGE_CTL,
    "document-structure-and-chunks": COVERAGE_DSC,
    "workflow-and-archive": COVERAGE_WA,
}
