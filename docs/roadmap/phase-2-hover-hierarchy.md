# Phase 2 — Hover hierarchy

Status: planned

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

Traceability: [usage audit](../deadlock-build-usage-audit.md#phase-2-hover-hierarchy)
and [annotation requirement](../deadlock-build-policy-requirements.md#req-rnd-006--keep-annotations-actionable-and-bounded).
