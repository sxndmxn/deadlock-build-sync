# Backlog

## Generate hero narratives concurrently

Goal: fan out independent hero-generation pipelines asynchronously instead of
waiting for all kit and synthesis calls one hero at a time. Permit full-roster
concurrency when Codex service limits allow it, with a bounded default that avoids
turning rate limits into repeated failures.

Keep the safety and reproducibility contracts intact:

- Run each hero's kit stage before that hero's synthesis stage, while allowing
  different heroes to progress concurrently.
- Use bounded, configurable concurrency with rate-limit backpressure, jittered
  retries, and `Retry-After` support; do not assume 38 simultaneous requests are
  always accepted by the service.
- Preserve per-stage fingerprints and reuse compatible completed artifacts after a
  retry or interrupted run.
- Validate every response independently and write progress atomically. One rejected
  hero must not corrupt or discard already validated hero artifacts.
- Preserve deterministic roster ordering in the final artifact regardless of request
  completion order.
- Keep the all-roster admission gate before Steam mutation: no cache write occurs
  until every eligible hero has a valid kit and synthesis result.

Acceptance:

- A concurrency test proves more than one independent hero request can be in flight
  while synthesis never starts before its matching kit result.
- A simulated 429 lowers request pressure and retries only the affected work without
  losing completed artifacts.
- An interrupted run reuses every fingerprint-compatible stage on restart.
- Serial and concurrent runs over fixed fixtures produce the same ordered artifact
  identities and validation results.
- A full-roster benchmark records wall-clock improvement and peak concurrency without
  performing a live Steam write.

## Make item notes hero-relative or omit them

Goal: every AI-authored item note must answer why that item belongs on that hero.
Never force a note merely because an item appears in the deterministic build.

Keep the contract narrow:

- Admit a note only when supplied evidence connects an item mechanic to a named hero
  ability, an explicit scaling hook, or a documented limitation in that hero's kit.
- Treat item mechanics as evidence for the relationship, not prose to paraphrase. The
  native hover already explains what the item does.
- Make action explanations an ordered optional subset of deterministic policy actions.
  If no grounded hero-relative reason exists, omit the AI annotation and retain only
  deterministic purchase-window and cohort statistics.
- Require every admitted note to name the item and its hero-specific reference. Reject
  generic usage advice, isolated tooltip descriptions, and near-copies of native item
  text.
- Keep models outside selection and ordering: they may explain an admitted relationship
  but cannot add, remove, replace, or reorder build items.

Acceptance:

- The current Infernus `Dispel Magic` tooltip paraphrase is rejected; its replacement
  must name a supplied Infernus-specific interaction or be omitted.
- A hero/item fixture with a supplied ability synergy, kit-gap response, or scaling hook
  renders one concise note describing that relationship.
- A fixture with item mechanics but no hero-relative support renders no AI item note.
- Full-roster prompt and reliability evals reject tooltip-only prose without weakening
  existing policy, evidence, or byte-limit validation.

## Restore useful tactical signals

Goal: bring back concise player-facing spike and curve guidance only when the
underlying telemetry can support it. Do not spend model calls on generic prose or
repeat facts already shown by Deadlock's native item tooltip.

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
- Any optional Codex review uses `gpt-5.6-luna` only and cannot change deterministic
  item selection, order, labels, or admission decisions.

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
