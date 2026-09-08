# deadlock-build-sync

[![CI](https://github.com/sxndmxn/deadlock-build-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/sxndmxn/deadlock-build-sync/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Linux CLI that creates private Deadlock hero builds from
[deadlock-api.com](https://deadlock-api.com) analytics and installs them under
**My Builds**.

Design evidence and implementation contracts:

- [Strategy-description research](docs/deadlock-strategy-description-research.md) — source evidence, analytical rationale, and build-policy findings.
- [Build-policy requirements](docs/deadlock-build-policy-requirements.md) — staged normative requirements, acceptance criteria, and verification evidence.
- [Build usage audit](docs/deadlock-build-usage-audit.md) — live-client findings and the five linked implementation phase briefs.

Each run uses one client version and one fixed cutoff time.
It records Ranked or Unranked as the cohort identity.
The snapshot manifest records exact response bytes, patch identity, independent epochs, rank labels, API record units, and fallback behavior.

The output is a typed policy graph with a snapshot identity:

- A mechanically legal level/AP ability timeline selected from equivalent reached
  legal states, with support reported at each decision. Price tiers are never treated
  as equal “quarters” of that timeline.
- Eclat first discovers exact four-to-six-item cores, then uses existing three-item
  seeds if no supported legal path is available. Leiden groups related cores.
  Pairwise purchase ordering supplies the component path. Whole matches are split
  by time. Candidates, ranking, paths, pools, and branch conditions are frozen
  before validation. The reserved test split is not used for admission.
- Each distinct identity group can supply a build that passes support,
  purchase-order, and mechanics checks. There is no fixed build-count limit per
  hero. Each core needs 100 owners in discovery and 100 in selection.
  The first usable identity in the frozen selection ranking is the default.
  Separate outcome checks set `outcome_supported` or `observed` evidence status.
  Weak or negative outcome estimates do not remove a supported legal build.
- Related exact cores appear in one guide group with a default Queue and compact
  variant choices. Shared core items determine the groups. Item mechanics explain
  their names. Each variant keeps its own complete path, evidence, and item pool.
  There is no fixed limit on groups or variants.
- Four item pools use discovery buyers who owned that exact core. Each item needs
  at least 20 buyers. Each tier has up to ten items. Every matching option stays
  visible. Buyer win rates describe the data; they do not rank pool items.
- Automatic choices need separate evidence at the current purchase checkpoint.
  Failed branch checks leave the manual options available.
- Evidence objects name their unit and claim class.
  Item adoption divides unique first ownership records by eligible player-match records.
  Adopter outcome rates describe observed results.
  They do not measure causal effects on win rates.
- Lane and whole-enemy-team matchup scopes kept separate, with mechanics-first
  counters and structured abstention when support or mechanics are inadequate.
- An ending-duration profile describes games that end in each phase.
  It does not measure live power or support delays when a team can end the game.

Steam receives the validated component path as `CORE 1`, `CORE 2`, and later
steps. These are the only automatic Queue rows. `OPTIONAL`, `PICK ONE`, and
`UPGRADE` rows appear at their supported checkpoints. The complete `ITEM POOL`
follows the path. Choice instructions show the trigger, checkpoint, component
route, extra cost, and core resume point. Long instructions use extra rows.
Items with unsupported timing stay in the pool with **Timing unknown**.

All current heroes are requested. A hero must have an admitted build or an explicit
evidence exclusion. Excluded heroes keep their installed builds. Missing data and
malformed artifacts are errors. If no build passes, the existing bundle is preserved.

Every item hover in every row carries the same two-line statistics card and nothing
else:

```
SOUL WINDOW: 2k - 15k
PR: 80.6% | WR: 49.0% | TOTAL GAMES: 12,611
```

`SOUL WINDOW` is the middle half of the buyer net worth at purchase. `PR` is the pick
rate across the hero's analysed games. `WR` is the raw buyer win rate. `TOTAL GAMES` is
the buyer match count behind that win rate. The card is derived, so a stored artifact
whose card no longer matches its evidence is rejected. Category height grows with the
number of item rows so item cards are not cut off. When purchase telemetry has a
supported majority imbue target, the Steam build encodes its current ability ID and
Steam shows its own imbue icon.
Each build's three header icons are deterministic: the ability maxed first, the
highest-win-rate Tier 3 CORE item (or Tier 4 when CORE has no Tier 3 item), and the
dominant functional build tag. The item win rate is descriptive buyer telemetry.
No model-written advice is installed. Deterministic code validates the
core against components, slots, active bindings, flex unlocks, ability currency, and
current item/ability qualifiers before serialization.

Pinned hero role, playstyle, build archetype, and ability order produce the short
build-level description. The description artifact must copy the exact snapshot,
policy, context, and narrative basis identities.

## Requirements

- Linux with Steam and Deadlock installed
- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)

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
Close Deadlock before running `sync`; the command refuses to write while the
game is open.

`sync` also requires a validated `build-evidence.json` from the offline
player-match analysis pipeline. Its default location is
`$XDG_STATE_HOME/deadlock-build-sync/artifacts/build-evidence.json` (or
`~/.local/state/deadlock-build-sync/artifacts/build-evidence.json`). Use
`--build-evidence PATH` to review another artifact. The CLI rejects edited or
incompatible patch, client, asset, rank-label, rank-range, mode, epoch, cutoff, or
roster identities; it never falls back to aggregate purchase-event rankings.

The repository includes the offline producer.
Its analysis dependencies are optional.
Install them on a machine that refreshes evidence:

```bash
uv tool install '.[analysis]'
deadlock-build-sync refresh-evidence
```

`refresh-evidence` downloads and analyzes the fixed public cohort.
It uses eight concurrent hero worker processes by default.
Use `--workers N` to change the worker count.
Each worker gives DuckDB a 512 MiB memory limit.
After discovery completes, `--resume --run-id ID` validates the saved candidate set.
Supply the original rank options when you resume a run.
The command verifies candidate fingerprints and guide groups before it resumes validation.
Within each hero, identical statistical inputs reuse their model fits.
The cache includes all input values and both item IDs.
It writes its run under `$XDG_STATE_HOME/deadlock-build-sync/offline`.
It atomically installs a validated `build-evidence.json` in the artifact directory.
It does not discover, read, or write Steam data.

Steam discovery supports native (`~/.local/share/Steam`), legacy
(`~/.steam/steam` and `~/.steam/root`), Flatpak, and Snap installations. A
legacy symlink to the native installation is deduplicated. If more than one
real cache remains, select it with `--account-id` or `--cache-path`.

## Development

Create complete builds from the normal application without Steam:

```bash
uv run build --hero kelvin
# Equivalent command:
uv run deadlock-build-sync build --hero kelvin
```

Omit `--hero` to build all eligible heroes. The command uses the current
`build-evidence.json`, validates the normal policy, and writes descriptions,
policies, Markdown, and JSON. `--details` shows complete optional routes.
Use `--format json` for structured output. `uv sync` installs dependencies;
it does not create hero builds.

Both `build` and `sync` write `builds.json` in the artifact directory. It points
to `builds/<snapshot-id>/INDEX.md`, one Markdown guide per group, detailed guides,
and `guides.json`. Each guide shows the core purchase path, all eligible choices,
component costs and rebuys, and the full tiered item pool. `PICK ONE` means the
next purchase for one need. It does not limit the number of choices in a match.
Steam, Markdown, JSON, recommendations, and artifact installation use the same
typed guide and purchase planner.
The main guide has CORE, CORE OPTIONAL when needed, and TIER 1–4. CORE OPTIONAL
contains the additional items from all supported variants, with no duplicates.
Items already shown in either core section are not repeated in the tier sections.
Small sections use smaller widths; empty tiers use a short text panel.
The details file and `guides.json` keep every variant's full purchase path, costs,
support, and pool.
Steam item notes identify variant scope. Full paths and purchase instructions
appear in the build description and detailed Markdown. `guides.json` also records
the exact Steam categories and dimensions.
Choose a complete variant before purchase. A manual variant is not evidence for
an automatic core substitution during a match.

`refresh-evidence` records strict adjacent purchase counts from the discovery
buyers of each exact core. A position needs at least 20 buyers and 10% of the
item's buyers. Missing or weak timing stays unknown. Evidence schema 12 and
purchase-guide schema 3 are required. Guide indexes use schema 2; their group
records use schema 1. Older evidence must be refreshed and rebuilt.
See [the default build contract](docs/default-build-system.md).
The [current verification report](docs/consolidated-hero-verification-2026-09-07.md)
records 140 guide groups, all 761 supported variants, and complete coverage of 38 heroes.

```bash
uv run deadlock-build-sync refresh-evidence
uv run build --hero kelvin --details
# Installation remains an explicit command:
uv run deadlock-build-sync sync
```

The default uv development group includes the test, type, coverage, complexity,
dead-code, duplicate-code, and mutation tools. Validate a checkout with:

```bash
uv lock --check
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run deptry .
uv run tach check
uv run complexipy
uv run coverage erase
uv run coverage run -m pytest -W error
uv run coverage json
uv run tools/quality_gate.py
uv run vulture
uv run pylint --disable=all --enable=duplicate-code src scripts
uv pip check
uv build
```

Run the commands in [Quality gates](docs/quality-gates.md) for the slower
mutation gate. See that document for all limits, mutation-run details, and
the standalone SonarLint setup.

## Execution tracing

Tracing is disabled by default. Add `--trace stages` for low-overhead pipeline
boundaries or `--trace calls` for the complete in-package Python call flow:

```bash
# Readable stage boundaries and allowlisted artifact/count metadata
uv run deadlock-build-sync preview --hero kelvin --trace stages

# Debug-only call, return, exception, and inclusive timing events
uv run deadlock-build-sync preview --hero kelvin --trace calls
```

The flag works before or after the command. Set
`DEADLOCK_BUILD_SYNC_TRACE=stages` or `DEADLOCK_BUILD_SYNC_TRACE=calls` for the
equivalent environment-driven behavior. At completion, the CLI prints the trace
run directory once to stderr, leaving stdout—including preview JSON—unchanged.
Runs are stored under
`$XDG_STATE_HOME/deadlock-build-sync/traces/<timestamp>/trace.jsonl` (or the
corresponding `~/.local/state` path). Starting a trace retains the latest three
application-owned trace runs and removes older recognized run directories; unrelated
directories and symlinks are never pruned.

Call tracing uses Python's profiling hook for `deadlock_build_sync` modules only.
An exception-only trace hook supplies exception type and failure status; neither
hook records arguments, return values, exception messages, account or match IDs,
inventories, environment contents, or model prompts. Preview traverses evidence
admission, policy construction, projection, presentation, and pure protobuf
serialization without reading or changing Steam data.

`stages` is intended for routine diagnostics. `calls` writes an event for every
entered project function and is deliberately debug-only because profiling and
per-event JSONL I/O add noticeable overhead. Each trace is capped at 100 MiB; a
`trace_truncated` event marks the cap and later events are omitted. Render a bounded
tree and per-function inclusive timings without changing production functions:

```bash
uv run deadlock-build-sync trace-summary \
  ~/.local/state/deadlock-build-sync/traces/<timestamp>
```

## Description verification

Build descriptions use pinned context fields and have no network or model step.
Unit tests verify exact output, identity reuse, size bounds, and fail-closed behavior.

The deterministic evaluation layer additionally implements patch-forward,
player/match-group-safe splits; popularity baselines; Brier/log-loss/calibration
and selective risk; predeclared target trials; IPS, self-normalized IPS, doubly
robust OPE with support and clipping diagnostics; privacy-bounded recommendation
events; and monitoring/rollback rules. See the
[coverage manifest](docs/evaluation-coverage.json),
[sample layer-separated report](docs/evaluation-sample-report.json), and
[monitoring runbook](docs/monitoring-runbook.md).

## Patch workflow

Use `deadlock-build-sync quality-report --artifacts PATH` to inspect ability
support, fallbacks, and independent replay coverage for each frozen build.
Missing replay evidence is reported as unevaluated. See
[Build quality and independent replay](docs/build-quality.md) for inputs,
technical acceptance criteria, and the limits of these diagnostics.

Check the whole artifact chain first. This command is read-only:

```bash
uv run deadlock-build-sync status
```

It reports build evidence, strategy context, policies, narratives, the reviewed
bundle, and installed managed builds separately. Exit 0 means current, exit 2 means
regeneration is required, and exit 1 means an input is malformed or unavailable.
When build evidence is stale, refresh it before generation:

```bash
uv run deadlock-build-sync refresh-evidence
```

The evidence producer reconstructs inventory from purchases, sales, and component
consumption. It uses Eclat, Leiden, and pairwise ordering. The old clustering and
core-completion fallback are archived in
[Git history](tools/comparisons/README.md). Analysis dependencies are optional;
rendering and installation do not load them.

The normal installation workflow uses one command.
Close Deadlock before you run it:

```bash
uv run deadlock-build-sync sync
```

`sync` discovers the local Steam account.
It generates every eligible hero from one snapshot and writes one deterministic description per path.
It validates every artifact, creates a cache backup, and installs the private builds.
Item statistics, imbue targets, categories, tags, and titles stay deterministic. Titles
come from the CORE item mix, so an ability-path label cannot misname a weapon-heavy
build. An all-hero run refuses installation if any pinned
eligible hero lacks a complete policy. Reusable artifacts live under
`$XDG_STATE_HOME/deadlock-build-sync/artifacts` (or
`~/.local/state/deadlock-build-sync/artifacts`). Use `--hero NAME` for one hero,
or `--artifacts DIR` to select another artifact directory.

For a read-only next-purchase decision after an in-match deviation, supply a
deidentified state document matching
[`schemas/decision-state.schema.json`](schemas/decision-state.schema.json):

```json
{
  "schema_version": 3,
  "build_evidence_id": "<64-character artifact id>",
  "client_version": 6677,
  "patch_identity": "<patch identity>",
  "match_mode": "Ranked",
  "game_mode": "Normal",
  "hero_id": 12,
  "clock_s": 900,
  "average_badge": 90,
  "liquid_souls": 1250,
  "purchases": [101],
  "inventory": {
    "items": [101],
    "components": [],
    "open_slots": 8,
    "flex_slots": 0,
    "active_bindings": 0
  },
  "learned_abilities": [1, 2],
  "enemy_hero_ids": [],
  "lane_enemy_hero_ids": [],
  "enemy_item_ids": [],
  "allied_hero_ids": [],
  "objectives": [],
  "threats": []
}
```

```bash
uv run deadlock-build-sync recommend --state state.json
```

The result gives the next purchase, liquid-soul shortfall, remaining route and
cost, selected placements, and all available choices. Add `--format markdown`
for text output. Use `path_id` to retain one admitted identity. State schema 3
also accepts `selected_optional_items`, `placement_overrides`,
`core_substitution_item_id`, `enemy_observed_at_s`, and `economy`.

Explicit player choices take priority. Otherwise an admitted matching branch can
apply at the current checkpoint. The default path applies when none matches.
The planner credits owned components and upgrades, shows required component
rebuys, and checks item and active-item limits. See the
[state example and observation rules](docs/default-build-system.md#match-state).
Steam shows static conditions. This tool does not capture live game state.

### What is cached

`sync` consumes four reviewable artifacts: the deterministic build evidence, exact
strategy context, rich typed policy sidecar, and final build descriptions.
Every artifact carries the source manifest or snapshot identity. A narrative is reusable only when its
snapshot, policy, context, narrative basis, and deterministic generator version are
exactly compatible. Changed or malformed entries regenerate.

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
# 1. Export the exact evidence context and rich policies
uv run deadlock-build-sync export-context --all \
  --build-evidence ~/.local/state/deadlock-build-sync/artifacts/build-evidence.json \
  --output generated/strategy-context.json

# 2. Generate a reviewable deterministic description artifact.
uv run python scripts/generate_narratives.py \
  --input generated/strategy-context.json \
  --output generated/narratives.json

# 3. Review strategy-context.json, policies.json, and narratives.json, then preview.
#    strategy-context.json is compact; pipe it through `jaq .` for formatted review.
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

Each hero uses its recorded effective rank range in analytics, guides, and
recommendations. The starting range is `emissary-i` through `eternus-v`.
`refresh-evidence` and generation commands accept `--rank-expansion auto|off`.
The default is `auto`. `--min-rank` sets the starting cutoff. If a hero has no
supported legal build, the producer lowers that hero's cutoff one tier at a time
through Initiate. The upper cutoff, source snapshot, patch, and time range stay
fixed. Expansion stops at the first range with a supported build. It does not
seek better wins or more identities. `off` uses only the requested range.
Use the same starting boundaries for refresh and generation:

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
- Layered mechanics, analytics, policy, description, projection, and whole-document
  fingerprints bound to the complete source manifest.

Every hero requires a supported legal core, complete purchase records, current
mechanics, a complete ability projection, a duration estimate or explicit duration
abstention, and policy validation. Optional pool tiers can be empty. The guide
then shows that no supported options are available. Conflicting timing estimates
are uncertain; the legal purchase order stays fixed. Missing optional economy or
enemy observations disable the affected estimates and choices.
Missing requested heroes cause generation to fail. A failed refresh or build
preserves the current artifact bundle.

Installation rejects an artifact when patch identity, snapshot, client version,
match mode, rank labels, policy, context, narrative basis, generator version, hero
coverage, or projection categories differ. Advancing raw evidence creates a new context; it
does not silently reuse prose merely because a patch title stayed the same.

The CLI discovers the Deadlock Steam Cloud cache automatically when there is a
single local Steam account. Use `--account-id` or `--cache-path` to disambiguate
multiple accounts.

## Safety model

- Refuses cache changes while Deadlock is running.
- Fetches and validates every requested guide before touching the cache.
- Recomputes exported source and per-hero fingerprints before generating
  descriptions, so a context edited after export is rejected.
- Rejects stale, cross-cohort, incomplete, or policy-changing description
  artifacts.
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
Report security vulnerabilities privately as described in
[SECURITY.md](SECURITY.md).

## License and affiliation

Released under the [MIT License](LICENSE).

This is an independent community project. It is not affiliated with, endorsed
by, or sponsored by Valve Corporation. Deadlock, Steam, and their associated
marks are property of their respective owners.
