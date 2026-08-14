# Phase 4 — Situational policies

Status: planned

## Outcome

The policy can recommend a small, legal response to an observed threat only when the
mechanism, decision opportunity, comparator, support, overlap, and failure condition
are all proven.

## Decisions

- Use a versioned mechanics-first threat vocabulary: healing, bullet pressure, spirit
  pressure, control, mobility/escape, ally protection, and active/slot burden. Unknown
  threats abstain.
- Extend decision state with enemy heroes/items, allied heroes, and objectives. These
  values are inputs to recommendation, never inferred from raw matchup win rate.
- Generate candidates from pinned item mechanics, then compare only alternatives that
  were legal and similarly accessible at the same decision opportunity. Include save
  and the default continuation as comparators.
- Require minimum support 20, explicit overlap diagnostics, chronological stability,
  and bounded uncertainty. A failed gate emits a structured abstention, not generic
  counter prose.
- Encode each admitted branch as a typed guard plus `CounterCard` trigger, replacement,
  execution, and failure fields. Steam receives only compact optional cards; the full
  reasoning remains in the sidecar and `recommend` output.

## Work

- Add threat extraction/classification from pinned mechanics and composition state.
- Add decision-opportunity comparison, partial pooling, overlap/effective-support,
  stability, and abstention outputs to offline evidence.
- Materialize validated branches in the policy graph and extend narrative generation to
  explain only the closed branch contract.
- Add privacy-safe recommendation/deviation logging and drift checks without account IDs
  or Steam mutation.

## Proof

- Mechanics fixtures for every threat class plus false-positive/unknown cases.
- Comparative-state tests for illegal candidates, weak support, poor overlap, unstable
  windows, conflicting guards, replacements, full slots, and explicit save.
- DeepEval rejects invented threats, causal claims, missing comparators, and incomplete
  trigger/execution/failure instructions.
- Representative weapon, spirit, melee/tank, summon/support, and sparse/new heroes pass
  offline and authorized live acceptance without weakening validators.

Traceability: [usage audit](../deadlock-build-usage-audit.md#phase-4-situational-policies),
[counter requirement](../deadlock-build-policy-requirements.md#req-ana-012--require-mechanics-first-counter-evidence),
and [policy requirements](../deadlock-build-policy-requirements.md#6-build-policy-model-and-claim-control).
