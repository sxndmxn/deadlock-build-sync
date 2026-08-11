# deadlock-build-sync

[![CI](https://github.com/sxndmxn/deadlock-build-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/sxndmxn/deadlock-build-sync/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Linux CLI that creates private Deadlock hero builds from
[deadlock-api.com](https://deadlock-api.com) analytics and installs them under
**My Builds**.

Design evidence and implementation contracts:

- [Strategy-description research](docs/deadlock-strategy-description-research.md) — source evidence, analytical rationale, and build-policy findings.
- [Build-policy requirements](docs/deadlock-build-policy-requirements.md) — staged normative requirements, acceptance criteria, and verification evidence.

Every run resolves one client version, freezes one as-of cutoff, and records
Ranked or Unranked as an explicit cohort identity. Exact response bytes, patch
identity, independent mechanics/matchmaking/map/telemetry epochs, rank-label
mapping, route grain, and fallback behavior are captured in a reusable snapshot
manifest.

The rich output is a typed, snapshot-bound policy graph:

- A mechanically legal level/AP ability timeline selected from equivalent reached
  legal states, with support reported at each decision. Price tiers are never treated
  as equal “quarters” of that timeline.
- A coherent eight-item final-inventory path selected by joint player-match support,
  ordered by observed acquisition time, and kept within the hero's median final net
  worth.
- Four ten-item price-tier reference menus selected by true player-match adoption and
  ordered left to right by observed first-ownership net worth. Outcome rate is
  descriptive only and never selects or orders an item.
- Evidence objects that name their actual unit and claim class. Item adoption uses
  unique first ownership over eligible player-matches; adopter outcome rate remains
  descriptive—not an item effect or causal win-rate improvement.
- Lane and whole-enemy-team matchup scopes kept separate, with mechanics-first
  counters and structured abstention when support or mechanics are inadequate.
- An ending-duration profile that describes games ending in each phase. It is not
  a live power curve and never justifies stalling an available close.

Steam receives five rows in a fixed order: `CORE ITEMS`, `TIER 1`, `TIER 2`,
`TIER 3`, and `TIER 4`. Only the eight-item core enters Queue. Each tier row is an
optional ten-item reference menu, not a claim that all ten items should be bought or
that popularity proves a situational counter. Standard row descriptions stay short,
and each evidence-backed item shows only its observed purchase window, adopter win
rate, and player-match pick rate. Deterministic code validates the core against
components, slots, active bindings, flex unlocks, ability currency, and current
item/ability qualifiers before serialization.

Codex writes explanations only after those decisions are closed. The narrative
artifact must copy the exact snapshot, policy, action, evidence, and projection
category identities. It cannot add purchases, change guards, strengthen a claim,
or redefine Queue behavior.

## Requirements

- Linux with Steam and Deadlock installed
- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- An authenticated [`codex`](https://developers.openai.com/codex/cli/) CLI for
  the separate narrative-generation stage

Deadlock must be closed before installing or restoring a cache.

## Install

Clone a release checkout and install the CLI into an isolated uv tool
environment:

```bash
git clone https://github.com/sxndmxn/deadlock-build-sync.git
cd deadlock-build-sync
uv tool install .
deadlock-build-sync sync
```

To upgrade after pulling a newer release, run `uv tool install --force .`.
The separate `codex` CLI must already be authenticated. Close Deadlock before
running `sync`; the command refuses to write while the game is open.

`sync` also requires a validated `build-evidence.json` from the offline
player-match analysis pipeline. Its default location is
`$XDG_STATE_HOME/deadlock-build-sync/artifacts/build-evidence.json` (or
`~/.local/state/deadlock-build-sync/artifacts/build-evidence.json`). Use
`--build-evidence PATH` to review another artifact. The CLI rejects edited or
incompatible patch, client, asset, rank-label, rank-range, mode, epoch, cutoff, or
roster identities; it never falls back to aggregate purchase-event rankings.

Steam discovery supports native (`~/.local/share/Steam`), legacy
(`~/.steam/steam` and `~/.steam/root`), Flatpak, and Snap installations. A
legacy symlink to the native installation is deduplicated. If more than one
real cache remains, select it with `--account-id` or `--cache-path`.

## Development

The default uv development group includes Pytest, Ruff, and ty. Validate a
checkout with:

```bash
uv lock --check
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv pip check
uv build
```

## Prompt evaluation

DeepEval exercises the exact production kit-analysis and closed-policy explanation
stages against representative heroes from the latest exported context. It reports
the production contract, complete policy/category coverage, evidence-language
ceiling, and repeated-generation structural stability separately:

```bash
uv run deepeval test run tests/evals/test_narrative_prompt.py
uv run deepeval test run tests/evals/test_narrative_reliability.py
```

Both commands require an authenticated `codex` CLI and a current
`generated/strategy-context.json` from `export-context`. Set
`DEADLOCK_BUILD_SYNC_EVAL_CONTEXT` to evaluate another exported context, such
as the artifact produced by `sync`. Every call has a two-minute timeout.
Evaluation results remain local unless the user explicitly configures Confident AI.

The deterministic evaluation layer additionally implements patch-forward,
player/match-group-safe splits; popularity baselines; Brier/log-loss/calibration
and selective risk; predeclared target trials; IPS, self-normalized IPS, doubly
robust OPE with support and clipping diagnostics; privacy-bounded recommendation
events; and monitoring/rollback rules. See the
[coverage manifest](docs/evaluation-coverage.json),
[sample layer-separated report](docs/evaluation-sample-report.json), and
[monitoring runbook](docs/monitoring-runbook.md).

## Patch workflow

The normal workflow is one command. Close Deadlock, then run:

```bash
uv run deadlock-build-sync sync
```

`sync` discovers the local Steam account, generates every eligible hero from one
coherent snapshot, builds an ability-only kit profile with `gpt-5.6-luna`, explains
the closed policy with `gpt-5.6-sol`, validates every artifact, backs up the cache,
and installs the private builds. An all-hero run refuses installation if any pinned
eligible hero lacks a complete policy. Reusable artifacts live under
`$XDG_STATE_HOME/deadlock-build-sync/artifacts` (or
`~/.local/state/deadlock-build-sync/artifacts`). Use `--hero NAME` for one hero,
`--artifacts DIR` to select another artifact directory, or
`--force-narratives` to regenerate both model stages. A failed model or
semantic-validation attempt is retried up to three times per stage; change that
bound with `--max-attempts N`.

### What is cached

`sync` consumes five reviewable artifacts: the deterministic build evidence, exact
strategy context, rich typed policy sidecar, kit profiles, and final explanations.
Every artifact carries the source manifest or snapshot identity. A narrative is reusable only when its
snapshot, policy, context, narrative basis, prompt, and model contract are exactly
compatible. Changed or malformed entries regenerate; `--force-narratives` bypasses
model-output reuse.

This artifact cache is separate from Steam's
`cached_hero_builds.kv3`, which is user-owned game data. The Steam file is never
used as an AI cache: it is discovered only after generation, backed up, updated
through a validated temporary file, and atomically replaced.

When reviewed full-roster build evidence, context, policy sidecar, and narratives
already exist in the artifact directory, `install-artifacts` installs that exact
bundle without refetching mutable analytics or invoking a model. It reconstructs
player-facing item statistics from the fingerprinted `build-evidence.json` and
recomputes every file, snapshot, policy, projection, cohort, patch, and coverage
fingerprint before entering the same guarded Steam backup and atomic-replacement
boundary.

The individual commands remain available for review and debugging:

```bash
# 1. Export the exact evidence context and rich policies Codex may explain
uv run deadlock-build-sync export-context --all \
  --build-evidence ~/.local/state/deadlock-build-sync/artifacts/build-evidence.json \
  --output generated/strategy-context.json

# 2. Generate a reviewable, schema-constrained narrative artifact.
#    This invokes `codex exec` separately; the sync/install process never does.
uv run python scripts/generate_narratives.py \
  --input generated/strategy-context.json \
  --output generated/narratives.json

# 3. Review strategy-context.json, policies.json, and narratives.json, then preview.
uv run deadlock-build-sync preview --hero kelvin

# 4. Install all private builds after closing Deadlock
uv run deadlock-build-sync install --all

# Or install the exact already-reviewed state artifact bundle without a refetch
uv run deadlock-build-sync install-artifacts

# Restore the most recent cache backup
uv run deadlock-build-sync restore --latest
```

Use `--narratives PATH` to select another reviewed artifact. A missing, stale,
cross-mode, cross-policy, or incomplete artifact stops preview or installation.
`--without-narratives` omits prose only; deterministic policy and Steam safety
validation still apply.

## Rank cohorts

Every analytics endpoint uses one validated rank range. Following the current
Ranked calibration reset, the default is `emissary-i` through `eternus-v`.
Override either boundary with symbolic
rank names only when the build-evidence artifact was exported for the same range:

```bash
uv run deadlock-build-sync preview --all \
  --min-rank oracle-iii \
  --max-rank ascendant-vi
```

Current tiers are `initiate`, `seeker`, `acolyte`, `sentinel`, `mystic`,
`ritualist`, `emissary`, `oracle`, `phantom`, `ascendant`, and `eternus`.
Pre-rename aliases still parse when unambiguous, but numeric badge IDs are identity
and labels come from the pinned rank asset. Divisions accept `i`–`vi` or `1`–`6`.
The numeric range and label-map hash appear in the manifest, preview, backup, and
in-game description.

`export-context` produces a per-hero closed evidence packet containing:

- Structured lore/role/playstyle, scaling, level information, complete ability and
  item properties, component relationships, and category-investment breakpoints.
- A legal ability timeline with earliest level, currency cost/balance, and
  reached-state support for every projected action—without a `quarter` field.
- True first-ownership adoption with eligible player-match denominators, raw event
  counts kept separately, observed acquisition time/net-worth distributions, and
  descriptive adopter outcome rates.
- Separate lane and whole-team matchup rows, an ending-duration estimand, the typed
  policy graph, the compact projection contract, and interpretation constraints.
- Layered mechanics, analytics, policy, narrative, projection, and whole-document
  fingerprints bound to the complete source manifest.

Every hero requires a supported, mechanically legal eight-item core at or below its
median final net worth, ten adoption-ranked items in each price tier, complete current
mechanics, a complete ability projection, a duration estimate or explicit duration
abstention, and policy validation. Core items may intentionally reappear in their
native tier row. Every omission receives a structured exclusion; all-hero installation
fails on any exclusion rather than silently shipping a partial roster.

The Codex response is constrained by
[`schemas/narrative-response.schema.json`](schemas/narrative-response.schema.json).
Installation rejects an artifact when patch identity, snapshot, client version,
match mode, rank labels, policy, context, narrative basis, prompt, hero coverage,
or projection categories differ. Advancing raw evidence creates a new context; it
does not silently reuse prose merely because a patch title stayed the same.

The CLI discovers the Deadlock Steam Cloud cache automatically when there is a
single local Steam account. Use `--account-id` or `--cache-path` to disambiguate
multiple accounts.

## Safety model

- Refuses cache changes while Deadlock is running.
- Fetches and validates every requested guide before touching the cache.
- Never invokes Codex while reading or changing Steam data.
- Recomputes exported source and per-hero fingerprints before invoking Codex,
  so a context edited after export is rejected.
- Rejects stale, cross-cohort, incomplete, or policy-changing Codex artifacts.
- Creates a timestamped backup of `cached_hero_builds.kv3` and
  `remotecache.vdf`.
- Writes a temporary KV3 file, decodes and validates it, atomically replaces the
  cache, fsyncs the file and directory, and decodes the installed bytes again.
- Fingerprints every out-of-scope KV3 section before and after mutation; a mismatch
  restores the backup or reports the exact backup path if restoration also fails.
- Preserves favorites, selected builds, saved builds, and unrelated private
  builds.
- Reruns update only entries carrying the `[deadlock-build-sync:v1]` marker.
- Never publishes a build or connects to Deadlock's Game Coordinator.

## Contributing and support

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow. Report
bugs and request features through [GitHub Issues](https://github.com/sxndmxn/deadlock-build-sync/issues).
Please report security vulnerabilities privately as described in
[SECURITY.md](SECURITY.md).

## License and affiliation

Released under the [MIT License](LICENSE).

This is an independent community project. It is not affiliated with, endorsed
by, or sponsored by Valve Corporation. Deadlock, Steam, and their associated
marks are property of their respective owners.
