# Phase 3 — Sequence and deviation

Status: implemented; live Queue acceptance awaits explicit authorization

## Outcome

The offline pipeline emits an outcome-agnostic next-action policy that expands
components, respects current inventory/economy, recovers after deviation, and abstains
outside supported states.

## Decisions

- Treat next-purchase prediction as imitation, never item effect. Use a deterministic
  first-item/previous-item/position backoff baseline in production unless the existing
  ranker beats it on chronological held-out gates.
- Add one versioned decision-state JSON contract containing snapshot/cohort identity,
  hero, clock, rank, liquid souls, inventory/components, slots/flex/actives, and learned
  abilities. Missing required live state produces abstention.
- Add a read-only `recommend --state FILE` command returning buy, save, end, or abstain
  with item, incremental component cost, support, backoff level, and policy identity.
- Generate legal candidates deterministically. Outcome rates never enter membership or
  ranking; `save` is returned when the supported next item is legal but unaffordable.
- Keep the installed Steam build static. Dynamic decisions live in the sidecar/CLI;
  CORE remains the simple default when no live state is supplied.

## Work

- Extend extraction with deidentified decision states and reconstruct buys, component
  consumption, sells, owned slots, and active burden without future leakage.
- Export versioned transition/backoff tables and component-expanded default paths in
  build evidence; validate their hashes and legality during admission.
- Extend the policy evaluator to recalculate from actual ownership instead of restarting
  the eight-card path.
- Evaluate the challenger and promote it only when every predeclared gate passes;
  otherwise ship the simpler baseline and record the rejection.

## Proof

- Match-group-safe chronological Recall/NDCG/MRR, coverage, legality, stability, and
  risk–coverage reports against popularity and transition baselines.
- Fixtures for owned components, manual off-path buys, sells, full slots, four actives,
  flex changes, insufficient currency, sparse states, and stale state identity.
- Live Queue acceptance for parent upgrades, manual deviation, component ownership, and
  imbue prompts only with explicit authorization.

## Implementation record

- Build-evidence schema 2 exports component-expanded defaults plus deterministic
  first/previous/position/popularity backoffs from training rows only.
- The existing XGBoost ranker remains a chronological challenger and cannot be
  promoted without a portable validated policy artifact, even when imitation metrics
  pass.
- `schemas/decision-state.schema.json` and `recommendation.py` provide one strict,
  deidentified patch/client/mode/rank/inventory/composition contract and return only
  buy, save, end, or abstain.
- Recommendation tests cover component credit, saving, sold/off-path history, backoff,
  sparse/unknown states, and exact evidence identity. Steam is never accessed.

Traceability: [usage audit](../deadlock-build-usage-audit.md#phase-3-sequence-and-deviation-research),
[deviation requirement](../deadlock-build-policy-requirements.md#req-pol-007--support-deviation-and-recalculation),
and [evaluation requirements](../deadlock-build-policy-requirements.md#10-evaluation-learning-and-monitoring).
