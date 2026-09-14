# deadlock-build-sync

[![CI](https://github.com/sxndmxn/deadlock-build-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/sxndmxn/deadlock-build-sync/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`deadlock-build-sync` makes private Deadlock hero builds from [Deadlock API](https://deadlock-api.com) analytics.
The CLI installs these builds in Steam's **My Builds** on Linux.
It can also make builds on macOS.

## Install

Install Rustup.
Install a C++ compiler for bundled DuckDB.
The checkout selects the pinned Rust toolchain.

```bash
git clone https://github.com/sxndmxn/deadlock-build-sync.git
cd deadlock-build-sync
cargo install --path crates/deadlock-build-sync --features analysis --locked
```

Use `--features analysis` only if you will use `refresh-evidence`.
The Linux AMD64 release includes analysis. Install the extracted executable:

```bash
mkdir -p ~/.local/bin
install -m 755 deadlock-build-sync ~/.local/bin/deadlock-build-sync
```

## Use

Before the first sync or after a patch change, update the evidence:

```bash
deadlock-build-sync refresh-evidence
```

Stop Deadlock.
Install the builds for all eligible heroes:

```bash
deadlock-build-sync sync
```

`sync` makes descriptions and validates the artifacts.
It makes a Steam cache backup before an atomic installation.
It keeps favorites, selected builds, saved builds, and unrelated private builds.
It prevents writes if Deadlock is in operation or process inspection is not possible.
It does not change the cache bytes if the builds are the same.

The CLI finds Steam caches in native, legacy, Flatpak, and Snap locations.
Use `--account-id` or `--cache-path` to select a cache.

Make builds without Steam access:

```bash
deadlock-build-sync build --hero kelvin
```

Use `build` without `--hero` to make builds for all eligible heroes.
Use `--details` for the full optional purchase paths.
Use `--format json` for JSON output.
Use `--artifacts DIR` to set the artifact directory.

## Build rules

Each displayed main core and alternate path must have a validation win rate above the hero's rate in the same validation sample.
Equal rates do not qualify.
Each path must also have a positive adjusted difference between core owners and comparable nonowners.
The comparison must include at least 100 core owners and at least 80% of all core owners in validation.
It groups observations by hero, rank, player wealth, and team lead.
The comparison uses the same rank range and matches that last at least 20 minutes.
It measures core ownership at 20 minutes, not the effect of an exact purchase order.
Missing or invalid rates prevent admission.
If no path qualifies for a requested hero, generation stops and keeps the previous bundle.
Successful artifact generation writes `build-admission.json` with path decisions, comparison values, and rejection reasons.
Missing comparison data and nonpositive adjusted differences have separate rejection reasons.
Admission does not establish statistical superiority or causation.
See [Build admission methods](docs/build-admission.md) for the method, research, and limitations.

- Eclat finds item cores. Leiden puts related cores into groups with default paths and manual variants.
- Discovery, selection, validation, and reserved test partitions contain different matches. Test data does not control build admission.
- The automatic Queue contains only MAIN CORE. Other panels are optional. Each core substitution must have its own evidence.
- The purchase planner uses component costs, rebuy costs, inventory limits, and ability currency. Without sufficient evidence, purchase timing stays unknown.
- Descriptions use the supplied hero abilities, item mechanics, purchase windows, cohort, patch, sample counts, and match duration. The CLI uses deterministic code.
- Buyer results do not show that an item causes a better match outcome.
- The CLI rejects artifacts with incorrect data, missing data, or different source identities. It keeps the previous bundle if generation stops with an error.

Item hover cards show:

```text
SOUL WINDOW: 2k - 15k
PR: 80.6% | WR: 49.0% | TOTAL GAMES: 12,611
```

| Field | Meaning |
| --- | --- |
| `SOUL WINDOW` | Middle half of buyer net worth at purchase |
| `PR` | Item adoption across the hero cohort |
| `WR` | Buyer win rate |
| `TOTAL GAMES` | Buyer match count |

## Evidence refresh

`refresh-evidence` downloads a fixed public cohort for analysis without Steam access.
DuckDB downloads ICU, DuckLake, and HTTPFS extensions if they are missing.
Timestamp parameters and match cutoffs use UTC.

| Option | Default | Scope |
| --- | --- | --- |
| `--extraction-memory-mb` | 12000 | Extraction memory limit in decimal MB |
| `--extraction-threads` | 8 | Extraction database threads |
| `--workers` | 8 | Hero workers; each connection uses one thread and a maximum of 512 MiB |

Memory use also includes source records and numerical matrices.

The default rank range is `emissary-i` through `eternus-v`.
`--rank-expansion auto` lets the rank range increase if the evidence for a hero is not sufficient.
Use `--rank-expansion off` to prevent this increase.
Use the same rank options for refresh and generation.

The CLI keeps runs in its `offline/results` directory.
After discovery, continue validation with the same run:

```bash
deadlock-build-sync refresh-evidence --resume --run-id RUN_ID
```

The source files, candidates, guide groups, cohort settings, and implementation identity must be compatible.
The command uses the previous extraction results.

## Artifacts

The default artifact directory is `$XDG_STATE_HOME/deadlock-build-sync/artifacts`.
If `XDG_STATE_HOME` is not set, the CLI uses `~/.local/state/deadlock-build-sync/artifacts`.
The bundle contains `build-evidence.json`, `strategy-context.json`, `policies.json`, and `narratives.json`.
`builds.json` contains an index of the Markdown and JSON files.

For one hero, `build` and `sync` keep the full-roster bundle.
For `--artifacts /path/artifacts`, they write to `/path/artifacts-subsets/HERO_ID` and show the output path.
Install that bundle with `install-artifacts --artifacts DIR`.

The CLI accepts context schema 17, projection guide version 5, and purchase guidance schema 4.
Use `build` to replace a bundle with previous schema versions.

## Commands

| Command | Purpose |
| --- | --- |
| `sync` | Make, validate, and install builds with a cache backup |
| `build` | Make builds without Steam |
| `status` | Show the status of artifacts and installed builds |
| `refresh-evidence` | Download evidence for analysis; `analysis` feature necessary |
| `quality-report` | Show build quality and optional replay results |
| `preview` | Show builds for selected heroes |
| `install` | Make and install builds for selected heroes |
| `install-artifacts` | Install a validated bundle |
| `export-context` | Export strategy context and policies |
| `generate-narratives` | Make descriptions from validated context |
| `restore --latest` | Make a cache backup before a restore |
| `trace-summary` | Show a trace summary |

Use `COMMAND --help` for options.
A Steam account is necessary for `preview`, `install`, and `export-context`.
Use `--hero NAME` or `--all` with these commands.

`status` gives exit code 0 when artifacts and installed builds agree with the API patch and client version.
Exit code 2 means that regeneration is necessary. Exit code 1 means that the inputs are incorrect or unavailable.
It ignores build titles and Steam identity timestamps.

`install-artifacts` uses network access to compare the bundle with the patch and client version from the API.
The installation stops if these identities are different or the check is not possible.
`restore --latest` selects a backup by creation time, account, and canonical cache path.

## Tracing and development

Use `--trace stages` for workflow events or `--trace calls` for instrumented calls.
`DEADLOCK_BUILD_SYNC_TRACE` accepts the same values. The CLI does not make traces by default.

```bash
deadlock-build-sync build --hero kelvin --trace stages
deadlock-build-sync trace-summary ~/.local/state/deadlock-build-sync/traces/RUN_ID
```

The CLI writes the trace directory path to stderr.
Traces contain timing and status events, without arguments, return values, or environment contents.
Each trace has a maximum size of 100 MiB. The CLI keeps three completed trace runs.

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions.
See [AGENTS.md](AGENTS.md) for repository requirements.
See the [CI workflow](.github/workflows/ci.yml) for verification commands.
