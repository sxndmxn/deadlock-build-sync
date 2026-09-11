# Complete SQL query audit

The main remaining problems are repeated state extraction, repeated item selection, repeated JSON serialization, and incomplete input checks.
Most administration statements and test statements are already simple.
A `LEFT JOIN`, CTE, or correlated subquery does not by itself indicate unnecessary work.

## Scope and evidence

This audit covers the current working tree on `experiment/purchase-guide-search`, based on commit `f966015`.
It includes both SQL optimization passes in PR #28.
This audit does not apply new product changes.

| Area | SQL files | Statements in files | Inline statements | Total statements |
| --- | ---: | ---: | ---: | ---: |
| Production | 53 | 56 | 0 | 56 |
| Purchase-search research | 7 | 7 | 3 | 10 |
| Tests | 72 | 95 | 0 | 95 |
| Total | 132 | 158 | 3 | **161** |

Every statement has an entry below.
Statement numbers distinguish multiple statements in one file.
The inventory includes repository SQL and new source fixtures.
Generated experiments, dependency files, build outputs, and SQL examples in documentation are outside this source-code inventory.

I read every statement, its caller, and the relevant result consumers.
I checked DuckDB plans, earlier measurements, new isolated measurements, and temporary-database reproductions.
The inventory and evidence are in `generated/sql-query-audit/`.

The SQL file inventory has this SHA-256 identifier:

```text
20ff62c8cd0b92cbdc15aa2286a0886ef2621550cf09f9c6a5aefba6a9c0cad9
```

**Confirmed** means a local execution demonstrated the behavior.
**Measured** means an isolated comparison checked results and execution time.
**Candidate** means the proposal still needs an implementation experiment.
A candidate speed improvement is not a measured result.

## Findings that need action

| Priority | Finding | Evidence | Affected statements |
| --- | --- | --- | --- |
| High | Match admission accepts a null reward-eligibility flag. | Confirmed with a temporary source table. | P21 |
| High | Filtering player rows before match validation can admit a match that subsequently expands to 13 players. | Confirmed with one extra player outside the rank range. | P21, P26 |
| High | Team completeness counts rows, including null wealth values. | Confirmed: five wealth values produced `observed_players = 6`. | P27, P32 |
| Medium | Beam counts admit purchases after recorded match completion. | Nine such observations passed the current filters in captured data. | P01, P28; review R02 |
| Medium | Item-pool queries repeat first-purchase selection. | Reusing the stored ordinal reduced measured SQL time by 11–19%. | P07 |
| Medium | Decision extraction serializes identical tier slates for each decision. | Serialization before the join reduced measured SQL time by 15–20%. | P19 |
| Medium | Personal-state extraction can select a same-second state that later filters reject. | 94,460 positive-wealth purchases use same-second personal states. | P28, P01, P06, R02 |
| Medium | Three research queries bypass file-based SQLFluff checks and the SQL-file fingerprint. | Confirmed from their inline Python definitions and `source_identity`. | R08–R10 |
| Lower | History membership uses a multiplying join with an `OR` condition. | Three purchases produced four rows with duplicate hero actors. | P09 |
| Lower | Split-boundary detection searches every catalog and schema. | An unrelated attached table produced a positive result. | P03 |

The temporary reproductions demonstrate failure conditions, not their prevalence in live data.
The captured database has no null player-snapshot values.
Every captured match has 12 distinct player slots.
Its one duplicate-hero group is in the test partition, which production discovery excludes.
Production discovery also rejects duplicate hero appearances when it constructs the hero dataset.
The P09 finding therefore concerns helper robustness under a violated input assumption.

The captured source does not retain `rewards_eligible` in `player_matches`.
This audit cannot measure null reward flags in that source without another remote extraction.

### State and count semantics

DuckDB ignores null inputs in most aggregates.
`count(*)` counts rows, while `count(column)` counts non-null values.
`arg_max_null` retains a null result at the greatest timestamp.
These differences matter for eligibility and state completeness. [DuckDB aggregate functions](https://duckdb.org/docs/current/sql/functions/aggregates).

Multiple `unnest` expressions align list positions and fill missing positions with nulls.
They do not form a Cartesian product.
Unequal array lengths therefore need validation before team completeness uses their output. [DuckDB unnesting](https://duckdb.org/docs/current/sql/query_syntax/unnest).

The extraction summary calls 16,849,694 personal-wealth observations valid because their values are non-null.
Only 9,098,129 have positive wealth and an age from 1 through 120 seconds.
These counts cover all extracted first purchases, before hero, rank, and partition filters.
The current summary names describe stronger validity than their queries check.

Of 94,460 same-second personal states, 214 have a positive strict-prior snapshot within 120 seconds.
Another comparison finds 74,394 with such a snapshot within 300 seconds.
These are possible observation counts before the remaining eligibility filters.
Changing personal-state extraction would change evidence and requires separate regression and guide comparisons.

### Confirmed efficiency opportunities

The following proposals remain outside product code.
The comparisons use the captured 89,979-match database and DuckDB 1.5.5.
Each connection uses one thread and a configured memory limit of 512 MiB.
Each measurement uses five timed runs after one warmup, with alternating execution order.
`EXPLAIN (ANALYZE, FORMAT JSON)` supplies execution time.

| Query proposal | Viscous | Lash | Infernus | Kelvin |
| --- | ---: | ---: | ---: | ---: |
| P07: reuse `item_purchase_ordinal = 1` | 14.3 → 11.6 ms | 22.8 → 20.2 ms | 18.3 → 15.9 ms | 12.8 → 10.8 ms |
| P19: serialize each tier slate before the join | 324.9 → 264.3 ms | 677.8 → 539.7 ms | 480.3 → 387.4 ms | 270.4 → 228.6 ms |

P07 uses discovery owners of the previously selected cores.
P19 uses one hero at a time and measures the selection portion of table creation.
It does not measure a complete extraction or table-write operation.
All eight comparisons preserve column names, types, values, and duplicate counts.
The comparisons cover 1,135,827 rows.
The comparison treats row order as unspecified; separate order checks remain necessary before implementation.

The previous optimization passes already measured other changes.
See [the first pass](sql-performance-2026-09-10.md) and [the second pass](sql-performance-2026-09-11.md).
Those gains are already present in the audited working tree.

## Production analytics statements

### P01: beam/select_item_counts.sql

[Source](../src/deadlock_build_sync/offline/sql/beam/select_item_counts.sql)

- **What it does:** Counts purchases and wins by item, wealth bin, and relative wealth. It uses discovery matches and strict-prior team states.
- **Can it be simpler?** Slightly. The ordinal check repeats the `first_purchases` table contract. The recent removal of two outer joins is appropriate.
- **Could it be more efficient?** Further shared state preparation is a candidate. Current inner temporal join costs are similar to the earlier outer joins.
- **Unnecessarily complex?** Mostly no. Keep the two team lookups and statistical filters. Add a match-duration boundary; nine late observations currently pass.

The SQL returns raw counts. Python applies Bayesian smoothing and scores that include cost.
It does not calculate joint core win rates.
A hero can contribute purchases to several item cells; summed cell counts are not distinct match counts.

### P02: discovery/count_hero_appearances.sql

[Source](../src/deadlock_build_sync/offline/sql/discovery/count_hero_appearances.sql)

- **What it does:** Counts all source appearances for one hero. The caller uses only the distinction between zero and nonzero.
- **Can it be simpler?** An existence query would state the actual requirement more directly.
- **Could it be more efficient?** An existence query could stop after a match. This is a small, unmeasured improvement.
- **Unnecessarily complex?** No. It performs more counting than the caller needs, but the statement is simple.

### P03: discovery/count_split_boundaries.sql

[Source](../src/deadlock_build_sync/offline/sql/discovery/count_split_boundaries.sql)

- **What it does:** Counts catalog tables named `split_boundaries`. Exactly one match selects the fixed-partition path.
- **Can it be simpler?** Use a catalog-qualified and schema-qualified existence check.
- **Could it be more efficient?** Metadata cost is negligible. Correct table identification matters more than runtime.
- **Unnecessarily complex?** The count-equals-one convention is unnecessary. An unrelated attached table can change the selected partition method.

### P04: discovery/create_fixed_partitions.sql

[Source](../src/deadlock_build_sync/offline/sql/discovery/create_fixed_partitions.sql)

- **What it does:** Splits training matches into discovery and selection using frozen timestamps. It retains validation and excludes test matches.
- **Can it be simpler?** A shared one-row-per-match relation could remove repeated player grouping. This needs a broader extraction change.
- **Could it be more efficient?** Reuse match start times if other split queries also need them. The current grouping is bounded by player appearances.
- **Unnecessarily complex?** No. The single-row boundary cross join is intentional. It does not multiply output when the boundary table contains one row.

Do not replace frozen timestamps with current row counts.
Rank expansion must not move existing matches between partitions.

### P05: discovery/create_ranked_partitions.sql

[Source](../src/deadlock_build_sync/offline/sql/discovery/create_ranked_partitions.sql)

- **What it does:** Assigns the earliest 75% of training matches to discovery when frozen boundaries are absent. It appends validation matches.
- **Can it be simpler?** Little. The window functions express a deterministic whole-match split.
- **Could it be more efficient?** A shared match relation could reduce repeated grouping. Sorting match keys remains necessary.
- **Unnecessarily complex?** No. `UNION ALL` is appropriate because training and validation sets are disjoint.

This compatibility path is not identical to the frozen timestamp path when start times tie.
A shorter `NTILE` expression can change rounding and partition membership.

### P06: discovery/select_decision_rows.sql

[Source](../src/deadlock_build_sync/offline/sql/discovery/select_decision_rows.sql)

- **What it does:** Loads hero decisions from discovery and validation. It attaches strict-prior team states and enemy compositions.
- **Can it be simpler?** Its long final projection preserves the 45-column result contract. Removing that projection would conceal the contract.
- **Could it be more efficient?** The recent distinct-key joins reduced measured execution time. A shared strict-prior state table remains a broader candidate.
- **Unnecessarily complex?** No major remaining excess. `DISTINCT` prevents multiplication when decisions share a checkpoint. Outer joins preserve missing team states.

The `NOT MATERIALIZED` choice has local measurement support.
Do not remove it solely to reduce syntax.
DuckDB can inline or materialize CTEs, with different costs for repeated wide inputs. [DuckDB CTE handling](https://duckdb.org/docs/current/sql/query_syntax/with).

The query returns stale or incomplete team evidence for downstream handling.
Moving completeness filters inside the snapshot inputs would change which observation counts as latest.

### P07: discovery/select_item_pool_purchases.sql

[Source](../src/deadlock_build_sync/offline/sql/discovery/select_item_pool_purchases.sql)

- **What it does:** Returns each exact core owner's first purchase of each item before match completion, with personal state evidence.
- **Can it be simpler?** Yes. Use the existing `item_purchase_ordinal = 1` value instead of another partitioned `row_number`.
- **Could it be more efficient?** The proposed filter reduced measured SQL time by 11–19% across four heroes.
- **Unnecessarily complex?** Yes. It recalculates first-purchase selection that extraction already stores.

Keep the exact actor membership join and the hero predicate.
Verify tie behavior and fixture schemas before applying the proposal.
The current pool intentionally uses purchases through match completion, including items bought after core ownership.

### P08: discovery/select_landmark_rows.sql

[Source](../src/deadlock_build_sync/offline/sql/discovery/select_landmark_rows.sql)

- **What it does:** Loads each hero actor's wealth, team lead, and enemy composition before a fixed ownership checkpoint.
- **Can it be simpler?** The recent grouped-state rewrite already removes three temporal joins and repeated freshness conditions.
- **Could it be more efficient?** Shared checkpoint aggregates across heroes are a candidate. They could cost more memory than the current filtered groups.
- **Unnecessarily complex?** No. The struct keeps team wealth and completeness from the same observation. The final projection preserves tuple order.

Keep null-preserving latest-state selection and the strict checkpoint boundary.
The remaining equality outer joins keep unknown states in the hero population.
Dropping those rows would change support and hero baseline denominators.

### P09: discovery/select_purchase_event_histories.sql

[Source](../src/deadlock_build_sync/offline/sql/discovery/select_purchase_event_histories.sql)

- **What it does:** Loads purchases for the selected hero actors and their enemies. It excludes unrelated friendly actors.
- **Can it be simpler?** Yes. A `SEMI JOIN` expresses membership without copying matching actor rows.
- **Could it be more efficient?** The membership form could reduce intermediate rows. Measure it before splitting the `OR` into separate scans.
- **Unnecessarily complex?** Partly. The multiplying inner join is unnecessary for an existence condition. The actor-or-enemy condition itself has a purpose.

A temporary duplicate-hero case returned four rows from three purchases.
The proposed semi join returned three.
The normal hero-data validator rejects duplicate appearances before production guide generation.
Keep the final event order because inventory reconstruction depends on ordered histories.

### P10: discovery/select_purchase_histories.sql

[Source](../src/deadlock_build_sync/offline/sql/discovery/select_purchase_histories.sql)

- **What it does:** Loads hero purchases before the ownership checkpoint from the discovery partition table, including selection and validation histories.
- **Can it be simpler?** No material simplification. The partition join, hero filter, and strict time filter define the requested history.
- **Could it be more efficient?** Passing the selected actor set could avoid histories that the later rank filter discards. This needs measurement.
- **Unnecessarily complex?** No. Keep event ordering and sold-time values for inventory reconstruction.

### P18: extract/create_compositions.sql

[Source](../src/deadlock_build_sync/offline/sql/extract/create_compositions.sql)

- **What it does:** Builds a sorted hero list for each match and team from local player records.
- **Can it be simpler?** `list(hero_id ORDER BY hero_id)` is an alternative spelling. It is not a demonstrated improvement.
- **Could it be more efficient?** Little. It groups the smaller local player table once.
- **Unnecessarily complex?** No. Sorting makes composition arrays stable. Do not remove duplicates silently; they can indicate malformed source data.

### P19: extract/create_decision_opportunities.sql

[Source](../src/deadlock_build_sync/offline/sql/extract/create_decision_opportunities.sql)

- **What it does:** Selects the first unambiguous purchase per actor, phase, and item tier. It adds a tier-wide item slate and action fields.
- **Can it be simpler?** Yes. Serialize the slate in the tier aggregate and join the finished JSON value to each decision.
- **Could it be more efficient?** The proposal reduced measured selection time by 15–20% across four heroes.
- **Unnecessarily complex?** Partly. Repeated JSON serialization is unnecessary. The purchase-selection window and explicit output columns protect the sampling contract.

The slate contains every catalog item in the tier and includes a save option.
Here, a slate is the candidate item list stored in each decision.
It does not prove affordability, compatibility, or observed saving behavior.
`save_action_observed` remains false; these rows are not an unbiased sample of all possible purchase decisions.

### P21: extract/create_eligible_matches.sql

[Source](../src/deadlock_build_sync/offline/sql/extract/create_eligible_matches.sql)

- **What it does:** Selects completed matches with 12 distinct slots, six players per team, valid outcomes, and reward eligibility.
- **Can it be simpler?** Partly. The outcome membership aggregate is redundant with the total and exact win/loss counts.
- **Could it be more efficient?** An additional direct upper start-time bound could improve remote filtering. Benchmark it without removing the completion-time condition.
- **Unnecessarily complex?** Mostly no. Admission checks have distinct safety purposes. Correct the null-eligibility and filtered-extra-player cases before performance changes.

Require twelve explicitly true reward flags, or equivalent null-rejecting logic.
Validate the complete source match before later extraction expands its identifier back into player rows.
The current first-stage rank filter can conceal an additional player that subsequent joins restore.
Also validate consistent match metadata and agreement between outcome labels and the `won` field used downstream.

### P22: extract/create_first_purchases.sql

[Source](../src/deadlock_build_sync/offline/sql/extract/create_first_purchases.sql)

- **What it does:** Keeps the first purchase of each item, adds folds and phases, joins team states, and calculates earlier purchase counts and spend.
- **Can it be simpler?** Yes. Two nested state stages carry full purchase rows through temporal joins. The narrower-key approach used by P06 is a candidate.
- **Could it be more efficient?** Possibly substantially. It processes all first purchases, and downstream queries calculate strict-prior team states again.
- **Unnecessarily complex?** Partly. The wide state chain duplicates later work. Do not remove exported fields before checking all analysis consumers.

Its team joins allow observations at the purchase timestamp through `>=`.
P01 and P06 use strict `>` boundaries and different freshness limits.
A shared state table needs one explicit semantic contract before it can replace these calculations.

The running spend and count use first purchases only.
They exclude repeat purchases and do not represent actual remaining currency.
The `RANGE ... 1 PRECEDING` frame correctly excludes every purchase at the current second.

### P23: extract/create_hero_account_counts.sql

[Source](../src/deadlock_build_sync/offline/sql/extract/create_hero_account_counts.sql)

- **What it does:** Counts distinct source accounts for each hero in eligible matches.
- **Can it be simpler?** The query itself is already direct.
- **Could it be more efficient?** Reuse a local admitted-player relation that includes account identifiers, if remote rereads prove expensive.
- **Unnecessarily complex?** No. Distinct accounts differ from player appearances and must not become a plain row count.

Null account identifiers do not contribute to the distinct count.
Do not retain additional account data merely to save a small query without evaluating the storage tradeoff.

### P25: extract/create_match_folds.sql

[Source](../src/deadlock_build_sync/offline/sql/extract/create_match_folds.sql)

- **What it does:** Assigns each complete match to train, validation, or test using frozen time boundaries.
- **Can it be simpler?** A shared match-start relation could remove repeated grouping of player rows.
- **Could it be more efficient?** Reuse that relation across P04 and P31 if profiling justifies another table.
- **Unnecessarily complex?** No. The boundary cross join reads one row. Grouping keeps all players in one fold.

### P26: extract/create_player_matches.sql

[Source](../src/deadlock_build_sync/offline/sql/extract/create_player_matches.sql)

- **What it does:** Copies admitted player attributes locally, converts team labels, and orders rows by hero and actor.
- **Can it be simpler?** The projection is appropriate. Shared admitted-player extraction could remove similar projections elsewhere.
- **Could it be more efficient?** Remote reuse is a candidate. Measure extraction plus later hero reads before removing the physical hero ordering.
- **Unnecessarily complex?** No. Its main risk is admitting all source rows for an identifier that P21 validated after filtering.

### P27: extract/create_player_snapshots.sql

[Source](../src/deadlock_build_sync/offline/sql/extract/create_player_snapshots.sql)

- **What it does:** Expands paired timestamp and personal-wealth arrays into local player snapshots.
- **Can it be simpler?** No. Paired `unnest` expressions state the array alignment directly.
- **Could it be more efficient?** Reuse these local rows when constructing team snapshots instead of expanding the same remote arrays again.
- **Unnecessarily complex?** No. Missing validation of array lengths, timestamp order, and duplicate actor/timestamp keys needs attention.

The later latest-state queries assume one unambiguous observation per actor and timestamp.
Reject or explicitly resolve malformed source arrays instead of allowing arbitrary ties.

### P28: extract/create_purchases.sql

[Source](../src/deadlock_build_sync/offline/sql/extract/create_purchases.sql)

- **What it does:** Expands item arrays, adds catalog data, finds personal wealth, and assigns event order, simultaneous-purchase counts, and item ordinals.
- **Can it be simpler?** Yes in principle. Personal-state selection repeats nested list operations for wealth and timestamp.
- **Could it be more efficient?** A normalized snapshot lookup is a candidate. Earlier direct-index and shared-list rewrites produced no useful overall gain.
- **Unnecessarily complex?** Partly. State lookup is difficult to inspect. The three windows calculate different facts and cannot be merged indiscriminately.

The current lookup selects the last eligible array position, not an explicitly ordered latest timestamp.
It allows same-second snapshots and relies on source-array order.
Changing it to strict-prior temporal selection requires result and statistical review.

The catalog inner join silently removes unknown item identifiers.
Audit unmatched items and paired-array lengths before treating purchase histories as complete.
Source item identifiers should be unique in `item_assets`, because duplicate catalog rows can multiply purchases before the windows.

### P31: extract/create_split_boundaries.sql

[Source](../src/deadlock_build_sync/offline/sql/extract/create_split_boundaries.sql)

- **What it does:** Calculates the 45%, 60%, and 80% start-time quantiles from the starting rank cohort.
- **Can it be simpler?** A list-valued quantile expression can calculate the three cutoffs together, followed by an explicit projection.
- **Could it be more efficient?** Possibly, but the input is only one row per match. A new projection may offset the readability benefit.
- **Unnecessarily complex?** No. Grouping before quantiles prevents twelve player rows from defining twelve independent observations.

Keep the starting-cohort filter and null fallback behavior.
The boundaries must remain fixed when rank coverage expands.

### P32: extract/create_team_snapshots.sql

[Source](../src/deadlock_build_sync/offline/sql/extract/create_team_snapshots.sql)

- **What it does:** Expands remote wealth arrays and sums player wealth by match, team, and timestamp.
- **Can it be simpler?** Yes across the extraction workflow. Join local player snapshots to local player teams and group once.
- **Could it be more efficient?** That could remove one remote array read and expansion. Remote performance remains unmeasured in this audit.
- **Unnecessarily complex?** The grouping is necessary. Repeated extraction is avoidable. Its current row count does not establish six complete player observations.

Retain player-slot identity until completeness checks finish.
Check distinct players, non-null wealth, and duplicate timestamps together.
Filtering away the newest incomplete team observation can incorrectly expose an older complete observation as current.

### P55: production/select_path_cohort_summary.sql

[Source](../src/deadlock_build_sync/offline/sql/production/select_path_cohort_summary.sql)

- **What it does:** Counts exact core-owner appearances and calculates their train/validation median final wealth.
- **Can it be simpler?** It is already one aggregate over two membership joins.
- **Could it be more efficient?** Bind the hero identifier, as P56 already does, to permit earlier hero filtering. Measure the small cohort query first.
- **Unnecessarily complex?** No. The fold filter on median wealth prevents test outcomes from changing selection evidence.

The total owner count includes the supplied full membership set.
Do not apply the median's train/validation filter to that count accidentally.

### P56: production/select_path_item_metrics.sql

[Source](../src/deadlock_build_sync/offline/sql/production/select_path_item_metrics.sql)

- **What it does:** Produces item adoption, outcomes, purchase timing, wealth quantiles, repeat-event counts, and supported imbue targets for exact core owners.
- **Can it be simpler?** Partly. `QUALIFY` can remove one imbue-ranking wrapper. Shared quantile lists could replace repeated expressions with explicit final projections.
- **Could it be more efficient?** Hero filtering is already effective. Further quantile consolidation needs measurement; matched core cohorts can be small.
- **Unnecessarily complex?** Mostly no. Separate fold aggregates and separate purchase-event counts represent different statistical populations.

DuckDB supports a list of quantile positions in one aggregate. [Quantile functions](https://duckdb.org/docs/current/sql/functions/aggregates#quantile_contx-pos).
Do not replace first-purchase adopter counts with purchase-event counts.
Keep test observations outside imbue selection and selection-only timing metrics.
The final outer join is necessary for items without an eligible imbue target.

## Production administration and scalar statements

Each row below audits one statement.
For the nine drop statements, `CREATE OR REPLACE TABLE` is a possible workflow simplification, not a standalone replacement for `DROP`.
Coordinate each change with its create statement and retry behavior.
A failed replacement must not leave an older table that the workflow mistakes for current data.

| ID and source | What it does | Can it be simpler? | Could it be more efficient? | Unnecessarily complex? |
| --- | --- | --- | --- | --- |
| **P11** [extract/attach_remote.sql](../src/deadlock_build_sync/offline/sql/extract/attach_remote.sql) | Attaches the current remote DuckLake catalog read-only. | No. This obtains the current snapshot identifier. | Keep the later pinned attachment for consistent reads. | No. |
| **P12** [extract/attach_remote_snapshot.sql](../src/deadlock_build_sync/offline/sql/extract/attach_remote_snapshot.sql) | Attaches the selected immutable snapshot read-only. | No. The version parameter is necessary. | Snapshot pinning avoids inconsistent repeated extraction. | No. |
| **P13** [extract/count_hero_accounts.sql](../src/deadlock_build_sync/offline/sql/extract/count_hero_accounts.sql) | Counts rows in the per-hero account summary. | No. One scalar aggregate. | Tiny grouped input. No material optimization needed. | No. |
| **P14** [extract/count_heroes.sql](../src/deadlock_build_sync/offline/sql/extract/count_heroes.sql) | Counts distinct hero identifiers in player records. | Possibly reuse P13 after validating non-null hero identifiers. | Could avoid another player-table scan; unmeasured. | No, but possibly redundant work. |
| **P15** [extract/count_purchase_net_worth.sql](../src/deadlock_build_sync/offline/sql/extract/count_purchase_net_worth.sql) | Counts non-null personal-wealth values in first purchases. | No. Correct the misleading validity interpretation instead. | Could share a scan with P17 and related diagnostics. | No. It does not check positivity or freshness. |
| **P16** [extract/count_table_rows.sql](../src/deadlock_build_sync/offline/sql/extract/count_table_rows.sql) | Counts rows in a table selected through a bound name. | No. Keep `query_table` for identifier binding. | Usually small metadata or count work; profile actual calls. | No. |
| **P17** [extract/count_team_lead.sql](../src/deadlock_build_sync/offline/sql/extract/count_team_lead.sql) | Counts non-null team-lead values in first purchases. | No. It is an availability count, not full validity. | Could share the P15 scan. | No. It does not check freshness or completeness. |
| **P20** [extract/create_ducklake_secret.sql](../src/deadlock_build_sync/offline/sql/extract/create_ducklake_secret.sql) | Defines the DuckLake metadata connection through a bound path. | No. The standard secret statement is direct. | Connection setup has no meaningful join optimization. | No. |
| **P24** [extract/create_item_assets.sql](../src/deadlock_build_sync/offline/sql/extract/create_item_assets.sql) | Defines the local item-catalog schema. | No. Explicit column types are appropriate. | Enforce or validate unique, non-null item identifiers before joins. | No. Missing key validation is a correctness concern. |
| **P29** [extract/create_s3_secret.sql](../src/deadlock_build_sync/offline/sql/extract/create_s3_secret.sql) | Configures anonymous HTTPS access to the public S3 cache. | No. The endpoint settings are required. | Network and caching behavior matter more than syntax. | No. |
| **P30** [extract/create_source_snapshot.sql](../src/deadlock_build_sync/offline/sql/extract/create_source_snapshot.sql) | Stores the pinned snapshot identifier as a BIGINT. | No. One row with an explicit type. | Negligible work. | No. |
| **P33** [extract/detach_remote.sql](../src/deadlock_build_sync/offline/sql/extract/detach_remote.sql) | Closes the unpinned remote attachment. | No. The next attachment pins its version. | Necessary connection transition. | No. |
| **P34** [extract/drop_decision_opportunities.sql](../src/deadlock_build_sync/offline/sql/extract/drop_decision_opportunities.sql) | Drops the previous local decision table before rebuilding it. | Coordinate replacement with P19. | One metadata operation; no material runtime gain expected. | No individually; repeated rebuild steps can be reduced. |
| **P35** [extract/drop_eligible_matches.sql](../src/deadlock_build_sync/offline/sql/extract/drop_eligible_matches.sql) | Drops the previous local eligible-match table. | Coordinate replacement with P21. | One metadata operation; retain failure handling. | No individually; repeated rebuild steps can be reduced. |
| **P36** [extract/drop_first_purchases.sql](../src/deadlock_build_sync/offline/sql/extract/drop_first_purchases.sql) | Drops the previous local first-purchase table. | Coordinate replacement with P22. | One metadata operation; retain failure handling. | No individually; repeated rebuild steps can be reduced. |
| **P37** [extract/drop_hero_account_counts.sql](../src/deadlock_build_sync/offline/sql/extract/drop_hero_account_counts.sql) | Drops the previous local hero-account summary. | Coordinate replacement with P23. | One metadata operation. | No individually; repeated rebuild steps can be reduced. |
| **P38** [extract/drop_item_assets.sql](../src/deadlock_build_sync/offline/sql/extract/drop_item_assets.sql) | Drops the previous local item catalog. | Coordinate replacement with P24 and its inserts. | One metadata operation. | No individually; repeated rebuild steps can be reduced. |
| **P39** [extract/drop_player_matches.sql](../src/deadlock_build_sync/offline/sql/extract/drop_player_matches.sql) | Drops the previous local player table. | Coordinate replacement with P26. | One metadata operation; retain failure handling. | No individually; repeated rebuild steps can be reduced. |
| **P40** [extract/drop_player_snapshots.sql](../src/deadlock_build_sync/offline/sql/extract/drop_player_snapshots.sql) | Drops the previous local player snapshots. | Coordinate replacement with P27. | One metadata operation; retain failure handling. | No individually; repeated rebuild steps can be reduced. |
| **P41** [extract/drop_purchases.sql](../src/deadlock_build_sync/offline/sql/extract/drop_purchases.sql) | Drops the previous local purchase table. | Coordinate replacement with P28. | One metadata operation; retain failure handling. | No individually; repeated rebuild steps can be reduced. |
| **P42** [extract/drop_team_snapshots.sql](../src/deadlock_build_sync/offline/sql/extract/drop_team_snapshots.sql) | Drops the previous local team snapshots. | Coordinate replacement with P32. | One metadata operation; retain failure handling. | No individually; repeated rebuild steps can be reduced. |
| **P43** [extract/export_table.sql](../src/deadlock_build_sync/offline/sql/extract/export_table.sql) | Exports a bound table to Zstandard-compressed Parquet. | No. The dynamic schema is intentional. | Measure compression and row-group choices on real exports. | No. The 100,000-row group size is a tuning choice. |
| **P44** [extract/fill_split_boundaries.sql](../src/deadlock_build_sync/offline/sql/extract/fill_split_boundaries.sql) | Fills null split cutoffs from fixed time fractions. | Could fold fallback values into P31 with caller changes. | One-row update. Negligible performance benefit. | No. Separate fallback handling is readable. |
| **P45** [extract/insert_item_assets.sql](../src/deadlock_build_sync/offline/sql/extract/insert_item_assets.sql) | Inserts one catalog row through nine bound values. | Add explicit target columns for schema clarity. | The caller batches a small catalog. Bulk alternatives are unnecessary. | No. |
| **P46** [extract/load_extensions.sql](../src/deadlock_build_sync/offline/sql/extract/load_extensions.sql); statement 1 | Installs the DuckLake extension. | Could move installation to environment setup. | Installation is setup work, not per-row query work. | No. |
| **P47** [extract/load_extensions.sql](../src/deadlock_build_sync/offline/sql/extract/load_extensions.sql); statement 2 | Loads the DuckLake extension into this connection. | No, unless connection setup guarantees an existing load. | Negligible compared with extraction. | No. |
| **P48** [extract/load_extensions.sql](../src/deadlock_build_sync/offline/sql/extract/load_extensions.sql); statement 3 | Installs the httpfs extension. | Could move installation to environment setup. | Installation is setup work, not per-row query work. | No. |
| **P49** [extract/load_extensions.sql](../src/deadlock_build_sync/offline/sql/extract/load_extensions.sql); statement 4 | Loads httpfs for remote file access. | No, unless connection setup guarantees an existing load. | Negligible compared with remote reads. | No. |
| **P50** [extract/select_current_snapshot.sql](../src/deadlock_build_sync/offline/sql/extract/select_current_snapshot.sql) | Reads the current remote snapshot identifier. | No. One metadata lookup. | Keep one lookup followed by the pinned attachment. | No. |
| **P51** [extract/select_source_snapshot.sql](../src/deadlock_build_sync/offline/sql/extract/select_source_snapshot.sql) | Reads the locally recorded snapshot identifier. | No. One-row lookup. | Negligible work. | No. |
| **P52** [extract/set_memory_limit.sql](../src/deadlock_build_sync/offline/sql/extract/set_memory_limit.sql) | Sets the extraction memory limit to 12 GB. | No syntactic simplification. | Make resource limits appropriate for the host. Fixed values can cause memory pressure. | No. This is a configuration issue. |
| **P53** [extract/set_temp_directory.sql](../src/deadlock_build_sync/offline/sql/extract/set_temp_directory.sql) | Sets the spill directory through a bound path. | No. The run-specific location supports cleanup. | Ensure enough temporary storage for measured workloads. | No. |
| **P54** [extract/set_threads.sql](../src/deadlock_build_sync/offline/sql/extract/set_threads.sql) | Sets extraction parallelism to eight threads. | No syntactic simplification. | Measure thread and memory settings together on the target host. | No. This is a configuration issue. |

## Purchase-search research statements

These statements belong to `tools/purchase_search`.
They support algorithm experiments and do not directly install Steam builds.
Their observation and checkpoint rules are not identical to the production rules.

### R01: create_eligible_matches.sql

[Source](../tools/purchase_search/sql/create_eligible_matches.sql)

- **What it does:** Creates a partition-specific match set and excludes entire matches with repeated hero identifiers.
- **Can it be simpler?** A named duplicate-match relation and an anti join could make the exclusion easier to inspect.
- **Could it be more efficient?** Possibly, but do not assume the correlated `NOT EXISTS` executes once per match.
- **Unnecessarily complex?** No confirmed excess. The grouping inside `NOT EXISTS` detects repeated appearances of any hero, not just the requested hero.

DuckDB decorrelates correlated subqueries into execution plans with relational operators. [DuckDB subquery optimization](https://duckdb.org/2023/05/26/correlated-subqueries-in-sql).
Inspect the actual plan before replacing this query with more SQL.

### R02: create_observations.sql

[Source](../tools/purchase_search/sql/create_observations.sql)

- **What it does:** Builds item-purchase observations for a partition using personal freshness, both team states, wealth bins, and relative wealth.
- **Can it be simpler?** Yes. Replace two outer temporal joins with inner joins and remove the separate own-team and enemy-team wrapper stages.
- **Could it be more efficient?** Prefilter team snapshots to eligible matches. Benchmark this broader partition workload before copying production timing claims.
- **Unnecessarily complex?** Yes in its state-stage structure. Its completeness, time, and positive-wealth conditions remain necessary.

The rank range is hard-coded to 71–115.
Keep hero baseline counts consistent if the source includes expanded ranks.
Add the same match-duration boundary proposed for P01.

### R03: select_histories.sql

[Source](../tools/purchase_search/sql/select_histories.sql)

- **What it does:** Loads a hero's ordered purchase and sale history for one match fold.
- **Can it be simpler?** No material simplification.
- **Could it be more efficient?** Restrict histories to `experiment_matches`; excluded matches currently consume read and reconstruction resources.
- **Unnecessarily complex?** No. The missing experiment membership filter is avoidable extra work, not a join-complexity problem.

### R04: select_item_counts.sql

[Source](../tools/purchase_search/sql/select_item_counts.sql)

- **What it does:** Counts purchases and wins by hero, wealth bin, relative state, and item.
- **Can it be simpler?** No. One grouped aggregate with stable output ordering.
- **Could it be more efficient?** Little within this statement. Reuse the prepared observation table as the caller already does.
- **Unnecessarily complex?** No. These are purchase counts, not joint-build ownership counts.

### R05: select_landmarks.sql

[Source](../tools/purchase_search/sql/select_landmarks.sql)

- **What it does:** Produces hero state and inventory checkpoints at 600, 1201, and 1801 seconds. Unknown relative wealth has the value `-1`.
- **Can it be simpler?** Yes. It retains three wide temporal join stages and repeated ratio expressions that production P08 already replaced.
- **Could it be more efficient?** Group recent snapshots by checkpoint and actor, then join the smaller state records. Benchmark the three-checkpoint workload.
- **Unnecessarily complex?** Yes in the wide state chain and repeated expressions. Keep the deliberate three-checkpoint expansion and unknown-state population.

The 1201-second and 1801-second boundaries include observations at exactly 1200 and 1800 seconds.
Production P08 excludes observations at those exact boundaries.
Align the specifications before presenting research and production outputs as equivalent.

### R06: select_query_sample.sql

[Source](../tools/purchase_search/sql/select_query_sample.sql)

- **What it does:** Selects one observation per hero/match, then limits the number of matches per hero through deterministic hash ordering.
- **Can it be simpler?** An aggregate that selects one full row could replace the first window. It would need careful field and tie handling.
- **Could it be more efficient?** Possibly. There are two ordering stages, but they implement two different sampling limits.
- **Unnecessarily complex?** No confirmed excess. Keep both sampling levels unless an equivalent measured replacement exists.

The hash algorithm can change between DuckDB versions. [DuckDB hash documentation](https://duckdb.org/docs/current/sql/functions/utility#hashvalue).
The project currently pins DuckDB 1.5.5.
Include the engine version in research cache identity before changing that dependency, or store and reuse the sampled identifiers.

### R07: select_state_counts.sql

[Source](../tools/purchase_search/sql/select_state_counts.sql)

- **What it does:** Counts distinct hero-match observations within each wealth and relative-state cell.
- **Can it be simpler?** The distinct stage could use equivalent grouping, but that would not remove its purpose.
- **Could it be more efficient?** Measure before introducing a shared state-summary table. The current query already removes repeated item purchases from each cell.
- **Unnecessarily complex?** No. Removing `DISTINCT` would count matches with more purchases multiple times.

A match can enter several cells during its progression.
Summing all cells does not produce a distinct overall match count.

### R08: inline hero counts

[Source: dataset.py, line 287](../tools/purchase_search/dataset.py#L287)

- **What it does:** Counts hero appearances and wins across experiment-eligible matches.
- **Can it be simpler?** Move the statement into the existing SQL directory and use its existing file loader.
- **Could it be more efficient?** The grouped join is reasonable. Apply consistent cohort filters when source ranks expand.
- **Unnecessarily complex?** The SQL is simple. Keeping it inline creates an unnecessary second storage and lint path.

Its hero denominator currently includes all eligible source ranks.
R02 restricts purchase observations to ranks 71–115.
These populations agree for the captured source, but can differ for expanded-rank inputs.

### R09: inline eligible-match count

[Source: dataset.py, line 290](../tools/purchase_search/dataset.py#L290)

- **What it does:** Counts rows in the prepared experiment match table.
- **Can it be simpler?** The SQL cannot usefully shrink. Move it to the existing SQL directory.
- **Could it be more efficient?** No meaningful opportunity in this small scalar query.
- **Unnecessarily complex?** No SQL complexity. Inline storage bypasses the existing SQL-file controls.

### R10: inline excluded-match count

[Source: dataset.py, line 293](../tools/purchase_search/dataset.py#L293)

- **What it does:** Counts partition matches absent from the prepared experiment match set.
- **Can it be simpler?** Use an anti join or `NOT EXISTS` to express exclusion explicitly. Move the statement into the SQL directory.
- **Could it be more efficient?** Possibly combine total and eligible counts if subset and uniqueness conditions are guaranteed. No gain has been measured.
- **Unnecessarily complex?** Not computationally. `NOT IN` introduces avoidable null-sensitive semantics, and inline storage bypasses the file controls.

## Join and extraction recommendations

1. Correct admission and snapshot completeness before changing shared state preparation.
2. Add consistent match-duration limits to purchase observations.
3. Apply the measured ordinal and tier-slate simplifications with regression tests.
4. Compare a narrow-key extraction join with P22 using the full extraction workload.
5. Compare local snapshot reuse with the repeated remote reads in P27 and P32.
6. Move the three inline research statements into the existing SQL directory.
7. Align research and production checkpoint and cohort specifications before another algorithm comparison.

A shared strict-prior purchase-state relation could reduce repeated temporal joins across P22, P01, P06, and R02.
This is a candidate architecture change, not a confirmed speedup.
The relation must retain observation timestamps, null values, player completeness, and actor identifiers.
Different consumers currently use different freshness limits.

Keep the `ASOF` operator for time-dependent matching unless an equivalent alternative measures better.
It selects the nearest qualifying state without generating every earlier state combination. [DuckDB AsOf joins](https://duckdb.org/docs/current/guides/sql_features/asof_join).
The earlier ordinary range-join experiment increased one decision query from 0.727 seconds to 33.469 seconds.

Do not remove all final `ORDER BY` clauses as a general optimization.
History consumers require deterministic event order.
Physical ordering of extracted tables can also affect later hero-filtered reads.
Measure complete extraction and subsequent analysis together before changing stored order.

Do not combine training, validation, and test aggregates merely to shorten P56.
Do not filter incomplete latest snapshots before selecting the latest timestamp.
Do not replace exact owner membership with a hero-wide cohort.

## Test SQL statements

These statements create fixtures, change deliberate edge cases, or read assertions.
Their small scans, joins, and generated rows support test behavior.
The concurrency fixture deliberately creates 300,000 rows and restricts memory to exercise disk spill and connection isolation.

The table gives a separate entry for all 95 statements.
A complex fixture does not establish that its tested product query needs the same complexity.

| ID and source | What it does | Can it be simpler? | Could it be more efficient? | Unnecessarily complex? |
| --- | --- | --- | --- | --- |
| **F01** [beam/change_reserved_outcomes.sql](../tests/offline/sql/beam/change_reserved_outcomes.sql) | Changes selection, validation, and test wins to check discovery isolation. | No. | Tiny targeted update. | No. |
| **F02** [beam/create_purchase_observations.sql](../tests/offline/sql/beam/create_purchase_observations.sql); statement 1 | Creates discovery and reserved partition cases for beam tests. | Named case data could explain numeric match identifiers. | Tiny generated set. | No; the cases test different partitions. |
| **F03** [beam/create_purchase_observations.sql](../tests/offline/sql/beam/create_purchase_observations.sql); statement 2 | Creates valid, simultaneous, repeated, missing-wealth, and same-second purchase cases. | Named cases could improve readability. | Tiny generated set. | No; each branch tests a separate rejection. |
| **F04** [beam/create_purchase_observations.sql](../tests/offline/sql/beam/create_purchase_observations.sql); statement 3 | Creates complete, future, and incomplete team observations. | Named cases could improve readability. | The two-team cross join is deliberate. | No. |
| **F05** [beam/create_purchase_observations.sql](../tests/offline/sql/beam/create_purchase_observations.sql); statement 4 | Adds older complete states before a newer incomplete state. | No. | Two inserted rows. | No; it detects incorrect fallback. |
| **F06** [beam/insert_second_purchase.sql](../tests/offline/sql/beam/insert_second_purchase.sql) | Adds another valid purchase to the same match. | No. | Copies one fixture row. | No; it checks observation multiplication. |
| **F07** [checkpoints/create_decision_opportunities.sql](../tests/offline/sql/checkpoints/create_decision_opportunities.sql) | Creates one wide decision with deliberately incorrect stored team state. | No; keep the output contract explicit. | One literal row. | No; width tests state replacement and field mapping. |
| **F08** [checkpoints/create_enemy_composition.sql](../tests/offline/sql/checkpoints/create_enemy_composition.sql) | Creates a six-hero enemy composition. | No. | One literal row. | No. |
| **F09** [checkpoints/create_hero_appearance.sql](../tests/offline/sql/checkpoints/create_hero_appearance.sql) | Creates a hero appearance for history membership. | No. | One literal row. | No. |
| **F10** [checkpoints/create_large_item_purchases.sql](../tests/offline/sql/checkpoints/create_large_item_purchases.sql) | Defines purchase columns with a BIGINT item identifier. | No. | Empty schema creation. | No; the identifier width is the test. |
| **F11** [checkpoints/create_ownership_checkpoint.sql](../tests/offline/sql/checkpoints/create_ownership_checkpoint.sql); statement 1 | Creates seven actors with duration and checkpoint edge cases. | Named cases could replace numeric case references. | Seven rows. | No; the duration difference is required. |
| **F12** [checkpoints/create_ownership_checkpoint.sql](../tests/offline/sql/checkpoints/create_ownership_checkpoint.sql); statement 2 | Assigns those seven actors to discovery. | No. | Small projection. | No. |
| **F13** [checkpoints/create_ownership_checkpoint.sql](../tests/offline/sql/checkpoints/create_ownership_checkpoint.sql); statement 3 | Adds a complete enemy composition for each actor. | No. | Small projection. | No. |
| **F14** [checkpoints/create_ownership_checkpoint.sql](../tests/offline/sql/checkpoints/create_ownership_checkpoint.sql); statement 4 | Adds prior, boundary, missing, and stale personal snapshots. | Named cases could make the unions easier to inspect. | Small fixture scans. | No; `UNION ALL` preserves separate observations. |
| **F15** [checkpoints/create_ownership_checkpoint.sql](../tests/offline/sql/checkpoints/create_ownership_checkpoint.sql); statement 5 | Adds complete, missing, stale, and incomplete team snapshots. | Named cases could improve readability. | Small deliberate team expansion. | No. |
| **F16** [checkpoints/create_ownership_checkpoint.sql](../tests/offline/sql/checkpoints/create_ownership_checkpoint.sql); statement 6 | Adds buys and sales before, at, and after checkpoint boundaries. | No; the literal event matrix is explicit. | Six events per actor. | No; the cross join creates the test matrix. |
| **F17** [checkpoints/create_purchases.sql](../tests/offline/sql/checkpoints/create_purchases.sql) | Defines the minimal purchase-history schema. | No. | Empty schema creation. | No. |
| **F18** [checkpoints/create_single_partition.sql](../tests/offline/sql/checkpoints/create_single_partition.sql) | Creates one discovery partition row. | No. | One literal row. | No. |
| **F19** [checkpoints/create_team_snapshots.sql](../tests/offline/sql/checkpoints/create_team_snapshots.sql) | Defines the team-state fixture schema. | No. | Empty schema creation. | No. |
| **F20** [checkpoints/insert_missing_sale.sql](../tests/offline/sql/checkpoints/insert_missing_sale.sql) | Inserts a large item identifier with an unknown sale time. | No. | One inserted row. | No. |
| **F21** [checkpoints/insert_purchase_history.sql](../tests/offline/sql/checkpoints/insert_purchase_history.sql) | Adds hero and enemy purchases around the observed checkpoint. | No. | Five inserted rows. | No; timing differences drive the assertions. |
| **F22** [checkpoints/insert_recent_observations.sql](../tests/offline/sql/checkpoints/insert_recent_observations.sql); statement 1 | Adds recent valid personal states beneath later invalid states. | No. | Seven fixture rows. | No. |
| **F23** [checkpoints/insert_recent_observations.sql](../tests/offline/sql/checkpoints/insert_recent_observations.sql); statement 2 | Adds recent complete team states beneath later invalid states. | No. | Small two-team cross join. | No. |
| **F24** [checkpoints/insert_recent_observations.sql](../tests/offline/sql/checkpoints/insert_recent_observations.sql); statement 3 | Changes latest personal wealth to null or zero. | No. | Targeted update. | No; both invalid-value cases matter. |
| **F25** [checkpoints/insert_recent_observations.sql](../tests/offline/sql/checkpoints/insert_recent_observations.sql); statement 4 | Makes selected latest own-team or enemy-team states incomplete. | Named case data could replace match-number conditions. | Targeted fixture update. | No; both team directions need coverage. |
| **F26** [checkpoints/insert_recent_observations.sql](../tests/offline/sql/checkpoints/insert_recent_observations.sql); statement 5 | Adds a latest null team-wealth observation with six reported players. | No. | One inserted row. | No; it tests null preservation after grouping. |
| **F27** [checkpoints/insert_team_snapshots.sql](../tests/offline/sql/checkpoints/insert_team_snapshots.sql) | Adds valid prior states and a large same-second future state. | No. | Three inserted rows. | No; values expose an incorrect time boundary. |
| **F28** [checkpoints/insert_teammate_purchase.sql](../tests/offline/sql/checkpoints/insert_teammate_purchase.sql) | Adds an unrelated friendly purchase. | No. | One inserted row. | No; it checks teammate exclusion. |
| **F29** [checkpoints/remove_enemy_observation.sql](../tests/offline/sql/checkpoints/remove_enemy_observation.sql) | Marks the enemy observation incomplete by setting its count to five. | Rename the file to describe the update accurately. | Targeted update. | No SQL excess; the current filename suggests deletion. |
| **F30** [checkpoints/remove_item_identifiers.sql](../tests/offline/sql/checkpoints/remove_item_identifiers.sql) | Removes item identifiers by setting fixture values to null. | No. | Small deliberate full-fixture update. | No; it checks invalid identifier rejection. |
| **F31** [checkpoints/set_stale_enemy_snapshot.sql](../tests/offline/sql/checkpoints/set_stale_enemy_snapshot.sql) | Moves the enemy snapshot beyond the freshness limit. | No. | Targeted update. | No. |
| **F32** [cohort/create_match_folds.sql](../tests/offline/sql/cohort/create_match_folds.sql) | Defines a match-fold fixture table. | No. | Empty schema creation. | No. |
| **F33** [cohort/create_player_matches.sql](../tests/offline/sql/cohort/create_player_matches.sql) | Defines the minimal player-cohort fixture schema. | No. | Empty schema creation. | No. |
| **F34** [cohort/insert_match_folds.sql](../tests/offline/sql/cohort/insert_match_folds.sql) | Inserts one match in each train, validation, and test fold. | No. | Three inserted rows. | No. |
| **F35** [cohort/insert_player_matches.sql](../tests/offline/sql/cohort/insert_player_matches.sql) | Adds an extreme test-period outcome beside normal selection observations. | No. | Three inserted rows. | No; the extreme value detects leakage. |
| **F36** [concurrency/count_invalid_records.sql](../tests/offline/sql/concurrency/count_invalid_records.sql) | Counts worker rows whose deterministic payload changed. | No. | The scan intentionally verifies every worker row. | No; reducing the scan weakens the assertion. |
| **F37** [concurrency/create_after_workers.sql](../tests/offline/sql/concurrency/create_after_workers.sql) | Creates a persistent table after parallel workers finish. | No. | One-row table creation. | No; it tests subsequent connection use. |
| **F38** [concurrency/create_current_hero.sql](../tests/offline/sql/concurrency/create_current_hero.sql) | Creates a connection-local current-hero value. | No. | One-row temporary table. | No; temporary scope is essential. |
| **F39** [concurrency/create_match_folds.sql](../tests/offline/sql/concurrency/create_match_folds.sql) | Creates train, validation, and test folds for concurrency checks. | No. | Four literal rows. | No. |
| **F40** [concurrency/create_player_matches.sql](../tests/offline/sql/concurrency/create_player_matches.sql) | Creates ordered match timestamps for concurrency checks. | No. | Four literal rows. | No. |
| **F41** [concurrency/create_worker_records.sql](../tests/offline/sql/concurrency/create_worker_records.sql) | Creates 300,000 deterministic wide worker rows to force resource pressure. | No; the repeated payload has a test purpose. | Intentionally expensive to exercise spill and isolation. | No; smaller data can stop testing the failure condition. |
| **F42** [concurrency/select_current_hero.sql](../tests/offline/sql/concurrency/select_current_hero.sql) | Reads the current connection's hero value. | No. | One-row lookup. | No. |
| **F43** [concurrency/set_memory_limit.sql](../tests/offline/sql/concurrency/set_memory_limit.sql) | Limits test memory to 16 MiB. | No. | The low limit deliberately forces spill. | No. |
| **F44** [ducklake/attach_writable.sql](../tests/offline/sql/ducklake/attach_writable.sql) | Attaches a writable temporary DuckLake catalog for snapshot setup. | No. | Connection setup. | No; production attachments remain read-only. |
| **F45** [ducklake/create_records.sql](../tests/offline/sql/ducklake/create_records.sql) | Creates a remote fixture record before snapshot pinning. | No. | One-row table creation. | No. |
| **F46** [ducklake/insert_record.sql](../tests/offline/sql/ducklake/insert_record.sql) | Adds a record after the original snapshot. | No. | One inserted row. | No; it distinguishes snapshot versions. |
| **F47** [ducklake/load_extension.sql](../tests/offline/sql/ducklake/load_extension.sql) | Loads DuckLake for the fixture connection. | No. | Connection setup. | No. |
| **F48** [ducklake/select_extension_installed.sql](../tests/offline/sql/ducklake/select_extension_installed.sql) | Checks whether DuckLake is installed before the test. | No. | Extension metadata lookup. | No. |
| **F49** [extract/attach_memory.sql](../tests/offline/sql/extract/attach_memory.sql) | Attaches an in-memory remote catalog for extraction tests. | No. | Connection setup. | No. |
| **F50** [extract/create_match_player.sql](../tests/offline/sql/extract/create_match_player.sql) | Defines the remote columns used by match-admission tests. | No. | Empty schema creation. | No. |
| **F51** [extract/create_source_tables.sql](../tests/offline/sql/extract/create_source_tables.sql); statement 1 | Stores fixture snapshot version seven as a BIGINT. | No. | One-row table creation. | No. |
| **F52** [extract/create_source_tables.sql](../tests/offline/sql/extract/create_source_tables.sql); statement 2 | Creates thirty complete matches with twelve players and paired item/stat arrays. | Named fixture constants could improve readability. | The 360-row cross join is intentional. | No; the arrays exercise full extraction. |
| **F53** [extract/insert_match_player.sql](../tests/offline/sql/extract/insert_match_player.sql) | Inserts one remote player through bound parameters. | Add explicit target column names if the fixture schema changes often. | Small batched inserts. | No. |
| **F54** [item_metrics/create_first_purchases.sql](../tests/offline/sql/item_metrics/create_first_purchases.sql) | Copies explicit first-purchase columns from a registered fixture frame. | No; explicit columns protect the fixture contract. | Small local copy. | No. |
| **F55** [item_metrics/create_purchases.sql](../tests/offline/sql/item_metrics/create_purchases.sql) | Copies purchase-event columns from a registered fixture frame. | No. | Small local copy. | No. |
| **F56** [missing_state/create_compositions.sql](../tests/offline/sql/missing_state/create_compositions.sql) | Creates an empty composition table. | No. | Empty schema creation. | No; missing data is intentional. |
| **F57** [missing_state/create_partitions.sql](../tests/offline/sql/missing_state/create_partitions.sql) | Assigns every missing-state actor to discovery. | No. | Small projection. | No. |
| **F58** [missing_state/create_player_matches.sql](../tests/offline/sql/missing_state/create_player_matches.sql) | Creates one hundred actors without observed states. | No. | Small generated set. | No; it checks unknown-state populations. |
| **F59** [missing_state/create_player_snapshots.sql](../tests/offline/sql/missing_state/create_player_snapshots.sql) | Creates an empty personal-snapshot table. | No. | Empty schema creation. | No; the absence is the test case. |
| **F60** [missing_state/create_team_snapshots.sql](../tests/offline/sql/missing_state/create_team_snapshots.sql) | Creates an empty team-snapshot table. | No. | Empty schema creation. | No; the absence is the test case. |
| **F61** [partitions/create_empty_player_matches.sql](../tests/offline/sql/partitions/create_empty_player_matches.sql) | Defines an empty hero table for missing-source rejection. | No. | Empty schema creation. | No. |
| **F62** [partitions/create_match_folds.sql](../tests/offline/sql/partitions/create_match_folds.sql) | Creates training, validation, and test partitions for ten matches. | No. | Ten generated rows. | No. |
| **F63** [partitions/create_player_matches.sql](../tests/offline/sql/partitions/create_player_matches.sql) | Creates two hero appearances per match for whole-match splitting. | No. | Twenty generated rows. | No. |
| **F64** [pool/create_purchases.sql](../tests/offline/sql/pool/create_purchases.sql) | Defines the item-pool purchase fixture schema. | No. | Empty schema creation. | No. |
| **F65** [pool/insert_purchase_history.sql](../tests/offline/sql/pool/insert_purchase_history.sql) | Adds repeat purchases, another hero, a nonmember, and a post-match purchase. | No; explicit values show the distinctions. | Five inserted rows. | No; each row tests a different filter. |
| **F66** [rank_expansion/create_low_rank_match.sql](../tests/offline/sql/rank_expansion/create_low_rank_match.sql) | Creates a match below the initial rank cohort. | No. | One literal row. | No. |
| **F67** [rank_expansion/create_player_matches.sql](../tests/offline/sql/rank_expansion/create_player_matches.sql) | Creates ten complete matches in the initial rank cohort. | No. | A deliberate 120-row cross join. | No. |
| **F68** [rank_expansion/insert_expanded_matches.sql](../tests/offline/sql/rank_expansion/insert_expanded_matches.sql) | Adds lower-rank copies of existing matches with distinct identifiers. | No. | Small fixture copy. | No; it checks fixed split boundaries during expansion. |
| **F69** [rank_expansion/select_match_sizes.sql](../tests/offline/sql/rank_expansion/select_match_sizes.sql) | Finds distinct player counts after partition assignment. | No. | Grouping and distinct output check complete matches. | No; neither operation is redundant for this assertion. |
| **F70** [rank_expansion/select_original_folds.sql](../tests/offline/sql/rank_expansion/select_original_folds.sql) | Reads only the original matches after rank expansion. | No. | Small filtered and ordered read. | No. |
| **F71** [search/create_duplicate_heroes.sql](../tests/offline/sql/search/create_duplicate_heroes.sql); statement 1 | Defines folds for duplicate-hero research cases. | No. | Empty schema creation. | No. |
| **F72** [search/create_duplicate_heroes.sql](../tests/offline/sql/search/create_duplicate_heroes.sql); statement 2 | Adds two training matches and one held-out match. | No. | Three inserted rows. | No. |
| **F73** [search/create_duplicate_heroes.sql](../tests/offline/sql/search/create_duplicate_heroes.sql); statement 3 | Defines hero appearances for duplicate detection. | No. | Empty schema creation. | No. |
| **F74** [search/create_duplicate_heroes.sql](../tests/offline/sql/search/create_duplicate_heroes.sql); statement 4 | Adds valid, repeated-hero, and held-out actor cases. | No. | Six inserted rows. | No. |
| **F75** [search/create_landmark_fixture.sql](../tests/offline/sql/search/create_landmark_fixture.sql); statement 1 | Defines the player schema for research checkpoint tests. | No. | Empty schema creation. | No. |
| **F76** [search/create_landmark_fixture.sql](../tests/offline/sql/search/create_landmark_fixture.sql); statement 2 | Adds one actor whose match reaches every tested checkpoint. | No. | One inserted row. | No. |
| **F77** [search/create_landmark_fixture.sql](../tests/offline/sql/search/create_landmark_fixture.sql); statement 3 | Defines research match folds. | No. | Empty schema creation. | No. |
| **F78** [search/create_landmark_fixture.sql](../tests/offline/sql/search/create_landmark_fixture.sql); statement 4 | Assigns the checkpoint actor to training. | No. | One inserted row. | No. |
| **F79** [search/create_landmark_fixture.sql](../tests/offline/sql/search/create_landmark_fixture.sql); statement 5 | Defines personal snapshots for research boundaries. | No. | Empty schema creation. | No. |
| **F80** [search/create_landmark_fixture.sql](../tests/offline/sql/search/create_landmark_fixture.sql); statement 6 | Adds snapshots before, at, and after the research checkpoints. | No. | Six inserted rows. | No; exact timestamps test inclusive behavior. |
| **F81** [search/create_landmark_fixture.sql](../tests/offline/sql/search/create_landmark_fixture.sql); statement 7 | Defines team snapshots for research boundaries. | No. | Empty schema creation. | No. |
| **F82** [search/create_landmark_fixture.sql](../tests/offline/sql/search/create_landmark_fixture.sql); statement 8 | Adds both teams at the tested observation times. | No. | Ten inserted rows. | No. |
| **F83** [search/select_experiment_matches.sql](../tests/offline/sql/search/select_experiment_matches.sql) | Reads eligible experiment match identifiers. | Add ordering if an assertion later depends on several rows. | Tiny result. | No; the current assertion returns one match. |
| **F84** [select_discovery_partitions.sql](../tests/offline/sql/select_discovery_partitions.sql) | Reads discovery partitions in match order. | No. | Small deterministic assertion read. | No. |
| **F85** [select_match_folds.sql](../tests/offline/sql/select_match_folds.sql) | Reads match folds without an order contract. | Use F86 if a caller needs ordered rows. | Tiny fixture read. | No. |
| **F86** [select_match_folds_ordered.sql](../tests/offline/sql/select_match_folds_ordered.sql) | Reads match folds in match order. | No. | Small deterministic assertion read. | No. |
| **F87** [select_one.sql](../tests/offline/sql/select_one.sql) | Returns one for connection and retry tests. | Optionally reuse F90 with a bound value. | No meaningful performance difference. | No; the separate constant file can be consolidated. |
| **F88** [select_seven.sql](../tests/offline/sql/select_seven.sql) | Returns seven for scalar-count tests. | Optionally reuse F90 with a bound value. | No meaningful performance difference. | No; the separate constant file can be consolidated. |
| **F89** [select_split_boundaries.sql](../tests/offline/sql/select_split_boundaries.sql) | Reads the three frozen split timestamps. | No. | One-row lookup. | No. |
| **F90** [select_value.sql](../tests/offline/sql/select_value.sql) | Returns a bound scalar value for parameter tests. | No. | Constant evaluation. | No. |
| **F91** [select_zero.sql](../tests/offline/sql/select_zero.sql) | Returns zero for empty-count tests. | Optionally reuse F90 with a bound value. | No meaningful performance difference. | No; the separate constant file can be consolidated. |
| **F92** [selection/change_test_observations.sql](../tests/offline/sql/selection/change_test_observations.sql) | Changes held-out imbues, wins, and wealth to detect selection leakage. | No. | Small targeted update. | No. |
| **F93** [selection/create_first_purchases.sql](../tests/offline/sql/selection/create_first_purchases.sql) | Creates fold-specific item adoption and imbue patterns. | Named cases can replace arithmetic inclusion thresholds. | The small generated set needs no optimization. | Partly; `52 - items.j` conceals the case meanings. |
| **F94** [selection/create_purchases.sql](../tests/offline/sql/selection/create_purchases.sql) | Copies the complete first-purchase fixture into a purchase table. | Possibly use `SELECT *` if copying every fixture column is intentional. | No meaningful performance difference. | No; explicit columns can also protect the fixture contract. |
| **F95** [selection/remove_test_item.sql](../tests/offline/sql/selection/remove_test_item.sql) | Deletes one held-out item to test selection independence. | No. | Small targeted delete. | No. |

## Verification and limits

| Check | Result |
| --- | --- |
| Inventory coverage | All 161 statements have exactly one audit entry. |
| Local source links | Every linked source file exists. |
| DuckDB syntax parsing | All 158 file statements and three inline statements parse. |
| Product SQL identity | Every audited SQL file retains its original audit-start SHA-256 value. |
| Temporary reproductions | Five conditions reproduced: null eligibility, extra actors, partial team wealth, history multiplication, and unrelated metadata. |
| Captured data checks | Read-only checks completed, including nine post-match beam observations. |
| Candidate comparisons | Eight comparisons matched 1,135,827 result rows and column schemas. |
| Lock, frozen environment, dependency compatibility | Passed. |
| Ruff format and lint, SQLFluff, Ty | Passed. |
| Deptry, Tach, Complexipy, Vulture, Pylint duplicate-code check | Passed. |
| Coverage with `pytest -W error` | 1,539 existing tests passed. |
| `tools/quality_gate.py` | Passed. |
| `uv build` | Source distribution and wheel built. |
| Full remote extraction benchmark | Did not run. |
| Live Steam sync | Did not run. |

The current tests pass despite the reproduced gaps.
The temporary reproductions are audit evidence, not regression tests for implemented fixes.
Each correctness fix needs a regression test before delivery.

The candidate measurements do not establish full-refresh runtime or live-build quality.
Their proposals remain outside product code.
The audit leaves the earlier uncommitted optimization changes in place.
