# Phase 4 — Situational policies

Status: implemented; fresh August 12 evidence correctly emitted only abstentions

## Outcome

The policy can recommend a small, legal response to an observed threat only when the
mechanism, decision opportunity, comparator, support, overlap, and failure condition
are all proven.

## Decisions

- Use a versioned mechanics-first threat vocabulary: healing, bullet pressure, spirit
  pressure, control, mobility/escape, ally protection, and active/slot burden. Unknown
  threats abstain.
- Extend decision state with whole-team and same-lane enemy heroes, enemy items, allied
  heroes, and objectives. These values are inputs to recommendation, never inferred
  from raw matchup win rate.
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

## Implementation record

- Evidence schema 8 admits only branches with an exact enemy scope, match phase, price
  tier, and enemy-mechanic reference. It requires a same-opportunity comparator, at
  least 20 target and comparator observations in training, validation, and untouched
  test, positive estimates in all three folds, and a bounded train-to-validation
  difference. Base descriptions and important active properties are the only mechanics
  inputs; hidden minor stats, resistance reduction, and upgrade-only ability text do not
  qualify.
- The producer compares items within the same hero, enemy scope, price tier, and match
  phase, retaining the existing partial pooling and overlap diagnostics. Every candidate
  and gate remains in `candidate_audit`; failed comparisons emit explicit abstentions.
- Admitted branches enter one typed choice with conjunctive threat, exact enemy-scope,
  and phase guards plus a `CounterCard`. The default still enters CORE, while optional
  tier cards receive only their compact validated conditional instruction. Player text
  names the threat, while enemy identity remains in the guards and audit evidence.
- The read-only recommender combines explicit threats with conservative pinned
  enemy-item mechanics, recognizes four-active slot burden, rejects unknown items or
  conflicting branches, filters illegal purchases, and exposes the admitted contract.
- Prompt 22 rejects changed identities, invented threats, causal language, missing
  comparators, and incomplete trigger/replacement/execution/failure instructions.
- The synthetic admitted-branch DeepEval case passed all four production metrics;
  deterministic negative fixtures exercise every conditional omission and identity
  failure without weakening admission.
- Existing privacy-bounded `RecommendationEvent` and monitoring/drift contracts remain
  the only feedback path; account IDs and other personal fields are rejected.
- The frozen August 12–14 production cohort produced 38 policies with zero admitted
  counter cards; each unsupported candidate remained an explicit abstention instead of
  becoming client prose.

Traceability: [usage audit](../deadlock-build-usage-audit.md#phase-4-situational-policies),
[counter requirement](../deadlock-build-policy-requirements.md#req-ana-012--require-mechanics-first-counter-evidence),
and [policy requirements](../deadlock-build-policy-requirements.md#6-build-policy-model-and-claim-control).
