# deadlock-build-sync

[![CI](https://github.com/sxndmxn/deadlock-build-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/sxndmxn/deadlock-build-sync/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`deadlock-build-sync` makes private Deadlock builds for every hero from public match data.
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
2. **VS WEAPON, VS SPIRIT, and VS SUSTAIN**: counter items from the mid game, for the main damage type of the enemy team and for enemy healing. Each run repeats the counter test and removes a panel when the run contradicts it.
3. **TIER 1 to TIER 4**: situational items for the matching shop tier. Buy one instead of a CORE item when the match makes it a better choice.
4. **Ability order**: the most common complete ability order at this rank.
5. **Description**: the inferred ability focus, when supported, the key item, its power spike, and the build confidence.

Build titles use `Steam name | ability + key item` when CORE items support a clear ability focus.
Otherwise, titles name the first fully upgraded ability from the selected ability order.
Titles use only the key item when no supported ability name is available.
Titles omit hero names and stay within 50 characters.
The description states the ability upgrade order separately from the inferred focus.

Example description:

```text
Play around: Essence Bomb with Mystic Reverb at about 18k net worth.
Ability order: max Life Drain first.
Buy MAIN CORE from left to right. TIER items are situational choices.
Evidence: moderate (held-out test, n=2599). Ranked • Ritualist I–Eternus V • 2026-10-09 to 2026-10-12.
```

Each item shows four lines:

```text
MID GAME
ITEM WIN RATE: 52.3% (523/1000)
PICK RATE: 50.0% (1000/2000)
SOUL WINDOW: 8k-16k
```

The phase is the time when the build adds the item: early game (9 minutes), mid game (20 minutes), or late game (30 minutes).
The item win rate is wins divided by buyer matches for this hero.
The pick rate is buyer matches divided by all selected matches for this hero.
Both rates show their numerator and denominator. Each player match counts once per item, regardless of purchase time or build variant.
These are observed item purchase statistics. They do not measure the complete build or prove an item causes wins.
Catalogs without purchase counts show `unavailable` until regeneration.
The soul window is the net worth range in which most players buy the item: the middle half of the first purchases.

Items with sufficient match evidence also select an ability in the native **IMBUE ABILITY** control.
The target needs at least 20 first purchases and more than half of the recorded imbue selections for that hero and item.
Items without sufficient evidence leave the selection empty.

The method estimates how much each item adds to the win probability in similar game states.
It then assembles a build from items that players at this rank use, tilted toward items that win more.
A test on held-out matches gives each build a confidence label: `strong`, `moderate`, or `limited`. The label pools the test with comparable builds of all heroes, because the test of one hero alone is mostly noise.
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
Before reuse, `--resume` verifies all seven source JSON files against the fingerprints in the run manifest.
Missing files, changed contents, and incomplete or malformed fingerprints stop the run.
JSON spacing and object key order do not affect these fingerprints.

## Artifacts

The default artifact directory is `$XDG_STATE_HOME/deadlock-build-sync/artifacts`.
If `XDG_STATE_HOME` is not set, the CLI uses `~/.local/state/deadlock-build-sync/artifacts`.
The directory contains `hero-builds.json` and one Markdown file per hero in `builds/`.
Each Markdown file includes every catalog build for that hero.
The catalog and installer support distinct variants for the same hero.
The analysis selects a main build and up to two additional builds with distinct item combinations and sufficient match support.
It evaluates each build separately. Similar candidates do not create additional entries.
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

`sync` and `install` compare the builds with the current patch and client version from the API before installation.
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
