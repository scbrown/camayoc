# Competency questions — golden paths (trajectories, blessing, conformance)

The test suite for the golden-paths slice
([docs/design/golden-paths.md](../docs/design/golden-paths.md)). A golden
path is a completed work item with verified results, pruned and promoted into
a blessed trajectory that guides — and eventually authorizes — similar future
work. Same discipline as the earlier slices: every ontology term must be owed
to a question here, and every question must eventually run as a named stored
query (quipu #79) against real records. Parameters in angle brackets.

## A. Trajectory replay — "what actually happened?"

1. What trajectory did `<work-item>` actually take — the ordered steps, each
   with actor, action, the Decision it enacted, and the Verification it
   produced, with timestamps?
2. Which trajectories exist for work items about `<topic/entity>`, and which
   of their work items closed `done`?

## B. Admissibility — "is this success evidence-grade?"

3. Which completed work items are admissible golden-path exemplars — closed
   with outcome `done` AND a terminal claim carrying falsifier-gated
   Verifications? (A success whose verification cannot name its failing
   result is an anecdote, not an exemplar.)
4. For `<trajectory>`, which of its steps produced falsifier-gated
   Verifications and which produced none? (The unverified stretch of a
   successful trajectory is where blessing must lean on human judgment.)

## C. Pruning — "which steps earned their place?"

5. Which steps of `<trajectory>` are inside the provenance cone of its
   verified result, and which are outside it (mechanically prunable)?
6. Which steps were pruned from `<golden-path>`, and on what authority — the
   deterministic cone analysis, or a human Decision, and with what rationale?
7. What dead ends did the exemplars of `<golden-path>` explore and abandon —
   what should a follower expect not to help? (Pruned is not deleted;
   negative knowledge is knowledge.)

## D. Blessing — "who promoted this, on what evidence?"

8. What is the blessing level of `<golden-path>` — recorded, verified,
   candidate, advisory, blessed, or constraint-backing — and for each
   promotion: who promoted it, when, citing which evidence?
9. Which golden paths were demoted or superseded, by what, and why?
10. Which candidate paths are awaiting human promotion, and how long have
    they waited? (The queue is where "we're involved in the process" is
    either true or quietly false.)

## E. Conformance — "is this work on the path?"

11. Which golden paths exist for work items like `<work-item>`? (Similarity
    resolves against the work item's type, topic entities, and declared
    intent — never against the tracker's message format.)
12. Is `<trajectory>` conforming to the golden path it declared? Where does
    it deviate — at which step, in what way?
13. Historically, did work items conforming to `<golden-path>` close `done`
    at a higher rate than comparable non-conformers? (The backtest that must
    be run before promotion and is re-runnable after.)

## F. Authorization audit — "why was this action allowed?"

14. Which constraints derive from `<golden-path>`, and which principal's
    capability grant is backed by which constraint, backed by which
    exemplars? (The full audit chain from an authorized act back to the
    concrete successful work that justified it.)
15. Which acts by `<principal>` in `<time-window>` were authorized by
    path-derived constraints rather than base capability?

## G. Staleness — "is the blessing still earned?"

16. Which golden paths have gone stale — exemplars whose context has since
    changed, or recent conformers now failing where exemplars succeeded?
    (Evidence for a demotion decision at read time, never a stored decaying
    "still good" verdict.)

## Acceptance

The slice is done when 1–13 run as named queries against a fixture graph
built from real trajectory records and the answers are accepted as faithful.
14–16 additionally require the constraint-derivation and conformance record
paths to exist and must return correct provenance chains; they may land with
the later levels of the blessing ladder rather than the first cut.
