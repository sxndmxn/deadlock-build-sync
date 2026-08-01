# Repository Mission

`deadlock-build-sync` is a Linux-first CLI that turns current Deadlock analytics
into private, tactically grounded hero builds and installs them safely under
Steam's **My Builds**. The primary user path is:

```bash
deadlock-build-sync sync
```

The project succeeds when that command can generate, validate, back up, and
install every eligible guide without corrupting or discarding user-owned Steam
data.

## Non-negotiable invariants

- Treat Steam files as user data. Refuse writes while Deadlock is running,
  create a recoverable backup, validate a temporary replacement, and replace
  atomically.
- Preserve favorites, saved builds, selected builds, and unrelated private
  builds. Update only entries carrying the managed marker.
- Keep AI generation outside the Steam mutation boundary. Models interpret
  exported evidence; deterministic code owns collection, fingerprints,
  validation, serialization, and installation.
- Ground tactical prose in supplied hero abilities, ability order, item
  mechanics, purchase windows, rank cohort, patch, match counts, and duration
  evidence. Never invent mechanics or claim analytics prove causation.
- Reject incomplete heroes and stale or malformed artifacts. Do not weaken a
  validator merely to make a generated response pass.
- Keep `sync` safe to rerun. Reuse fingerprint-compatible artifacts and make
  managed build updates idempotent.

## Architecture boundaries

- `api.py`, `purchase_guide.py`, `ability_order.py`, and `power_curve.py` own
  deterministic analytics.
- `strategy_context.py` owns exported evidence and fingerprints.
- `scripts/generate_narratives.py` owns staged Codex generation and semantic
  response validation.
- `narratives.py` admits reviewed artifacts into guides.
- `protobuf.py`, `kv3_binary.py`, and `cache.py` form the high-risk Steam write
  boundary.
- `cli.py` orchestrates user workflows; keep the zero-argument `sync` path
  obvious and preserve the lower-level review/debug commands.

## Change and release bar

- Add a regression test for every correctness or safety fix.
- Run the complete local gate before handoff:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv pip check
uv build
```

- For prompt or validator changes, run the relevant DeepEval suite or clearly
  report why a model-backed eval was not run.
- For packaging changes, inspect and smoke-test the built wheel outside the
  source checkout.
- Never run a live Steam sync unless the user explicitly authorizes it. Report
  the artifact directory, cache path, backup path, created/updated counts, and
  skipped heroes after a live run.
