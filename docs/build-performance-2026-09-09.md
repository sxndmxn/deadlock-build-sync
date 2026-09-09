# Build performance verification

The target is a complete roster in 20 minutes.
The measured sequence completes in 17.39 minutes on this Mac.
Fresh discovery, validation, and evidence creation take 12.28 minutes.
Generation and temporary Steam installation add 5.11 minutes.
The timing uses saved raw inputs, recorded API responses, and the normal request interval.
It excludes live input downloads, HTTP response latency, and Steam Cloud synchronization.
The previous complete sequence took 29.04 minutes.
The measurements use an Apple M4 with 10 CPU cores and 16 GiB of RAM.
The computer runs macOS 15.5 and Python 3.13.15.
It has no Deadlock installation.

## Fixed inputs

The source run is `20260909T001949Z`.
Its read-only DuckDB file contains 1,079,748 appearances and 18,295,887 purchases from 89,979 matches.
The cohort uses ranks 71 through 115 with rank expansion disabled.
The cutoff is `2026-09-09T00:19:49Z`.
The client version is 6686.

The frozen family contains 38 heroes, 800 core candidates, and 187,708 branch candidates.
The full validation calculates 90,602 distinct contrasts.
Each eligible contrast uses the original temporal folds and five match-group folds.

The candidate fingerprint is:

```text
d5d6fe6ca7b52f2c1209594177fd34dad62ce05cb33af68cb60409018f721c48
```

The baseline roster result fingerprint is:

```text
d748fecf211c1be26a41d8cb97ab3a9a5dfe8ca06b96a892251277121600cbf6
```

## Changes

- Stop optional branch calculations at the first failed balance check.
- Retain full diagnostics for comparisons that pass balance.
- Use one Polars thread in each worker unless the user supplies an override.
- Distribute frozen candidate groups between workers.
- Restore the original hero and candidate order after validation.
- Index decision rows by item and comparison rows by condition.
- Reuse comparison tables and purchase legality checks.
- Reuse player inventories between observation times.
- Cache item ancestors within each item graph.
- Construct numeric feature arrays once per contrast.
- Use batch calculations for balance diagnostics.
- Remove repeated estimator setup around the original scaling, loss, and L-BFGS-B calculations.
- Request hero analytics concurrently through one shared request schedule.
- Restore the original evidence record order after concurrent requests.
- Reuse the snapshot fingerprint within each item and ability claim set.

The numerical path retains the original model, regularization, tolerances, iteration limits, imputation, and scaling.
It retains all candidates, support requirements, correction factors, and admission gates.
Unsuccessful native solver runs use the original estimator and its warnings.
The solver and scaling code use internal interfaces from the locked SciPy and scikit-learn versions.
Dependency updates must pass the exact numerical comparison tests.

## Validation operations

Branch validation calculates statistical evidence for optional purchases and item substitutions.
It compares choices at the same purchase checkpoint and observed game condition.
It reconstructs inventory before the purchase and checks both legal paths.
It retains the first qualifying observation for each player and match.
It requires at least 20 observations for each item in each selection period before model fitting.

The selection periods are the discovery period and the validation period.
Each period has five groups of complete matches.
Each group receives predictions from models that use only the other four groups.
Each group requires three logistic models when its period passes balance:

- The probability of the observed item choice from the observed state.
- The probability of winning after the candidate item from the observed state.
- The probability of winning after the comparison item from the observed state.

This gives 30 model fits per supported comparison when both periods pass balance.
Rejection in the first period requires only five item-choice models.
State features include rank, purchase time, wealth, prior purchases, inventory, enemy heroes, and enemy items.
Missing values use training medians.
The model uses the original scaling, regularization, solver, and convergence limits.

The estimator combines outcome predictions with observed outcomes and item-choice probabilities.
It calculates uncertainty from match groups.
These observational estimates do not establish causation.
Each selection period must pass these checks:

| Check | Requirement |
| --- | --- |
| Observed support | At least 20 observations for each item |
| Weighted effective support | At least 20 observations |
| Probability overlap | At least half the predictions fall between 0.1 and 0.9 |
| State balance | Maximum standardized mean difference at most 0.10 |
| Uncertainty | Interval width at most 0.10 |
| Outcome advantage | Lower confidence bound above zero |
| Temporal stability | Period estimates differ by at most 0.05 |

The branch evaluator also corrects confidence bounds for the complete frozen hypothesis family.
The corrected lower bound must exceed zero.
The corrected interval width must not exceed 0.10.
Accepted comparisons retain all diagnostics, including clipped-weight sensitivity estimates.
Early rejections retain the failed period, item counts, and calculated balance value.
The rejection reason states that later outcome diagnostics were not calculated.
The evidence method records this diagnostic policy.

The complete baseline audit contains 180,276 optional purchase and substitution records.
Insufficient temporal support rejects 88,049 records before fitting.
The remaining 92,227 records contain calculated statistics, including reused results.
Every calculated record fails the balance gate.
No automatic branch passes admission across the 800 builds.
The core evidence classifies 795 builds as `observed` and five as `outcome_supported`.

These calculations belong to `refresh-evidence`.
Normal `sync` already reuses compatible evidence and does not repeat offline model fitting.

## Data structure changes

The follow-up changes start with observation storage and selection.

| Data | Structure | Purpose |
| --- | --- | --- |
| Numeric observations | Aligned NumPy column arrays | Select temporal periods without rebuilding data frames |
| Context indicators | Shared packed bit arrays | Store observed memberships once for each choice cohort |
| Comparison selections | Integer row indices | Preserve observation order and first-occurrence selection |
| Purchase histories | Ordered integer arrays | Reconstruct one match without retaining all Python event tuples |
| Repeated inventories | Shared immutable tuples | Reuse equal inventories within a choice cohort |

Each model receives the original dense float64 feature values and column order.
The feature table retains only context columns present in the selected observations.
It retains existing custom context columns and the original missing-value behavior.
Inconsistent observation columns use the original per-selection construction.
The comparison cache retains its complete frame fingerprint and bounded capacity.

Purchase searches use keys with the same integer type as the match array.
This prevents full-array type conversion and precision loss for unsigned match identifiers.
Missing item identifiers and purchase times remain invalid.
Missing sale times retain the original zero value.

The Lash sample contains 1,210 comparisons.
Shared feature storage alone reduced its measured duration from 79.98 to 70.58 seconds.
The purchase array changes with sparse feature storage took 73.02 seconds and retained identical result bytes.
Peak process RSS decreased from 3.35 to 3.04 GiB.
These sample durations include instrumentation and do not establish full-roster performance.

A later comparison tested packed bits against sparse CSR indices on 20 recorded Kelvin comparison tables.
Both structures produced identical feature bytes for all 400 row selections.
Packed indicators used 293,846 bytes; sparse indicators used 2,767,889 bytes.
Packed selection took 0.134 seconds; sparse selection took 0.208 seconds.
This comparison measures indicator storage and row selection, not the complete build pipeline.
The final implementation retains packed bits.
The sample difference projects to about 17 CPU seconds across the complete comparison count.
Bit packing alone therefore saves only a few elapsed seconds with eight workers.

## Larger validation change

The producer now checks each period's balance before fitting that period's outcome models.
A failed balance gate already prevents branch admission.
It can therefore omit later calculations without changing the admission decision.
Omitted diagnostics change evidence files and their fingerprints.
Build items, ability orders, and instruction text must remain identical.

The experiment used 203 recorded Kelvin comparisons distributed across the complete hero input sequence.
All 203 comparisons failed balance in the first selection period.
The balance values and rejection decisions matched the complete estimator exactly.

| Operation | Wall time | CPU time | Model fits |
| --- | ---: | ---: | ---: |
| Complete statistical calculation | 9.72 seconds | 8.86 seconds | 6,090 |
| Balance check before outcome fitting | 2.26 seconds | 2.03 seconds | 1,015 |

Comparison time decreased by 77% in this sample.
This result does not establish full-roster performance.
Later gates still require the complete calculation when balance passes.
The complete estimator remains available for calculations that require every diagnostic.
Passing comparisons reuse their item-choice models, so screening does not add model fits.

A second experiment bounds binary-feature balance from observed counts and the existing propensity weight limits.
It proves that 112 of the 203 comparisons cannot pass balance, before fitting any model.
This experiment also remains outside the product code.
Its mathematical bound and complete build-content preservation require further verification before use.

## Initial measurements

| Run | Workers | Wall time | Peak process tree RSS |
| --- | ---: | ---: | ---: |
| Original validation, default Polars threads | 4 | 111.17 minutes | 9.79 GiB |
| Original validation, one Polars thread | 4 | 98.72 minutes | 9.41 GiB |
| Intermediate optimized validation | 8 | 42.80 minutes | 10.32 GiB |
| Fresh candidate discovery | 8 | 4.26 minutes | 10.40 GiB |

Both original runs and the intermediate run produced identical roster result bytes.
The intermediate run overlapped diagnostic work.
It is an exploratory measurement, not a final timing result.
Fresh discovery produced the same complete candidate fingerprint.
It used the saved raw inputs and current source validation.
It did not reuse an old discovery checkpoint.

The original Kelvin CPU profile took 260 seconds.
A later profile took 71 seconds and produced the same result fingerprint.
Profiling adds overhead, so these durations do not measure ordinary build time.

## Producer measurements before early rejection

| Stage | Wall time |
| --- | ---: |
| Fresh discovery workers | 3.02 minutes |
| Complete validation workers | 17.17 minutes |
| Source checks, checkpoint storage, and evidence creation | 0.28 minutes |
| Combined producer stages from saved raw inputs | 20.46 minutes |

The final producer uses eight workers.
Its validation run reached a peak process tree RSS of 10.22 GiB.
System swap use did not increase during this run.
Validation worker CPU time is 7,685.91 seconds.

Comparable validation time decreased from 111.17 to 17.17 minutes.
This is a 6.5-fold improvement on the same computer.
The worker count also increased from four to eight.
The data structure changes reduced validation from 20.53 to 17.17 minutes with the same eight workers.

All 38 hero result files match the original baseline bytes.
The final producer created all 800 builds and the same complete candidate fingerprint.
Fresh discovery created a new checkpoint from the saved raw inputs.
The final validation run resumed from that new checkpoint.
The combined producer duration adds these two measured stages.
It retained the normal source checks before and after validation.
Short diagnostic probes and the local quality gate overlapped part of validation.

The original exporter assembled a reference evidence file from the 38 saved baseline hero results.
The reference file and the optimized evidence files before early rejection have this SHA-256 value:

```text
8a3ff8db6fccbc29df4f882bfc1d47a88f3a65efd7b47a5bd228dc4c9617d817
```

## Generation and installation measurements before early rejection

| Stage | Seconds |
| --- | ---: |
| Evidence loading and freshness checks | 5.06 |
| Guide generation with the request schedule | 288.74 |
| Description generation and artifact writing | 13.57 |
| Temporary Steam installation | 0.08 |
| Repeated installation | 0.10 |
| Complete runtime measurement | 307.94 |

The run generated 800 descriptions and 142 grouped guides for all 38 heroes.
It skipped no heroes.
All 291 artifact files match the original baseline bytes.
The installed Steam cache also matches the original baseline bytes.
The comparison uses the same direct generation and installation path in both checkouts.

The first installation created 142 builds, updated none, and removed none.
The repeated installation created none, updated 142, and removed none.
Repeated installation produced identical cache bytes.
Both backup checks passed.
Favorites, saved builds, selected builds, unrelated private builds, and unknown fields retained their original values.

The installed cache has this SHA-256 value:

```text
17116222991ccc3a291805fc4865aac22692595b408ef60c10005ee79791f0c5
```

Runtime CPU time decreased from 133.00 to 85.97 seconds.
Peak runtime RSS is 2.79 GiB.
The original recorded-response run took 133.37 seconds without a request schedule or network delay.
The final run retains the API request schedule.
These replay durations do not measure a live HTTP speed improvement.

Snapshot fingerprint reuse reduced the scheduled runtime from 415.43 to 342.54 seconds with an interval of 0.35 seconds.
The final interval of 0.31 seconds reduced the runtime to 307.94 seconds.

## Producer measurements with early rejection

The final run completed fresh discovery and validation in one process sequence.
It used the saved raw inputs and eight worker processes.
It did not reuse a discovery checkpoint or previous validation results.

| Stage | Wall time |
| --- | ---: |
| Fresh discovery | 181.64 seconds |
| Complete validation | 544.93 seconds |
| Source checks and evidence creation | 10.39 seconds |
| Complete producer | 736.96 seconds |

The complete producer took 12.28 minutes.
Validation decreased from 17.17 to 9.08 minutes after early rejection was added.
Peak process tree RSS was 10.48 GiB.
System swap use did not increase.
Worker CPU time was 5,298.35 seconds.
The final quality gate overlapped a short part of this run.

The producer retained all 38 heroes and 800 builds.
It retained the complete candidate fingerprint and every branch admission decision.
The comparison checked all 180,276 audit records against the original baseline.
It found 92,219 balance rejections in the first period and eight in the second period.
All calculated rejection balance values and item counts matched the original diagnostics.
Hero results outside the rejected diagnostics retained identical bytes.

Branch estimation now requires about 453,000 probability calculations instead of 2.72 million.
Comparisons that pass balance retain the complete statistical calculation.
Passing comparisons do not require extra probability calculations.

The evidence file decreased from 584,829,402 to 322,489,455 bytes.
Its new SHA-256 value is:

```text
b46350908b62fabff0d5f9091cd900f3e981d2fab54001723551b2d620178ff9
```

## Generation and installation with early rejection

| Stage | Seconds |
| --- | ---: |
| Evidence loading and freshness checks | 3.07 |
| Guide generation with the request schedule | 289.05 |
| Description generation and artifact writing | 13.82 |
| Temporary Steam installation | 0.08 |
| Repeated installation | 0.10 |
| Complete runtime measurement | 306.42 |

The complete sequence took 1,043.38 seconds, or 17.39 minutes.
It generated 800 descriptions and 142 grouped guides for all 38 heroes.
It skipped no heroes.
It made 855 API calls through the original request interval of 0.31 seconds.
Peak runtime RSS was 2.53 GiB.

The content comparison passed against the original baseline.
All 800 descriptions and ability plans retained identical content.
All 142 grouped purchase guides and 284 guide Markdown files retained identical content.
The guide index and complete purchase records matched after replacing only known snapshot and policy fingerprints.
The Steam cache comparison found only changed snapshot and policy fingerprints.
Its new SHA-256 value is:

```text
38679c245133952498df3e1fe5a4a76e5f35fdf16faff5cff082bb132a569a38
```

The first temporary installation created 142 builds, updated none, and removed none.
Repeated installation created none, updated 142, and removed none.
Repeated installation retained identical cache bytes.
Backups and preservation of unrelated user data passed both checks.
These operations used an isolated temporary cache, without a live Steam installation.

The retained measurement directory is `/tmp/deadlock-build-optimization-YZbIWD`.
Its final installation files are:

- Artifacts: `runtime-screened/artifacts`.
- Cache: `runtime-screened/steam/userdata/146293212/1422450/remote/cfg/cached_hero_builds.kv3`.
- Backup: `runtime-screened/state/deadlock-build-sync/backups/146293212/20260909T233701Z`.
- Complete sequence measurements: `screened-pipeline-metrics.json`.
- Runtime measurements: `runtime-screened/metrics.json`.
- Build content comparison: `screened-build-comparison.json`.
- Original byte comparison: `runtime-byte-comparison.json`.
- Final producer measurements: `full-producer-screened/production-metrics.json`.
- Complete evidence comparison: `screened-evidence-comparison.json`.
- Earlier validation measurements: `full-producer-packed/production-metrics.json`.
- Earlier runtime measurements: `runtime-interval-031/metrics.json`.
- Admission audit: `validation-admission-audit.json`.
- Experimental rejection timing: `staged-validation-measurement.json`.
- Quality checks: `quality-gates-screened/results.json`.
- Wheel checks: `wheel-smoke/results-screened.json`.

The complete fast local gate passed with 1,364 tests after early rejection was added.
The wheel contains 165 Python files that match the source checkout and all four schemas.
Its external installation, imports, CLI checks, and exact probability comparison passed.
The slow mutation gate did not run because these changes do not modify the Steam data boundary.

## Measurement limits

The measured sequence meets the 20-minute budget with saved inputs.
Live input capture, HTTP response latency, and Steam Cloud synchronization remain unmeasured.
These results do not establish a live 20-minute limit.
The early-rejection change permits omitted diagnostics for rejected comparisons and retains all branch admission requirements.

A 15-minute producer would need about 11.5 occupied CPU cores at the measured worker CPU cost.
This is a capacity estimate, not a verified Linux duration.
CPU speed, memory bandwidth, source extraction, and server response times can change the result.
A complete timing run on the target Linux computer remains necessary.

The Lash stage profile measured 1,210 contrasts in 79.98 seconds.
Model fitting used 41.48 CPU seconds within 59.07 CPU seconds of contrast estimation.
Data and inventory loading used 13.83 CPU seconds.
These stage measurements use nested timers and must not be added together.

A further fixed loss and scaling prototype reduced the Kelvin contrast test from 21.26 to 20.15 seconds.
All 1,013 contrast results matched.
The retained path uses the library loss and scaling calculations.
The extra 5.2% improvement did not justify another copy of those calculations.

## Verification

The complete fast local gate in [Quality gates](quality-gates.md) passed.
This includes lock validation, environment synchronization, formatting, linting, types, dependencies, architecture, complexity, coverage, dead code, duplicate code, package checks, and packaging.
All 1,332 tests passed with warnings treated as errors.
Statement coverage is 97.19%; branch coverage is 91.98%.
The wheel contains all 161 product Python files with the same source bytes.
Module imports, exact probability comparisons, CLI help, narrative command help, and dependency checks passed outside the source checkout.
The final verification record includes the full roster comparison and temporary Steam installation checks.
The slower mutation gate and live Steam sync did not run.

## Scope

`refresh-evidence` includes source extraction, candidate discovery, validation, and evidence artifact creation.
`sync` uses current evidence to create descriptions and guides before installation.
These operations have separate timing requirements.

The local producer measurements use saved raw inputs.
They exclude a new remote cohort download.
The generation comparison uses exact recorded API response bytes.
Recorded response replay excludes network latency.
The current API request schedule remains active unless the measurement states otherwise.
All output comparisons use the same source bytes, artifact path, and timestamps.

The [API specification](https://api.deadlock-api.com/openapi.json) declares a shared analytics limit of 200 requests per minute per IP address.
The final client uses an interval of 0.31 seconds, approximately 194 requests per minute.

The captured generation set contains 853 unique requests.
A paced retry retrieved all 471 missing responses in 168.84 seconds without request failures.
The other 382 responses came from the first capture attempt.
These two attempts do not constitute one clean full network benchmark.

Temporary Steam files support backup, preservation, serialization, validation, replacement, and repeat-installation checks.
The test simulates a stopped Deadlock process because macOS has no Linux `/proc` directory.
The simulation applies only to the temporary installation test.
These checks do not certify installation in a running Linux Steam environment.
