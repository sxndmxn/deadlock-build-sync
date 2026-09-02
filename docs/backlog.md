# Backlog

## Restore useful tactical signals

Goal: bring back concise player-facing spike and curve guidance only when the
underlying telemetry can support it. Do not add generic prose or repeat facts
already shown by Deadlock's native item tooltip.

Delivered: a mechanics-only `POWER SPIKE` hover line on `CORE ITEMS` and tier rows.
It matches an important item stat to a hero ability scale function and names up to
two abilities with the spirit coefficient. Item win rate is not a spike signal. In
the current cohort it correlates 0.51 with cost, 0.46 with buy time, and follows the
team net-worth lead at purchase (25% behind, 72% ahead). No outcome statistic
selects, orders, or admits the line.

Still open:

- Collect joint item-ownership and ability-unlock state so a `POWER SPIKE` can name
  a verified state transition, its prerequisite, tactical conversion, and counterplay.
  The warehouse `match_player` table exposes `stats.ability_points` and `stats.level`
  beside `stats.time_stamp_s`, but the offline extract pulls neither. Adding them
  makes boons per minute and ability rank at a landmark observable, which is what an
  `acquisition_state` with a level range needs.
- Enforce Steam's 200-character limit on every note. Nine `TIER 4` cards exceed it
  today; only the spike decision respects the limit.
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
