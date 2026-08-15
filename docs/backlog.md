# Backlog

## Opt-in execution tracing

Goal: make end-to-end data flow inspectable without scattering `print()` calls
through every function or changing normal CLI output.

Keep the first version small:

- Add `--trace stages|calls` plus an equivalent environment variable.
- `stages` records pipeline boundaries, artifact IDs, row counts, paths, durations,
  and success/failure as JSON Lines.
- `calls` uses Python's profiling hook to capture call, return, exception, and elapsed
  time automatically for `deadlock_build_sync` modules only. Do not instrument each
  function by hand.
- Never record arguments, return values, account IDs, match IDs, inventory contents,
  environment variables, or model prompts by default.
- Write traces under the state directory in a timestamped run folder; print that path
  once at command completion.
- Keep tracing disabled by default and test that enabling it cannot change artifacts,
  fingerprints, policy decisions, or Steam output.

Acceptance:

- A traced one-hero preview shows the path from evidence admission through policy,
  projection, presentation, and protobuf serialization.
- Every entered project function has a matching return or exception event.
- Stage tracing adds negligible overhead; call tracing documents its expected debug-only
  overhead and bounded file-size behavior.
- A small trace summarizer renders the call tree and per-function elapsed time without
  requiring changes to production functions.

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
- Keep item hover additions limited to `PURCHASE WINDOW`, `WIN RATE`, and `PICK RATE`;
  rely on the game's native item description for mechanics.
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
