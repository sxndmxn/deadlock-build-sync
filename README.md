# deadlock-build-sync

[![CI](https://github.com/sxndmxn/deadlock-build-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/sxndmxn/deadlock-build-sync/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`deadlock-build-sync` creates private Deadlock hero builds from [Deadlock API](https://deadlock-api.com) analytics.
It installs validated builds under Steam's **My Builds**.
The Rust CLI primarily supports Linux.
It uses synchronous I/O, deterministic generation, and guarded Steam transactions.

## Install

A source build requires Rust 1.92.0 and a C++ compiler for bundled DuckDB.
Rustup selects the pinned toolchain from this checkout.
Install the complete CLI from the workspace:

```bash
git clone https://github.com/sxndmxn/deadlock-build-sync.git
cd deadlock-build-sync
cargo install --path crates/deadlock-build-sync --features analysis --locked
```

The `analysis` feature supplies `refresh-evidence`.
It includes DuckDB, numerical optimization, and Leiden discovery.
For a machine that only consumes reviewed evidence, omit `--features analysis`.
That binary retains every other command and rejects evidence refresh with an explicit feature error.
The application does not require Python or an asynchronous runtime.

The release workflow packages a Linux AMD64 executable with analysis enabled.
After extracting its archive, install the executable into a directory on your `PATH`:

```bash
mkdir -p ~/.local/bin
install -m 755 deadlock-build-sync ~/.local/bin/deadlock-build-sync
```

## Generate and install builds

Generate the current evidence before the first sync:

```bash
deadlock-build-sync refresh-evidence
```

Close Deadlock before installation.
Install every eligible hero with:

```bash
deadlock-build-sync sync
```

`sync` generates descriptions, validates the complete artifact bundle, creates a recoverable cache backup, and installs managed builds.
It preserves favorites, selected builds, saved builds, and unrelated private builds.
It refuses a write while Deadlock runs or process inspection fails.
A repeated unchanged update leaves the cache bytes unchanged.

Steam discovery supports native, legacy, Flatpak, and Snap locations.
Duplicate symlink locations resolve to one cache.
Use `--account-id` or `--cache-path` when multiple real caches remain.
Steam writes require Linux process inspection.
Read-only generation and artifact review also work on macOS.

Build without Steam access:

```bash
deadlock-build-sync build --hero kelvin
```

Omit `--hero` to generate every eligible hero.
Use `--details` for complete optional routes.
Use `--format json` for structured output.
Use `--artifacts DIR` to select the output directory.

Hero subsets preserve the main artifact directory and its full-roster evidence.
For `--artifacts /path/artifacts`, subset builds use `/path/artifacts-subsets/HERO_ID`.
The default directory follows the same rule.
`build` reports the subset index path, and `sync` reports the subset artifact directory.
Use that directory with `install-artifacts --artifacts DIR` to install the subset bundle.

## Evidence and guide rules

Each snapshot pins the client version, patch, cutoff, rank labels, cohort, assets, roster, and independent epochs.
The recorder retains exact API response bytes.
Edited, stale, incomplete, or incompatible artifacts fail admission.
A failed build preserves the previous artifact bundle.

Eclat discovers supported exact item cores.
Leiden groups related cores.
Whole matches enter separate discovery, selection, validation, and reserved test partitions.
Eligible matches require 12 distinct player slots and 12 distinct heroes.
Candidates, paths, groups, pools, and branch conditions freeze before validation.
Reserved test data does not determine admission.

Each admitted identity retains a complete legal component path.
Related identities share a guide group with a default Queue and manual variants.
Automatic substitutions require separate checkpoint evidence.
Unsupported timing remains unknown.
The planner accounts for component ownership, rebuy costs, item slots, active bindings, flex slots, and ability currency.

Descriptions use the supplied hero kit, legal ability order, item mechanics, purchase windows, cohort, patch, support, and match duration.
Generation does not use a model.
Observed buyer results do not establish item effects or improved match outcomes.
The ending-duration profile describes completed matches rather than live power.

Item hover cards use this format:

```text
SOUL WINDOW: 2k - 15k
PR: 80.6% | WR: 49.0% | TOTAL GAMES: 12,611
```

`SOUL WINDOW` is the middle half of buyer net worth at purchase.
`PR` is item adoption across the hero cohort.
`WR` is observed buyer win rate.
`TOTAL GAMES` is its buyer match count.
Admission recomputes each card from its evidence.

Eclat / Leiden generates all builds.

## Evidence refresh

`refresh-evidence` downloads and analyzes a fixed public cohort.
It does not discover or modify Steam data.
DuckDB installs its ICU, DuckLake, and HTTPFS extensions when they are absent from its extension cache.
Extraction uses UTC for timestamp parameters and match cutoff calculations.
Extraction defaults to 12 GB of database memory and eight database threads.
Use `--extraction-memory-mb N` to set the extraction memory limit in decimal megabytes.
Use `--extraction-threads N` to set extraction database threads.
Both values must be positive integers.
These options apply to new extraction runs; resume reuses completed extraction.

The default worker count is eight.
Each worker uses a standard thread, a separate DuckDB connection, and one database execution thread.
Workers take the next hero from a shared queue.
Validation starts larger estimated workloads first, using frozen candidate counts and discovery support.
Results retain the source hero order.
Each connection has a 512 MiB database memory limit.
Use `--workers N` to reduce concurrent hero work.
This option does not change extraction limits.
Total memory also includes source records and numerical matrices.

Runs reside under the application's `offline/results` directory.
After discovery completes, resume validation with the original run and cohort settings:

```bash
deadlock-build-sync refresh-evidence --resume --run-id RUN_ID
```

Resume requires unchanged source files, candidate fingerprints, guide groups, generator, rank options, timestamps, and Rust implementation identity.
Python discovery checkpoints require a new extraction run.
Compatible reviewed evidence artifacts remain readable.

The default rank range is `emissary-i` through `eternus-v`.
`--rank-expansion auto` permits the documented per-hero expansion when support is insufficient.
Use `--rank-expansion off` to prohibit expansion.
Use the same rank options for refresh and generation.

## Artifacts and review commands

The default artifact directory is `$XDG_STATE_HOME/deadlock-build-sync/artifacts`.
When `XDG_STATE_HOME` is absent, the CLI uses `~/.local/state/deadlock-build-sync/artifacts`.
`build-evidence.json`, `strategy-context.json`, `policies.json`, and `narratives.json` form the reviewed bundle.
`builds.json` points to the snapshot's Markdown index, detailed guides, and `guides.json`.

A selected hero subset receives its own evidence identity.
Its `source_artifact_id` identifies the admitted parent evidence.
Every included hero must still pass complete coverage and fingerprint checks.

| Command | Purpose |
| --- | --- |
| `sync` | Generate, validate, back up, and install every eligible guide |
| `build` | Generate Markdown, JSON, policies, and descriptions without Steam |
| `status` | Check artifact and installed-build freshness |
| `refresh-evidence` | Extract and produce evidence with the analysis feature |
| `quality-report` | Check guide quality and optional independent replay |
| `preview` | Display generated guides for an explicit hero selection |
| `install` | Install guides for an explicit hero selection |
| `install-artifacts` | Install a reviewed bundle without new analytics requests |
| `export-context` | Export strategy context and typed policies |
| `generate-narratives` | Generate deterministic descriptions from validated context |
| `restore --latest` | Restore a validated backup after creating a recovery backup |
| `trace-summary` | Display a bounded execution trace summary |

`status` returns 0 for current data, 2 when regeneration is required, and 1 for malformed or unavailable inputs.
It compares managed item panels, queue flags, ability orders, annotations, descriptions, and tags with the reviewed bundle.
Build titles and Steam identity timestamps do not affect this comparison.

`install-artifacts` checks the current patch and client version before installation.
It requires network access for these checks but makes no new analytics requests.
Stale bundles and unavailable freshness checks prevent installation.

`restore --latest` selects the latest backup for the selected account and canonical cache path.
Backups for other Steam installations do not affect this selection.

Use `--help` on each command for its input requirements.
The review commands `preview`, `install`, and `export-context` require `--hero NAME` or `--all`.
They discover the selected Steam account.
Use `build` when Steam is unavailable.

Generate descriptions from a reviewed context with:

```bash
deadlock-build-sync generate-narratives --context generated/strategy-context.json --output generated/narratives.json
```

Quality replay uses [decision-state schema 3](schemas/decision-state.schema.json).
The library retains purchase recommendations for these replay checks.
The CLI has no `recommend` command.

Strategy context uses schema 17, projection guide version 5, and purchase guidance schema 4.
Regenerate older bundles with `build` before installation.
Compact categories form the canonical projection in both context and Steam output.
Purchase instructions retain routes, costs, checkpoints, and supported conditions.
They omit generic item-purpose advice.

The library requires an evidence layout in `project_policy_to_guide`.
Its arguments are policy, validation context, projection identity, and layout.
`build_compact_categories` replaces `build_purchase_categories`.
`extract_description_text` keeps its existing public interface.
The library removes `ItemPurpose`, `PurchaseDecision`, `TacticalProfile`, and their unused text builders.
It also removes `EvaluationState`, `PolicyDecision`, `next_policy_decision`, and `render_recommendation_markdown`.
Purchase recommendations require a policy path from admitted evidence.

## Execution tracing

Tracing is disabled by default.
Use `--trace stages` for workflow stages or `--trace calls` for instrumented calls.
`DEADLOCK_BUILD_SYNC_TRACE` accepts the same values.
The CLI prints the trace directory to stderr and preserves structured stdout.

```bash
deadlock-build-sync build --hero kelvin --trace stages
deadlock-build-sync trace-summary ~/.local/state/deadlock-build-sync/traces/RUN_ID
```

Traces record bounded timing and status events.
They do not record function arguments, return values, or environment contents.
Call mode covers explicit instrumentation rather than every Rust function.
A trace stops recording after 100 MiB.
The recorder retains three completed application trace runs and preserves unrelated directories and symlinks.

## Development

Run the CLI from the workspace with:

```bash
cargo run --locked -- build --hero kelvin
cargo run --locked --features analysis -- refresh-evidence
```

The workspace forbids unsafe repository code and treats warnings as errors.
Clippy denies `all`, `pedantic`, and `nursery` findings.
Cognitive complexity cannot exceed 21.
Arch-lint checks crate import boundaries.
Code review checks asynchronous syntax and cyclic module dependencies.
No unit tests were added during the rewrite, as requested.

Run the checks in the [CI workflow](.github/workflows/ci.yml) before delivery.
See [AGENTS.md](AGENTS.md) for crate ownership and verification requirements.
SQLFluff runs through an isolated `uvx` environment as a development tool.

The Python implementation and its comparison tools remain in Git at `d603d6b53bb110d0ac48a689f037861e6453b243`.
