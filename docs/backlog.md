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
