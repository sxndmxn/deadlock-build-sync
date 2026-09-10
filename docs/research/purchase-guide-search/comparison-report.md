# Purchase-guide algorithm comparison

## Result

State-aware beam search is the best foundation for the next implementation.
Diverse beam at width 16 provides a useful coverage and runtime compromise.
Ordinary beam at width 16 is simpler and slightly faster.
Width 32 increases coverage at additional cost.
ECLAT and Leiden do not establish a clear overall advantage under the final common settings.

The current outcome model is not sufficient to certify stronger builds.
The Infernus example shows this failure directly.
Its default core has a 43.33% test win rate, compared with a 47.26% overall hero win rate.
Its 60-owner sample also has a wide interval.
The search and display prototypes must remain experimental.

## Scope and data

The work uses branch `experiment/purchase-guide-search`, based on merged PR #26.
The experiment adds isolated tools, regression tests, and research artifacts.
It does not change production guide selection or Steam writes.
No commit or live Steam sync was performed.

The saved source contains 89,979 matches, 1,079,748 player appearances, and 18,295,887 purchases across 38 heroes.
The final cohort excludes one test match with duplicate hero appearances.
It retains 89,978 matches: 53,987 training, 17,996 validation, and 17,995 test matches.
The [correction record](test-data-correction.md) discloses the failed first test attempt and corrected rerun.

The study uses the saved 2026-08-22 patch context and client-6686 item catalog.
Per-match client versions are unavailable.
This study does not establish performance across patches or current live-client compatibility.

The main sensitivity studies test 53 configurations before the final comparison.
They cover beam width, search depth, smoothing, cost weighting, state information, combination support, itemset size, graph resolution, and seed.
The final comparison uses nine method-width combinations with one common scorer and common constraints.
Beam width limits internal search states, not displayed builds.
The final output contains up to three distinct alternatives.
This benchmark limit does not require a three-variant limit in the product.
The [protocol](experiment-protocol.md) and [selection record](selection-rationale.md) preserve the decisions.

## Complete-core coverage

Each method receives 342 fixed scenarios: 38 heroes, three relative-wealth states, and three budget checkpoints.
Budgets are 4,800, 12,800, and 25,600 souls.
Ownership checkpoints are 600, 1,201, and 1,801 seconds.
Later checkpoints mean just after 20 and 30 minutes.

A returned core contains at least three final items and has at least 200 training owners in the matched checkpoint state.
Support percentages below use all 342 scenarios, including abstentions.

| Method | Core returned | Test owners ≥30 | Test owners ≥100 | Median search | P95 search |
| --- | ---: | ---: | ---: | ---: | ---: |
| Greedy | 47.95% | 45.61% | 28.36% | 0.44 ms | 0.80 ms |
| Beam 4 | 78.95% | 75.73% | 44.74% | 1.43 ms | 2.83 ms |
| Beam 8 | 87.72% | 85.09% | 47.37% | 2.74 ms | 5.43 ms |
| Beam 16 | 93.86% | 90.64% | 51.46% | 5.10 ms | 10.39 ms |
| Beam 32 | 96.49% | 93.27% | 52.92% | 9.03 ms | 19.85 ms |
| Diverse beam 16 | 95.32% | 92.11% | 50.88% | 6.41 ms | 13.49 ms |
| ECLAT + beam 8 | 89.77% | 86.26% | 52.05% | 3.06 ms | 5.94 ms |
| ECLAT + beam 16 | 93.57% | 90.64% | 51.46% | 5.99 ms | 12.52 ms |
| Leiden + beam 16 | 95.32% | 92.40% | 50.58% | 5.70 ms | 11.38 ms |

Every emitted action passed the checked cost, component, inventory, and active-item rules.
This validity depends on the explicit income, cash, and flex-capacity assumptions.
It does not certify actual cash availability, ability imbues, or a complete late-game guide.

Diverse beam returns 326 of 342 cores, compared with 164 for greedy.
Its top core has at least 30 test owners in 315 scenarios.
Only 174 scenarios have at least 100 test owners for that top core.
Its mean final inventory contains 3.73 items and uses 61.52% of the budget ceiling.
The experiment returns supported partial cores instead of forcing unsupported purchases.

## Purchase prediction

The decision comparison uses 3,648 sampled purchases from 3,317 distinct test matches.
Every hero contributes 96 decisions.
The split keeps each match intact.

| Method | Next-action agreement | Alternative agreement | Two-action agreement | Median search |
| --- | ---: | ---: | ---: | ---: |
| Greedy | 9.43% | 9.43% | 0.78% | 0.18 ms |
| Beam 4 | 9.90% | 18.75% | 1.34% | 0.56 ms |
| Beam 8 | 10.22% | 19.63% | 1.50% | 1.01 ms |
| Beam 16 | 10.28% | 20.12% | 1.56% | 1.76 ms |
| Beam 32 | 10.22% | 20.12% | 1.56% | 2.52 ms |
| Diverse beam 16 | 10.31% | 20.12% | 1.56% | 2.05 ms |
| ECLAT + beam 8 | 10.31% | 19.85% | 1.59% | 1.16 ms |
| ECLAT + beam 16 | 10.28% | 19.90% | 1.56% | 2.03 ms |
| Leiden + beam 16 | 10.31% | 20.09% | 1.56% | 1.90 ms |

Alternative agreement tests whether any returned path starts with the observed purchase.
The output limit is three paths, but greedy normally provides one.
Therefore, the alternative-agreement gain over greedy partly reflects a larger useful choice set.

Only 87.17% of sampled inventories fit the assumed capacity without known flex unlocks.
Only 68.04% of observed actions satisfy every experimental action and support constraint.
These exclusions limit the agreement ceiling.
They do not establish that the recorded purchases were illegal in the game.

Beam 16 improves next-action agreement over greedy by 0.85 percentage points.
The paired match-bootstrap interval is 0.36 to 1.34 percentage points.
Diverse beam adds one correct next-action prediction over beam 16.
That difference does not establish a useful prediction advantage.

Agreement measures behavior prediction.
It does not establish a winning purchase policy.
The source has no randomized action assignment or known behavior propensities.
The assumptions in [unbiased replay evaluation](https://arxiv.org/abs/1003.5956) and [doubly robust evaluation](https://icml.cc/2011/papers/554_icmlpaper.pdf) therefore require more evidence than these records provide.

## Statistical support and outcomes

Among 315 supported diverse-beam scenarios, 202 have a raw rate above the matched checkpoint-state baseline.
Only 184 exceed the whole-hero test baseline.
Only 101 combine at least 100 test owners with a raw rate above the whole-hero baseline.
These are descriptive counts, not admission decisions or significance tests.
They do not implement the earlier proposed win-rate rule.

The median raw difference from the matched state baseline is approximately 1.48 percentage points.
The median 95% interval width for the core rate is approximately 17.16 percentage points.
Thus, most apparent advantages are small relative to their uncertainty.
Owner groups overlap, so counts and wins cannot be summed across displayed variants.

The shared Bayesian item model has test Brier score 0.242569.
The state-only baseline scores 0.242635; the whole-hero baseline scores 0.249444.
Most predictive information comes from the wealth state.
The item-specific improvement is small.
These purchase-weighted calibration results do not estimate the value of the selected purchase policy.

The scorer adds item associations across purchase steps.
It does not estimate the joint effect of the complete inventory.
It can reward a component and its upgrade without modeling their separate durations.
Inventory constraints and co-occurrence support do not remove this limitation.

## Paired comparisons

The analysis uses 2,000 resamples with seed 23.
Decision intervals resample complete matches.
Guide intervals resample heroes and retain all nine scenarios for each sampled hero.
Guide intervals describe variation across the fixed hero grid.
They are not confidence intervals for a causal win-rate effect.

| Comparison | Metric | Difference | 95% interval |
| --- | --- | ---: | --- |
| beam:16 minus greedy:1 | Core support ≥30 | +45.03 pp | +38.30 to +51.75 pp |
| diverse:16 minus beam:16 | Core support ≥30 | +1.46 pp | +0.29 to +3.22 pp |
| leiden:16 minus beam:16 | Core support ≥30 | +1.75 pp | +0.29 to +3.22 pp |
| eclat:16 minus beam:16 | Core support ≥30 | +0.00 pp | -1.75 to +1.75 pp |
| eclat:8 minus beam:8 | Core support ≥100 | +4.68 pp | +0.29 to +9.36 pp |
| beam:16 minus greedy:1 | Next-action agreement | +0.85 pp | +0.36 to +1.34 pp |

These are unadjusted descriptive intervals for several planned comparisons.
Do not treat a marginal interval as proof of an algorithm winner.
ECLAT at width eight improves the stronger support measure, but its overall coverage remains below the width-16 alternatives.
Leiden improves six supported scenarios over ordinary beam 16, but adds graph choices without a useful next-action advantage.

## Efficiency

The runtime machine is an Apple M4 with ten CPU cores and 16 GiB memory.
Timings describe this machine and the saved cache.
Search timing excludes data extraction and structure preparation.
The saved summaries also report complete evaluation time, including evidence checks.

For all 342 guide scenarios, diverse beam requires 2.40 seconds of search and 3.09 seconds of evaluation.
For all 3,648 decision queries, it requires 9.05 seconds of search and 9.95 seconds of evaluation.
Structure preparation takes approximately 0.30 seconds for all heroes.
Preparing one match partition takes approximately 29 to 47 seconds.
Reusable data artifacts therefore matter more than small graph-preparation differences.

The candidate-support cache preserves all 35,910 final validation records apart from timing and attempted-action counts.
The [optimization record](results/optimization-verification.json) contains the measured before-and-after times.
It removes unsupported candidates across reachable wealth bins before expensive transition work.
It does not remove any supported valid purchase.

## Recommended next implementation

Use the common state-aware transition and exact complete-combination support checks.
Use beam width 16 as the search foundation.
Retain diverse frontier selection when additional supported variants justify its small runtime cost.
Keep greedy as a regression baseline and a possible low-cost fallback.
Do not add ECLAT or Leiden as mandatory dependencies of guide selection without a further measured benefit.

Improve the outcome model before presenting the generated paths as stronger builds.
Estimate complete-core outcomes with uncertainty and explicit state, purchase time, and match-duration context.
Test a value function for complete inventories and marginal inventory changes.
This could reduce repeated rewards for a component and its upgrade.
Preserve an untouched future evaluation cohort for that model change.
Report missing cash, flex capacity, ability targets, and unsupported continuation steps.
Connect early, middle, and later guide stages through valid inventory transitions.
Do not concatenate independently generated budget scenarios into one purchase queue.
Do not convert a high heuristic score into a superiority claim.

Use the [display design](display-design.md) to preserve complete branch relationships.
Use the [Infernus example](infernus-display-example.md) to see the resulting Markdown with actual test counts.
Keep one default queue, separate branch statistics, and bounded optional tier rows.
The current compact renderer merges optional variant items into a shared pool.
A future display change must preserve complete branch recipes and their separate statistics.
Only an identical ordered prefix can safely share the queued purchase sequence.

## Verification and artifacts

The complete fast local gate passed after the cohort correction.
All 1,459 tests passed, including 38 purchase-search regression cases.
Statement coverage is 97.24%; branch coverage is 92.08%.
The research package is outside the production wheel.
The [verification record](verification.md) lists every check and the remaining limits.

The [per-hero tables](per-hero-results.md) show coverage and action agreement for all 38 heroes.
The [results directory](results/) contains aggregate summaries, paired analyses, sensitivity measurements, and correction checks.
Raw match records and large experiment caches remain in the ignored generated directory.
The [reproduction guide](reproducibility.md) lists their paths and commands.
