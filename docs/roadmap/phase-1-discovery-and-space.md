# Phase 1 — Discovery and space

Status: planned

## Outcome

Every build has three resolved tags, a useful archetype title, and four compact
optional menus that never repeat CORE merely to fill space.

## Decisions

- Fetch the 14-entry build-tag catalog for the pinned client, validate class names and
  nonzero IDs, hash it into the snapshot, and encode exactly three repeated protobuf
  field-11 values.
- Select the axis tag from CORE catalog investment by slot with a stable
  Weapon → Spirit → Vitality tie-break. Select the function tag only from explicit
  mechanics rules; use Utility when no more specific rule is proven. Use Intermediate
  as the conservative audience tag.
- Build the archetype from the validated function and axis labels, then render
  `<archetype> | <queue> | <YYYY-MM-DD>` within 50 characters. Fall back to
  `Evidence Default` only when classification abstains.
- Exclude all CORE IDs before tier ranking. Require at least 20 adopter matches, retain
  observed-time ordering, return up to ten items, and never add weak filler.
- Preserve the exact five names, geometry, optional flags, and CORE-only Queue behavior.

## Work

- Add typed tag catalog/admission and deterministic tag/archetype selection.
- Add tag identity to source records, manifests, contexts, bundles, previews, and
  compatibility checks.
- Relax tier rows from exactly ten to one-through-ten items and enforce global
  CORE-versus-tier disjointness through live and reviewed-artifact paths.
- Encode/decode title and tags in protobuf without moving any mutation logic.

## Proof

- Golden field-11 decode tests with exactly three valid IDs and no zero placeholders.
- Deterministic classifier/tie/fallback/title-length tests.
- Tier sparsity, support, ordering, and disjointness tests across direct generation,
  artifact loading, preview, and round trip.
- Live preview confirms resolved badges only after explicit authorization.

Traceability: [usage audit](../deadlock-build-usage-audit.md#phase-1-tags-titles-and-duplicate-space)
and [rendering requirements](../deadlock-build-policy-requirements.md#7-valve-rendering-and-guide-ux).
