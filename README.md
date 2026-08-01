# deadlock-build-sync

[![CI](https://github.com/sxndmxn/deadlock-build-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/sxndmxn/deadlock-build-sync/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Linux CLI that creates private Deadlock hero builds from
[deadlock-api.com](https://deadlock-api.com) analytics and installs them under
**My Builds**.

The generated guide has four item categories (`I`, `II`, `III`, `IV`). Items
are sorted by purchase popularity, capped at eight per tier, and annotated with
their statistically reliable purchase windows and overall win rate.

Each build also includes:

- The most-picked complete ability path for the current patch and cohort, with
  raw win rate and match count used as ranking context.
- A Codex-authored build profile and four-quarter game plan grounded in the
  exported hero ability descriptions, ability order, core item descriptions,
  item slots, purchase timing, pick rate, raw win rate, and match counts.

In-game tier descriptions contain short `TIER I`–`TIER IV` gameplay
instructions. They name a few core items only to explain why those purchases
change the hero's tactics. Core active items receive explicit instructions for
their target, timing, sequence, or hold condition. The prose does not dump item
descriptions, slots, stat lines, or analytics.

One primary power spike and at most one distinct secondary spike are identified
from the intersection of a reliable core-item timing, an ability-path
milestone, and a meaningful change in what the hero can safely force. Those
tiers are labeled `POWER SPIKE` in the in-game instructions; ordinary stat
growth is not labeled as a spike.

Hero win rate is also fetched across the website's seven match-duration
buckets. The context classifies broad early, mid, and late direction, and Codex
compares that natural curve with Tier III/IV item mechanics. Tier IV explicitly
labels whether the build `REINFORCE`s a natural strength, `COMPENSATE`s for a
weak phase, or has a `MIXED` response. Duration is treated as observational,
outcome-conditioned evidence rather than a causal result.
Because 45m+ games are a small population tail, late scaling never instructs
the player to stall an available close.

Item recommendations are independent analytics options rather than proof that
all listed items were purchased together. The Codex prompt says this explicitly
and treats lower-ranked items as matchup alternatives.

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
```

## Prompt evaluation

DeepEval exercises the exact production Luna kit-analysis and Sol synthesis
stages, Codex invocation, JSON schemas, and tactical response validator against
ten representative heroes from the latest exported context. Run either one
uncached pass or the three-pass reliability suite:

```bash
uv run deepeval test run tests/evals/test_narrative_prompt.py
uv run deepeval test run tests/evals/test_narrative_reliability.py
```

Both commands require an authenticated `codex` CLI and a current
`generated/strategy-context.json` from `export-context`. Set
`DEADLOCK_BUILD_SYNC_EVAL_CONTEXT` to evaluate another exported context, such
as the artifact produced by `sync`. The prompt suite makes twenty model calls;
the three-pass reliability suite makes sixty. Every call has a two-minute timeout,
and the suites do not enable DeepEval's optional cache, so results measure
first-pass reliability. Evaluation results remain local unless the user
explicitly configures Confident AI.

Repeated-generation scoring separates power-spike timing, tactical permission,
item/ability mechanic grounding, outcome-evidence coverage, and exact identity.
Adjacent timing and majority-supported tactical interpretations can agree even
when wording or secondary selections differ; invented mechanics, wrong-tier or
unsupported triggers, missing spikes, and duration-curve contradictions remain
hard failures. Exact quarter/item/ability overlap and lexical plan overlap are
reported as diagnostics instead of overriding strategically equivalent advice.

## Patch workflow

The normal workflow is one command. Close Deadlock, then run:

```bash
uv run deadlock-build-sync sync
```

`sync` discovers the local Steam account, fetches every eligible hero, builds
an ability-only kit profile with `gpt-5.6-luna`, synthesizes the final build
narrative with `gpt-5.6-sol`, validates every artifact, backs up the cache, and
installs the private builds. Reusable artifacts live under
`$XDG_STATE_HOME/deadlock-build-sync/artifacts` (or
`~/.local/state/deadlock-build-sync/artifacts`). Use `--hero NAME` for one hero,
`--artifacts DIR` to select another artifact directory, or
`--force-narratives` to regenerate both model stages. A failed model or
semantic-validation attempt is retried up to three times per stage; change that
bound with `--max-attempts N`.

### What is cached

`sync` keeps three reviewable artifacts: the exact analytics context, the Luna
kit profiles, and the final Sol narratives. Each hero is fingerprinted from the
evidence that can affect its prose. On a later run, compatible kit profiles and
narratives are reused, while changed or invalid entries are regenerated. This
avoids paying for identical model work without allowing stale prose into a
guide. `--force-narratives` bypasses this reuse.

This artifact cache is separate from Steam's
`cached_hero_builds.kv3`, which is user-owned game data. The Steam file is never
used as an AI cache: it is discovered only after generation, backed up, updated
through a validated temporary file, and atomically replaced.

The individual commands remain available for review and debugging:

```bash
# 1. Fetch analytics and export the exact source context Codex may use
uv run deadlock-build-sync export-context --all \
  --output generated/strategy-context.json

# 2. Generate a reviewable, schema-constrained narrative artifact.
#    This invokes `codex exec` separately; the sync/install process never does.
uv run python scripts/generate_narratives.py \
  --input generated/strategy-context.json \
  --output generated/narratives.json

# 3. Review the artifact, then preview it against fresh live context.
#    Preview and install use generated/narratives.json by default.
uv run deadlock-build-sync preview --hero kelvin

# 4. Install all private builds after closing Deadlock
uv run deadlock-build-sync install --all

# Restore the most recent cache backup
uv run deadlock-build-sync restore --latest
```

Use `--narratives PATH` to select another reviewed artifact. A missing, stale,
or incomplete narrative artifact stops preview or installation. Analytics-only
guides require the explicit `--without-narratives` flag; installing them writes
empty summary and tier-instruction fields.

## Rank cohorts

Every analytics endpoint uses one validated rank range. The default is
`phantom-i` through `eternus-vi`. Override either boundary with symbolic
rank names:

```bash
uv run deadlock-build-sync preview --all \
  --min-rank oracle-iii \
  --max-rank ascendant-vi
```

Available tiers are `initiate`, `seeker`, `alchemist`, `arcanist`, `ritualist`,
`emissary`, `archon`, `oracle`, `phantom`, `ascendant`, and `eternus`.
Divisions accept `i`–`vi` or `1`–`6`. The selected range is recorded in preview
output, exported context fingerprints, backup manifests, and in-game build
descriptions.

`export-context` produces a per-hero JSON object containing:

- Full hero and ability descriptions plus labeled, nonzero ability properties.
- The selected 16-step ability path, split into four quarters, with its complete
  path raw outcome and sample size (not per-upgrade win rates).
- Tier I–IV arrays of item objects with `item`, `slot` (`SPIRIT`, `VITALITY`,
  or `WEAPON`), descriptions, timing windows, relative pick rate, raw win rate,
  and match count.
- Seven hero win-rate-by-duration buckets plus conservative early/mid/late
  curve classification.
- A full-source fingerprint plus a stable narrative-basis fingerprint.

Only heroes with eight reliable items in every tier, all four ability assets, a
reliable complete 16-step ability path, and all seven duration buckets are
exported. `--all` reports and skips incomplete heroes; selecting one explicitly
returns an error instead of producing a guide with unsupported tactical timing.

The Codex response is constrained by
[`schemas/narrative-response.schema.json`](schemas/narrative-response.schema.json).
Installation rejects an artifact if the live patch or any selected hero's
ranked items, purchase windows, mechanics, descriptions, ability path, or broad
duration classification has changed. Raw match totals and rates may advance
within the same patch without invalidating otherwise identical tactical prose.
Regenerate the context and narratives when the narrative basis changes instead
of silently applying stale strategy text.

The CLI discovers the Deadlock Steam Cloud cache automatically when there is a
single local Steam account. Use `--account-id` or `--cache-path` to disambiguate
multiple accounts.

## Safety model

- Refuses cache changes while Deadlock is running.
- Fetches and validates every requested guide before touching the cache.
- Never invokes Codex while reading or changing Steam data.
- Recomputes exported source and per-hero fingerprints before invoking Codex,
  so a context edited after export is rejected.
- Rejects stale or incomplete Codex narrative artifacts.
- Creates a timestamped backup of `cached_hero_builds.kv3` and
  `remotecache.vdf`.
- Writes a temporary KV3 file, decodes and validates it, and then performs an
  atomic replacement.
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
