# Configuration selection before test evaluation

The final comparison uses the settings recorded in `final-settings.json`.
All choices below use validation results only.

## Common scorer and constraints

Prior strength 1,000 produced the lowest Brier score among the tested smoothing settings.
Its validation Brier score was 0.242484, compared with 0.242609 for prior strength 100.
The state-only baseline scored 0.242547.
Thus, item-specific estimates add little predictive information beyond the wealth state.

Minimum complete-combination support 200 increased the number of guides with useful held-out support.
This experimental support constraint applies to every method.
It does not introduce a production win-rate eligibility rule.

Depth six retains most useful results while reducing guide search time.
Depth twelve increased search work without improving validation coverage.
Cost exponent 0.5 retains the original incremental-cost adjustment.
The cost-zero alternative produced a small action-agreement difference without a consistent guide-support advantage.

The output contains up to three distinct alternatives.
Strict subset cores and prefix extensions do not count as separate alternatives.
The scorer remains an observational heuristic.
Its numeric value is not a build win rate.

## Primary candidate

Diverse beam at width 16 is the primary candidate for the final comparison.
In validation, it returned guides for 95.32% of scenarios.
Its top guide had at least 30 validation owners in 94.44% of scenarios.
Constrained beam at width 32 improved these figures to 96.49% and 95.61%, with greater runtime.
Constrained beam at width 16 returned guides for 93.86% of scenarios.

These differences are small enough to require a paired comparison.
The reserved test results may reject a claimed advantage.
Do not change the settings after that evaluation.
Report a runtime and coverage tradeoff if the evidence does not establish a clear winner.

ECLAT and Leiden retain their original proposal settings.
Their structural changes did not establish a consistent validation advantage after stronger smoothing and support constraints.
They remain required comparison methods.

## Runtime correction

Profiling identified repeated evaluation of unsupported item-state cells.
The final implementation caches item indices with support in at least one reachable net-worth bin.
The upper bound includes the maximum additional income permitted by the remaining budget and current cash.
Every retained action still passes the same transition and exact support checks.

This filter changes the amount of search work, not the scoring function.
Regression tests cover entry into a later wealth bin and exclusion of unreachable wealth bins.
The final validation rerun compares every output record with the version before this optimization.
Search time and attempted-action counts are the only expected differences.
Each method starts with an empty candidate cache for its timing comparison.

## Test boundary

The freeze records code hashes, SQL hashes, the training-statistics hash, the structure-proposal hash, and the allowed benchmark settings.
The data fingerprint includes the source manifest, patch context, sample settings, and extraction SQL.
Test extraction and evaluation reject a missing or incompatible freeze.
Test evaluation also rejects unlisted parameter settings.

The final guide test uses 342 fixed scenarios.
The final decision test uses up to 96 sampled decisions per hero.
Keep all records from a match in the existing chronological partition.
The final test evaluates all nine method-width combinations with identical settings.
