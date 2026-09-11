# SQL join simplification

Three queries now use simpler joins and smaller intermediate results.
This report compares them with the [first optimization pass](sql-performance-2026-09-10.md).
The query results and statistical rules remain the same.

## Changes

The ownership checkpoint query replaces three temporal joins with grouped latest observations and equality joins.
It selects observations from the existing 300-second freshness window before grouping.
It calculates team completeness and total wealth once.

The player aggregate uses `arg_max_null` to retain a null value at the latest observation.
The team aggregate keeps wealth and player count together in one struct.
An incomplete latest observation cannot use an older complete observation as a replacement.
These choices follow the [DuckDB aggregate semantics](https://duckdb.org/docs/current/sql/functions/aggregates).

The decision query runs temporal joins on distinct match, team, and purchase-time keys.
It adds item details and enemy hero lists after these joins.
This reduces the columns that the temporal joins must sort and carry.
Purchases that share a checkpoint reuse its state without duplicate output rows.

The beam query uses two inner temporal joins because its existing filters already exclude missing team states.
One query stage replaces the separate own-team and enemy-team stages.
It retains the strict purchase-time boundary, freshness limits, and completeness checks.

The remaining outer joins preserve rows with unknown states or optional evidence.
The decision query retains temporal joins because purchase times vary.
SQLFluff configuration and exceptions remain unchanged.

## Measurements

The tests use the same captured database as the first pass: 89,979 matches and 38 heroes.
DuckDB 1.5.5 uses one thread and a configured memory limit of 512 MiB.
Temporary files have a 512 MiB limit.

`EXPLAIN (ANALYZE, FORMAT JSON)` supplies SQL execution times.
The checkpoint and decision measurements use five timed runs after one warmup per version.
The execution order alternates between versions.

Checkpoint execution time decreased by 6.9% to 13.0% across Viscous, Lash, Infernus, and Kelvin.
The comparisons cover both 20-minute and 30-minute checkpoints.

The decision query has these median execution times:

| Hero | First pass | Second pass | Runtime decrease |
| --- | ---: | ---: | ---: |
| Viscous | 0.288 s | 0.240 s | 16.5% |
| Lash | 0.742 s | 0.527 s | 28.9% |
| Infernus | 0.414 s | 0.321 s | 22.5% |
| Kelvin | 0.251 s | 0.218 s | 13.0% |

The beam rewrite reduces query stages but gives no consistent runtime decrease.
Twenty additional runs per version and hero show similar temporal join costs.
Table scan time varies more than join time.

The measurements cover individual SQL queries.
They do not measure a complete evidence refresh or Steam installation.

## Rejected alternatives

Ordinary range joins performed poorly when they replaced purchase-time `ASOF` joins.
The Viscous decision query increased from 0.727 seconds to 33.469 seconds in that experiment.
The final query retains DuckDB's temporal join operator.

Purchase extraction experiments used 410,896 purchases from 2,000 captured matches.
Direct list indexing produced the same results but no useful runtime decrease.
An extra shared-list stage increased runtime.
The extraction query remains unchanged.

## Result verification

All 152 comparisons passed across 38 heroes and 6,547,483 result rows.
They cover both ownership checkpoints, beam item counts, and decision rows.
The comparisons check values, nulls, column names, column types, duplicate counts, and row order.

All 27 selected Lash and Viscous purchase-guide nominations match the saved results.
The replay covers both checkpoints and all three wealth states.
Core items, purchase sequences, tier pools, timing statistics, support counts, and model fingerprints match.

Regression tests cover null wealth, incomplete latest team observations, missing teams, and purchases that share a checkpoint.
Local scripts, profiles, baseline SQL files, and comparison records are in `generated/sql-simplification/`.

## Repository verification

The complete [fast local gate](quality-gates.md#fast-local-gate) passed.

| Check | Result |
| --- | --- |
| Lock, frozen environment, and installed dependencies | Passed |
| Ruff format and lint, SQLFluff, Ty | Passed |
| Deptry, Tach, Complexipy, Vulture, Pylint duplicate-code check | Passed |
| Coverage with `pytest -W error` | 1,539 tests passed |
| `tools/quality_gate.py` | Passed; statement coverage 97.08%, branch coverage 91.87% |
| `uv build` | Source distribution and wheel built |
| Wheel inspection and smoke test outside the checkout | Passed |

Both distributions contain all 53 SQL files with bytes identical to the source files.
The installed wheel passes SQL parsing, both ownership checkpoints, null-state checks, beam observation checks, and both CLI help commands.
Live Steam sync did not run.

The subsequent [complete build verification](build-verification-2026-09-11.md) covers generation, reconstruction, and serialization for all 38 heroes.
