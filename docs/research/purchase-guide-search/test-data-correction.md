# Test-data correction

## Detection

The first frozen test attempt stopped at the ownership-evidence validator.
It encountered duplicate hero appearances within one match.
No method summary or performance report was produced by that attempt.
The search had evaluated several earlier hero scenarios before the guard stopped the run.
Therefore, this correction occurred after initial test access.

The metadata inspection found one affected match, `104133070`, in the test partition.
Hero 11 appears once on each opposing team.
Player slots are unique, and the fold table has no duplicate match rows.
No training or validation match has duplicate hero appearances.

This record violates the experiment's assumption of one outcome per hero within a match.
The inspection did not establish whether the source match itself was invalid.
Selecting one appearance would create an arbitrary result.
Counting both as independent hero matches would misstate the sample size.

## Correction

The revised extraction excludes complete matches with duplicate hero appearances.
It applies the same general rule to every partition.
It does not hard-code the observed match ID.
The original duplicate-ownership validator remains active.

The rule excludes one test match and all 12 player appearances from that match.
The test partition therefore contains 17,995 eligible matches.
Training retains 53,987 matches; validation retains 17,996.
The final eligible total is 89,978 matches.
The source database remains unchanged.

The extraction creates a new cache with a new SQL and data fingerprint.
The regression tests verify complete-match exclusion and continued rejection of duplicate ownership records.
The training and validation caches are compared with their previous versions.
Their statistical counts, sampled queries, and reconstructed inventories must remain identical.

## Repeated evaluation disclosure

All search methods, scoring parameters, support thresholds, depths, widths, and output limits remain unchanged.
The correction uses cohort metadata, not a performance comparison.
The original [freeze](frozen-specification.json) remains available for review.
The [corrected freeze](frozen-specification-corrected.json) records the changed extraction code and data fingerprint.
The final report uses only the completed corrected test evaluation.

The first attempt is a failed test-data validation run.
It is not an additional successful test comparison.
The final report must disclose both the failed attempt and the corrected rerun.
