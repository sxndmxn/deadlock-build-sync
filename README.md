# deadlock-build-sync

[![CI](https://github.com/sxndmxn/deadlock-build-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/sxndmxn/deadlock-build-sync/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`deadlock-build-sync` makes one private Deadlock build for every hero from public match data.
The CLI installs the builds in Steam's **My Builds** on Linux.

## Install

Install Rustup.
Install a C++ compiler for bundled DuckDB.
The checkout selects the pinned Rust toolchain.

```bash
git clone https://github.com/sxndmxn/deadlock-build-sync.git
cd deadlock-build-sync
cargo install --path crates/deadlock-build-sync --locked
```

The Linux AMD64 release contains the same executable. Install the extracted executable:

```bash
mkdir -p ~/.local/bin
install -m 755 deadlock-build-sync ~/.local/bin/deadlock-build-sync
```

## Use

Stop Deadlock.
Make and install a build for every hero:

```bash
deadlock-build-sync sync
```

`sync` downloads the ranked matches of the current patch, makes the builds, and writes them to the artifact directory.
Then it makes a Steam cache backup and installs the builds atomically.
It keeps favorites, selected builds, saved builds, and unrelated private builds.
It replaces only builds with the managed marker.
It prevents writes if Deadlock is in operation or process inspection is not possible.

The CLI finds Steam caches in native, legacy, Flatpak, and Snap locations.
Use `--account-id` or `--cache-path` to select a cache.

Make builds without Steam access:

```bash
deadlock-build-sync build
```

## The builds

Each build has these parts:

1. **MAIN CORE**: the items to buy from left to right.
2. **TIER 1 to TIER 4**: situational items for the matching shop tier. Buy one instead of a CORE item when the match makes it a better choice.
3. **Ability order**: the most common complete ability order at this rank.
4. **Description**: what to play around (the key ability, the key item, and its power spike) and the confidence of the build.

Example description:

```text
Play around: max Arctic Beam first, then get Escalating Exposure for the power spike at about 25k net worth.
Buy MAIN CORE from left to right. TIER items are situational choices.
Evidence: moderate (held-out test, n=2075). Ranked • Ritualist I–Eternus V • 2026-10-09 to 2026-10-11.
```

Each item shows three lines:

```text
MID GAME
WIN RATE: 52.3%
PICK RATE: 48.1%
```

The phase is the time when the build adds the item: early game (9 minutes), mid game (20 minutes), or late game (30 minutes).
The win rate is the share of hero players who own the item at that time and win the match.
The pick rate is the share of hero players who own the item at that time.

The method estimates how much each item adds to the win probability in similar game states.
It then assembles a build from items that players at this rank use, tilted toward items that win more.
A test on held-out matches gives each build a confidence label: `strong`, `moderate`, or `limited`.
See [Build method](docs/build-method.md) for the method, the test, and the limits.

The data is observational. It does not prove that an item causes a win.

## Options

| Option | Default | Scope |
| --- | --- | --- |
| `--min-rank` | `ritualist-i` | Lowest average match rank |
| `--max-rank` | `eternus-v` | Highest average match rank |
| `--since` | Current patch | First match start time (ISO 8601, UTC) |
| `--as-of` | Now | Last match end time (ISO 8601, UTC) |
| `--extraction-memory-mb` | 12000 | Database memory limit in decimal MB |
| `--extraction-threads` | 8 | Database threads |
| `--run-id` | Current time | Name of the analysis run |
| `--resume` | Off | Reuse the extracted matches of `--run-id` |

DuckDB downloads ICU, DuckLake, and HTTPFS extensions if they are missing.
The CLI keeps analysis runs in `$XDG_STATE_HOME/deadlock-build-sync/offline/results`.

## Artifacts

The default artifact directory is `$XDG_STATE_HOME/deadlock-build-sync/artifacts`.
If `XDG_STATE_HOME` is not set, the CLI uses `~/.local/state/deadlock-build-sync/artifacts`.
The directory contains `hero-builds.json` and one Markdown file per hero in `builds/`.
Each new run replaces the complete directory.

## Commands

| Command | Purpose |
| --- | --- |
| `sync` | Make builds for all heroes and install them with a cache backup |
| `build` | Make builds for all heroes without Steam |
| `install` | Install the builds in the artifact directory |
| `status` | Show whether the builds match the current patch and whether Steam has them |
| `restore --latest` | Restore the latest cache backup, after a backup of the current cache |
| `trace-summary` | Show a trace summary |

Use `COMMAND --help` for options.

`status` gives exit code 0 when the builds match the current patch and client version and Steam has them.
Exit code 2 means that a new sync is necessary. Exit code 1 means that an input is malformed or unavailable.
It ignores build titles and Steam identity timestamps.

`install` compares the builds with the current patch and client version from the API.
The installation stops if these identities are different or the check is not possible.

## Tracing and development

Use `--trace stages` for workflow events or `--trace calls` for instrumented calls.
`DEADLOCK_BUILD_SYNC_TRACE` accepts the same values. The CLI does not make traces by default.

```bash
deadlock-build-sync build --trace stages
deadlock-build-sync trace-summary ~/.local/state/deadlock-build-sync/traces/RUN_ID
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions.
Run `bash scripts/check_repository.sh` for the shared local and CI checks.
See [AGENTS.md](AGENTS.md) for repository requirements.
