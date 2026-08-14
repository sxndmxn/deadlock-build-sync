# Phase 2 — Hover hierarchy

Status: implemented; screenshot/clipping matrix awaits explicit authorization

## Outcome

CORE hovers lead with hero-specific action, every option states a mechanically proven
job, and observational context remains compact and subordinate.

## Decisions

- Limit generated CORE instructions to 165 UTF-8 bytes and the complete Steam
  annotation to 240 bytes. Reject, do not truncate, model output that exceeds its
  contract.
- Format CORE as action first, then `Usually <window> • adopted <rate> (n=<eligible>)`.
  Omit unavailable or weak timing instead of substituting outcome rate.
- Classify optional items only into mechanics-backed jobs: anti-heal, bullet defense,
  spirit defense, mobility, ally protection, active use, imbue, upgrade, or slot
  consolidation. Use the neutral “reference option” label when no rule matches.
- Show active, imbue, sell, flex, component, and replacement burdens only when those
  fields are actually encoded. Never emit counter language without Phase 4 evidence.
- Keep category descriptions fixed and short; category summaries remain in the audit
  artifact but do not enumerate visible cards in the client.

## Work

- Add one byte-budgeted annotation composer shared by live generation and reviewed
  artifact loading.
- Add deterministic mechanics-job classification from pinned structured assets.
- Tighten narrative schema/prompt validation and bump narrative identity.
- Add projection-utilization evaluation so every required narrative field has a
  declared player or audit consumer.

## Proof

- Golden UTF-8 boundary tests, missing/sparse window cases, and no raw `Win rate` or
  misleading `Pick rate` in any default hover.
- Mechanics classifier fixtures for each supported job and neutral abstention.
- DeepEval contract, grounding, causal-language, action-order, byte-budget, and
  projection-utilization suites.
- Authorized screenshots verify no clipping at 2560×1440, lower 16:9, and ultrawide.

## Implementation record

- Narrative schema 5 / prompt 21 enforces 165-byte item instructions; the shared
  composer enforces the 240-byte Steam annotation ceiling without truncation.
- CORE annotations lead with exact hero-specific action prose. Optional annotations
  use explicit mechanics jobs and report active, imbue, replacement, flex, component,
  and consolidation burdens only when present.
- `NARRATIVE_FIELD_SURFACES` declares the consumer for every generated field family,
  and `ProjectionUtilizationMetric` enforces the declaration in the production suite.
- Prompt 21 validates conditional trigger, comparator, replacement, execution, and
  failure-condition identity in addition to the original CORE contract.
- On 2026-08-13, the 11-case prompt run admitted 9 responses on their first attempt;
  Shiv and Vindicta passed unchanged immediate rechecks. All 11 admitted responses
  passed contract, closed-policy, evidence-language, and projection-utilization
  metrics (44/44), while preserving the validator's fail-closed behavior.

Traceability: [usage audit](../deadlock-build-usage-audit.md#phase-2-hover-hierarchy)
and [annotation requirement](../deadlock-build-policy-requirements.md#req-rnd-006--keep-annotations-actionable-and-bounded).
