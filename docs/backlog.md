# Backlog

## Restore useful tactical signals

Goal: bring back concise player-facing spike and curve guidance only when the
underlying telemetry can support it. Do not add generic prose or repeat facts
already shown by Deadlock's native item tooltip.

Keep the implementation evidence-first and deterministic:

- Collect joint item-ownership and ability-unlock state so a `POWER SPIKE` can name
  a verified state transition, its prerequisite, tactical conversion, and counterplay.
- Add landmark-at-risk estimates before emitting a live `CURVE RESPONSE`; match-ending
  duration buckets remain labeled as descriptive associations and cannot drive it.
- Render admitted spike/curve cards from typed policy data. If no card passes, omit
  the section instead of generating filler.
- Without an admitted hero-relative rationale, keep item hover additions limited to
  `PURCHASE WINDOW`, `WIN RATE`, and `PICK RATE`; rely on the game's native item
  description for mechanics.

Acceptance:

- A fixture with sufficient joint-state evidence renders one exact `POWER SPIKE`
  card; an outcome-only peak renders none.
- A fixture without landmark-at-risk data cannot emit `CURVE RESPONSE`.
- A full-roster build can be generated and installed without model calls or generic
  tactical filler.

## Close the stats-only review/install snapshot gap

Goal: make a stats-only install and `status` agree on the exact snapshot without
refetching mutable analytics between review and Steam mutation.

Keep it small:

- Persist the exact context, policies, and snapshot manifest produced by
  `install --without-narratives` before entering the Steam write boundary.
- Teach `status` that a deliberately narrative-free bundle is complete when its
  manifest records that mode; do not require an empty or fake narrative artifact.
- Never rebuild an installed identity from a later API response. Public analytics can
  backfill even behind a fixed upper timestamp, so compare against the persisted
  install manifest.

Acceptance:

- A stats-only install followed immediately by `status` reports current.
- A fixture where an API response backfills after review does not relabel the already
  installed coherent snapshot; it reports the newer evidence as a separate candidate.
- The same-run context/policy identities in the artifact directory exactly match the
  identities embedded in all managed Steam builds.
