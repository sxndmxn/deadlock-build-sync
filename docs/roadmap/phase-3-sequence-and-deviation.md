# Phase 3 — Sequence and deviation

Status: duplicate-free correction regenerated and audited; reinstall awaits Deadlock shutdown

## Outcome

The offline pipeline emits an outcome-agnostic next-action policy that expands
components, respects current inventory/economy, recovers after deviation, and abstains
outside supported states.

The static Steam CORE row uses that same component-expanded path. The separate
eight-item set remains the final-inventory estimand, not the literal shopping queue.

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
- Schedule every required component in CORE by observed first-ownership net worth while
  keeping it before its parent. Preserve final-item order and inventory legality,
  reject candidates that require a repeated component card, and exclude every
  CORE-path item from optional rows.
- Prefer CUDA automatically for XGBoost when a runtime probe succeeds; retain explicit
  `cuda` and `cpu` overrides and record the resolved device in the experiment manifest.

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
- Projection regression proving a component appears in CORE, remains outside the final
  eight-item inventory, and cannot also appear in an optional row.

## Implementation record

- Build-evidence schema 2 sequence policy 3 exports chronologically scheduled,
  component-expanded defaults plus deterministic
  first/previous/position/popularity backoffs from training rows only.
- The existing XGBoost ranker remains a chronological challenger and cannot be
  promoted without a portable validated policy artifact, even when imitation metrics
  pass.
- `schemas/decision-state.schema.json` and `recommendation.py` provide one strict,
  deidentified patch/client/mode/rank/inventory/composition contract and return only
  buy, save, end, or abstain.
- Recommendation tests cover component credit, saving, sold/off-path history, backoff,
  sparse/unknown states, and exact evidence identity. Steam is never accessed.
- Live review on 2026-08-15 established that parent cards alone do not communicate the
  intended component queue: all 38 reviewed heroes had required component IDs displayed
  as optional. The shared projection now admits the validated component-expanded path;
  the frozen 38-hero regression spans 9–17 CORE purchase actions with zero optional
  overlap.
- Follow-up live review found that immediate-before-parent expansion still violated the
  row's earlier-to-later promise for components such as Kelvin's Mystic Expansion.
  Sequence policy 3 uses a dependency-safe chronological scheduler: timing is the
  priority, while component, final-order, capacity, and active-item constraints remain
  mandatory.
- A later UI review established that the static Steam row cannot communicate component
  rebuys without duplicate cards. Candidate selection now rejects any expanded path
  with a repeated item ID and chooses the next supported coherent final inventory.
- The earlier 2026-08-15 regeneration admitted all 38 heroes. An independent replay matched
  evidence, context, and projected CORE order for 38/38 heroes, resolved every path to
  its selected final eight, covered 190 component consumptions and seven legal rebuys,
  and found zero optional-row overlaps. The authorized stats-only install updated all
  38 managed builds from evidence `060bb289...5043cf4`; the decoded Steam cache matched
  every projected category, item order, annotation, and optional flag. Its recoverable
  backup is `20260815T165850Z`.
- The duplicate-free regeneration produced evidence `b64fa1eb...f29e4cc` and admitted
  38/38 heroes. Its audit found zero repeated CORE IDs, zero optional overlaps, exact
  scheduler/projection agreement, 183 legal component consumptions, and 38 valid final
  inventories. Reinstallation is deferred because Deadlock is running.
- XGBoost 3.3 uses `tree_method=hist` with the resolved `device`; a real one-round CUDA
  probe prevents an `auto` run from silently selecting an unavailable GPU.

Traceability: [usage audit](../deadlock-build-usage-audit.md#phase-3-sequence-and-deviation-research),
[deviation requirement](../deadlock-build-policy-requirements.md#req-pol-007--support-deviation-and-recalculation),
and [evaluation requirements](../deadlock-build-policy-requirements.md#10-evaluation-learning-and-monitoring).
