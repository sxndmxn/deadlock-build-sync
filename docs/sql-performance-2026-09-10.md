# SQL query performance

This report records the first optimization pass.
The [second pass](sql-performance-2026-09-11.md) contains subsequent changes and measurements.

Five DuckDB queries now process fewer rows before their joins.
The baseline is commit `f966015`.
The changes retain the original statistical rules and query results.

## Captured inputs

The source run is `20260909T001949Z`, captured under `generated/beam-integration/source/results/master-0ecad50`.
Its read-only database contains 38 heroes and 89,979 matches.
It contains 18,295,887 purchases, 10,318,560 player snapshots, and 1,719,760 team snapshots.
The cohort uses ranks 71 through 115.
Its cutoff is `2026-09-09T00:19:49Z`.

The measurements use DuckDB 1.5.5 on the local Mac.
Each connection uses one thread and a configured memory limit of 512 MiB.
Temporary files have a 384 MiB limit during these measurements.

## Query measurements

These times include execution and transfer into Python rows.
Each value is the median across all 38 heroes, with one comparison per hero.
The checkpoint queries run at both 20 and 30 minutes.
Item evidence uses discovery owners of a selected core, or the hero cohort when no core is available.

| Query | Before | After | Speedup |
| --- | ---: | ---: | ---: |
| Ownership checkpoint at 20 minutes | 1.661 s | 0.158 s | 10.5× |
| Ownership checkpoint at 30 minutes | 1.755 s | 0.151 s | 11.6× |
| Beam item counts | 0.460 s | 0.182 s | 2.5× |
| Core item pool | 0.180 s | 0.021 s | 8.6× |
| Core item statistics | 0.359 s | 0.042 s | 8.6× |

The decision query returns many wide rows, so Python transfer takes a large share of its measured time.
Separate `EXPLAIN ANALYZE` measurements identify SQL execution time.
These values are medians from three runs with a new connection for each run.
This method follows the [DuckDB query profiling guidance](https://duckdb.org/docs/current/guides/meta/explain_analyze).

| Hero | Previous decision query | Final decision query |
| --- | ---: | ---: |
| Lash | 0.977 s | 0.820 s |
| Viscous | 0.529 s | 0.298 s |
| Infernus | 0.699 s | 0.403 s |
| Kelvin | 0.507 s | 0.260 s |

These measurements cover the selected SQL queries.
They do not measure a complete evidence refresh or Steam installation.

## Changes

- Checkpoint joins use snapshots from the relevant players, matches, and existing 300-second freshness window.
- Beam and decision queries select relevant team snapshots once for both team joins.
- The decision query inlines its wide input to reduce disk spill for large hero cohorts.
- Core item queries bind the hero identifier before matching exact core owners.
- Shared query inputs select only the columns that subsequent operations need.

The queries retain their `ASOF LEFT JOIN` conditions.
They select the latest observation before checking completeness.
An incomplete latest observation cannot use an older complete observation as a replacement.
The item pool still uses purchase history through match completion.

## Result verification

The comparison covers six cases per hero: two checkpoints and four other queries.
The 228 comparisons cover 7,210,446 result rows.
The checks compare values, nulls, column names, column types, and specified row order.
Queries without specified row order use comparisons that preserve duplicate counts.

The guide replay checks Lash and Viscous at both checkpoints and all three wealth states.
All 27 selected purchase-guide nominations match the saved results.
The checks include core items, purchase sequences, tier pools, timing statistics, support counts, and beam model fingerprints.

Regression tests cover multiple purchases in one match, hero-specific item pools, and incomplete latest snapshots.
Local comparison scripts, query profiles, and result records are in `generated/sql-optimization/`.

## Repository verification

The complete [fast local gate](quality-gates.md#fast-local-gate) passed.

| Check | Result |
| --- | --- |
| `uv lock --check`, `uv sync --frozen`, `uv pip check` | Passed |
| Ruff format and lint, SQLFluff, Ty | Passed |
| Deptry, Tach, Complexipy, Vulture, Pylint duplicate-code check | Passed |
| Coverage with `pytest -W error` | 1,538 tests passed |
| `tools/quality_gate.py` | Passed; statement coverage 97.08%, branch coverage 91.87% |
| `uv build` | Source distribution and wheel built |
| Wheel inspection and smoke test outside the checkout | Passed |

The installed wheel contains all 53 SQL files with bytes identical to the source files.
The wheel smoke test checks SQL parsing, both ownership checkpoints, and both CLI help commands.
Live Steam sync did not run.
