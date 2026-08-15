# Phase 2 — Hover hierarchy

Status: feedback correction implemented, audited, and installed

## Outcome

Every item keeps the familiar compact analytics block. Reviewed hero-specific advice
may precede it, while Valve's native tooltip remains the sole generic mechanics
description.

## Decisions

- Limit generated CORE instructions to 165 UTF-8 bytes and the complete Steam
  annotation to 240 bytes. Reject, do not truncate, model output that exceeds its
  contract.
- Keep the native item description authoritative. Default to the compact analytics
  block `PURCHASE WINDOW`, `WIN RATE`, and `PICK RATE`; prepend only reviewed,
  hero-specific tactical guidance.
  Show an unavailable purchase window honestly when timing is missing.
- Do not repeat native mechanics with generic labels such as active use, active
  binding, imbue, upgrade, component consumption, or reference option.
- Never emit counter language without Phase 4 evidence.
- Keep category descriptions fixed and short; category summaries remain in the audit
  artifact but do not enumerate visible cards in the client.

## Work

- Add one byte-budgeted annotation composer shared by live generation and reviewed
  artifact loading.
- Keep unreviewed optional-item hovers stats-only.
- Tighten narrative schema/prompt validation and bump narrative identity.
- Add projection-utilization evaluation so every required narrative field has a
  declared player or audit consumer.

## Proof

- Golden UTF-8 boundary tests and missing/sparse window cases. Raw buyer win rate
  remains descriptive only, and pick rate means unique hero-player-match adoption.
- Regression coverage proves the complete stats block survives tactical composition.
- DeepEval contract, grounding, causal-language, action-order, byte-budget, and
  projection-utilization suites.
- Authorized screenshots verify no clipping at 2560×1440, lower 16:9, and ultrawide.

## Implementation record

- Narrative schema 6 / prompt 22 requires a complete, uncorrupted primary-role
  sentence and enforces 165-byte item instructions; the shared composer enforces the
  240-byte Steam annotation ceiling without truncation.
- CORE annotations lead with exact reviewed hero-specific action prose when it fits.
  Optional reference items contain only the stats block; an admitted conditional
  action may add reviewed hero-specific guidance.
- `NARRATIVE_FIELD_SURFACES` declares the consumer for every generated field family,
  and `ProjectionUtilizationMetric` enforces the declaration in the production suite.
- Prompt 22 validates conditional trigger, comparator, replacement, execution, and
  failure-condition identity in addition to the original CORE contract.
- On 2026-08-13, the 11-case prompt run admitted 9 responses on their first attempt;
  Shiv and Vindicta passed unchanged immediate rechecks. All 11 admitted responses
  passed contract, closed-policy, evidence-language, and projection-utilization
  metrics (44/44), while preserving the validator's fail-closed behavior.
- On 2026-08-14, the prompt-22 run admitted 10 responses on the first full attempt;
  Grey Talon passed unchanged on the third bounded attempt after two drafts were
  correctly rejected for making an optional tier automatic. All 11 admitted responses
  passed the same 44/44 production metrics.
- Live-client review on 2026-08-14 found the deterministic mechanics labels redundant
  with Valve's item tooltip. The correction removed that classifier and restored the
  three-line analytics block for every item.
- The 2026-08-15 stats-only reinstall decoded cleanly for all 38 managed builds: every
  item retained exactly `PURCHASE WINDOW`, `WIN RATE`, and `PICK RATE`, with no generic
  mechanics label added.

Traceability: [usage audit](../deadlock-build-usage-audit.md#phase-2-hover-hierarchy)
and [annotation requirement](../deadlock-build-policy-requirements.md#req-rnd-006--keep-annotations-actionable-and-bounded).
