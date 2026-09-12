# Rust rewrite verification

Local verification date: September 11, 2026.
Target: `aarch64-apple-darwin`, Rust 1.92.0.
Python reference: `d603d6b53bb110d0ac48a689f037861e6453b243`.

## Implemented scope

The Rust workspace supplies the complete CLI, including evidence refresh, guide generation, deterministic descriptions, recommendations, replay reports, installation, and recovery.
The default executable consumes reviewed evidence.
The optional `analysis` feature adds source extraction, DuckDB, numerical estimates, current discovery, and beam generation.
No command delegates to Python.

Six product crates separate shared data, inputs, guides, Steam storage, analysis, and CLI workflows.
The quality tool enforces the approved crate dependencies and rejects cyclic module dependencies.
Compiler settings forbid unsafe repository code and deny warnings.
Clippy denies `all`, `pedantic`, and `nursery` findings and limits cognitive complexity to 21.
The parsed source check rejects async functions, blocks, closures, await expressions, and equivalent macro tokens.

The Python runtime, package manifest, lockfile, tests, and comparison runners were retired from the active workspace.
Git retains the complete reference implementation and its checks.
The existing licensed KV3 fixture remains under `tests/fixtures`.

## Initial required gates

| Check | Result |
| --- | --- |
| Rust formatting | Passed |
| Strict Clippy, all targets and features | Passed |
| Approved crate dependencies and acyclic module graphs | Passed |
| Synchronous source policy | Passed |
| SQLFluff 4.3.0 | Passed |
| Rust documentation, all features, warnings as errors | Passed |
| Cargo Deny advisories, bans, licenses, and sources | Passed |
| Default CLI build and missing-analysis-feature behavior | Passed |
| Release CLI build with analysis | Passed |
| Release archive inspection outside the checkout | Passed |
| Packaged release workflows against a local HTTP server | Passed |
| Existing Python reference gate before retirement | Passed |
| Linux execution and GitHub Actions execution | Did not run locally |
| Live Steam installation or restoration | Did not run |
| Live remote DuckLake extraction | Did not run |
| Application performance benchmark | Did not run |
| New unit tests | Not written, as requested |

The [final gate record](research/rust-packages/final-rust-gates.json) contains exact commands and exit codes.
The [structured verification record](research/rust-packages/rewrite-verification.json) contains comparison counts and release details.
The earlier `rust-gates.json` describes the initial implementation stage only.

## Artifact and numerical comparisons

Canonical JSON and SHA-256 inputs matched Python across 100,009 deterministic floating-point cases.
The checks also covered rank fingerprints, snapshots, evidence admission, item mechanics, abilities, component routes, policy reconstruction, and deterministic descriptions.
Recommendation and report comparisons checked operational results while accounting for deliberate wording changes.
The artifact loader checked complete bundle fingerprints without relaxing its validators.

The final probability adapter passed 100 standardized fixtures.
The maximum absolute probability difference was `7.78e-16`.
The cases included missing values, constant features, class imbalance, and single-class fallback.

Core mining, grouping, outcomes, and 12 complete doubly robust contrasts passed 43,527 comparisons.
The maximum numerical difference was `1.30e-11`.
All 24 discovery fixtures produced the same groups as Python.
These results do not guarantee identical partitions for every possible graph.

Balance calculations center each feature before calculating weighted class statistics.
This prevents floating-point roundoff from reporting a large standardized difference for a constant feature.
The Python comparison oracle used the same centering for that diagnostic.
The admission threshold remains unchanged.
The implementation fingerprint prevents incompatible extraction checkpoints from resuming.

A database fixture with 2,400 hero appearances produced three admitted current builds.
A second fixture produced three supported beam routes.
The Python evidence validator accepted both outputs.
Eight independent database connections also passed the worker-isolation check.
At initial verification, all 53 embedded SQL files matched the reference bytes.

CLI refresh checks covered complete resume, repeated artifact identity, mismatched timestamps, changed implementation identity, and changed source files.
Rejected resume requests preserved the previous output.
These checks exercised local database fixtures rather than the remote public database.

## CLI and Steam checks

The development CLI passed generation, bundle admission, narrative reuse, recommendations, quality reporting, status, trace output, and repeated-build preservation checks.
A separate two-hero fixture verified single-hero selection and complete subset admission.
Each CLI workflow used 44 local HTTP requests.
The packaged release passed the same complete workflow outside the checkout.

Subset selection derives a new evidence artifact and retains its parent in `source_artifact_id`.
The selected bundle must pass the full coverage validator.
The source roster fingerprint still identifies the complete pinned asset roster.

The codec checks covered binary KV3 versions 0 through 5, raw storage, LZ4, Zstandard, and legacy Valve block compression.
Seventeen additional fixtures checked legacy encodings, version 1 blobs, and version 5 flags.
Truncated inputs were rejected.
Entity-name flags survived replacement through the version 5 encoder.

Temporary Steam directories exercised managed metadata, backup bytes, recovery backups, unchanged repeats, concurrent-change rejection, and malformed protobuf rejection.
Preservation checks included favorites, saved selections, unrelated values, and entity-name flags.
Eleven process cases covered custom paths, Windows path separators, quoted executable names, unrelated processes, missing process lists, and oversized command lines.
Three identifier cases distinguished conflicting private builds from other accounts and favorites copies.
No check used a live Steam cache.

## Packaging and dependency scope

The inspected release contains the executable, README, and project license.
Its executable includes the analysis feature and embedded SQL.
The packaging check extracts the archive outside the source checkout and checks all 13 command help pages.
The release workflow builds the Linux AMD64 archive after the reusable CI gate.
The local archive targets macOS ARM64 and does not certify the Linux executable.

The locked Linux AMD64 dependency graph has 81 external package versions without analysis and 165 with analysis.
Counts include normal and build dependencies.
Neither selected graph includes a prohibited asynchronous runtime.
The [package report](rust-package-research.md) explains each dependency and the numerical comparison limits.
No VDF dependency was added.

Repository code contains no unsafe operations.
Safe dependency interfaces can use unsafe Rust or native code internally.
DuckDB remains a native C++ dependency and requires substantial build resources.

## Source size and performance

The Python product and narrative script contain 31,334 lines in 175 files.
The Rust product contains 31,523 lines in 230 files, including build scripts.
Both counts include blank lines and comments and exclude tests, SQL, documentation, and quality tools.
The production source size is approximately unchanged.

The Rust executable removes the Python application environment and conversion boundaries.
These changes do not establish a measured speed or memory improvement.
The initial verification did not measure application performance.
Fixture validation does not certify current live builds.

## Live extraction corrections

Follow-up verification date: September 12, 2026.

The first live Rust extraction failed because the bundled client had not loaded ICU before timezone-aware interval arithmetic.
Extraction now explicitly loads ICU and sets the connection timezone to UTC.
This preserves UTC values when DuckDB converts timezone-naive Rust timestamp parameters.
The change adds no Cargo dependency.
The extension startup and match eligibility queries changed.
The other 51 embedded SQL files still match the Python reference bytes.

An isolated Rust executable checked the actual extension startup SQL from a connection that initially used `America/Los_Angeles`.
It checked the resulting UTC setting and a bound timestamp.

After the timezone correction, live extraction passed against DuckLake snapshot 56.
It captured 80,728 matches, 968,736 player appearances, and 16,408,307 purchase records across 38 heroes.
The cohort cutoff is `2026-09-12T12:02:45+00:00`.
The cohort starts at `2026-08-22T21:40:46+00:00` and uses badges 71 through 115.

Discovery then rejected two source matches with repeated heroes: `104133070` and `105067902`.
Both matches had 12 distinct player slots but only 11 distinct heroes.
The Python reference has the same discovery restriction.
Extraction now requires 12 distinct heroes before it includes a match.
The discovery validator remains unchanged.

Seven isolated match fixtures checked the actual eligibility query.
Complete matches before or at the cutoff passed.
Matches after the cutoff, with repeated player slots, with repeated heroes, or with a missing hero failed admission.
The reference query admitted the repeated-hero and missing-hero fixtures.
The corrected query rejected both.
All fixture checks passed without adding repository unit tests.

The next live extraction included both corrections.
It captured 80,850 matches, 970,200 player appearances, and 16,432,797 purchase records.
It retained the same cutoff, rank range, and patch start.
Read-only inspection found no invalid match compositions, no matches after the cutoff, and no records from the two rejected matches.

The complete local gate passed after the changes.
The final match filter also passed repeated formatting, SQLFluff, and strict Clippy checks.
The release archive passed inspection outside the checkout.
The [follow-up gate record](research/rust-packages/viscous-generation-gates.json) contains the commands and results.

## Validation performance changes

Follow-up verification date: September 12, 2026.

The first complete live validation attempt took too long.
A process sample identified repeated logistic calculations, JSON copies, condition scans, and idle workers after fixed job groups completed.

The logistic adapter now calculates loss and gradient together through the existing Basin interface.
It stores feature rows in one contiguous allocation and shares each exponential calculation.
Solver tolerances, iteration limits, regularization, and admission thresholds remain unchanged.

Branch validation indexes immutable decision rows by condition.
It passes row references to contrast estimation and caches substitution legality for repeated inventories.
Contrast cache keys identify selected row positions within the borrowed hero data.
The worker queue assigns the next hero to each available thread and returns results in source order.
These changes add no dependency, asynchronous code, or unsafe repository code.

The optimized logistic adapter matched the previous Rust adapter exactly across 105 fixtures.
Four complete fits with 4,000 rows and 240 columns took approximately 0.016 seconds each, compared with 0.022 seconds previously.
The fifth large fixture used the existing single-class fallback.

The existing Python comparison passed all 43,527 checks again.
The maximum numerical difference remained `1.29641575252748e-11`.
All 24 discovery fixtures retained the same groups.

An isolated executable compared 1,617 real Viscous candidate selections against the previous Rust implementation.
All 893,940 selected rows retained their exact contents and order.
Selection took 0.528 seconds, compared with 4.933 seconds previously.
Separate worker checks passed with 1, 2, 4, 8, and 64 workers.
They checked complete coverage, result ordering, error ordering, empty inputs, and invalid worker counts.

These component timings do not establish a complete generation time.
The complete-run measurement includes source capture, extraction, discovery, validation, and evidence artifact admission.
Compilation and debugging are outside that measurement.

The first optimized complete run passed in 1,321.093 seconds, or 22 minutes 1 second.
It missed the required 20-minute limit.
The run admitted 750 build paths across all 38 heroes and wrote a validated evidence artifact.
Rust then generated three Viscous guides in 19.361 seconds.

A second process sample identified repeated feature-name parsing and JSON comparisons within the remaining statistical work.
Feature conversion now creates the column mapping once per contrast and writes observed indicator values directly.
It retains the original column order, missing values, aliases, and numeric values.
Validation now starts larger estimated workloads first, using frozen branch counts and discovery support.
The queue retains source order for results and errors.

All 205 feature fixtures matched the previous Rust matrices exactly.
Four malformed cases retained rejection behavior.
Large fixtures contained 4,000 rows and approximately 250 columns.
Their conversion time fell from approximately 118 milliseconds to 4 milliseconds.
The 43,527 numerical comparisons passed again with the same maximum difference.
Priority, coverage, result order, and error order checks passed for all five worker counts.

## Earlier live generation timing

The complete Rust refresh passed in 673.122 seconds, or 11 minutes 13 seconds.
It met the 20-minute requirement and did not meet the preferred 10-minute target.
The release executable used eight standard threads on this Mac, which has 10 logical processors and 16 GiB memory.
Rank expansion was off.
Compilation and verification commands were outside the measured refresh.

| Stage | Elapsed time |
| --- | --- |
| Source capture | 2.319 seconds |
| Extraction | 130.141 seconds |
| Discovery | 68.374 seconds |
| Hero validation | 465.752 seconds |
| Complete evidence admission | 2.367 seconds |
| Complete CLI invocation, including other work | 673.122 seconds |

The refresh captured 80,911 matches, 970,932 player appearances, and 16,445,070 purchases.
It admitted 754 build paths across all 38 heroes.
The frozen roster contained 164,966 branch candidates.
No hero was excluded.
Read-only inspection found no invalid match compositions, no matches after the cutoff, and no records from the two previously rejected matches.

The public source added 61 matches within the fixed cutoff between the two measured refreshes.
Both runs used the same rank range, patch start, cutoff, worker count, and complete validation rules.
The timing comparison therefore uses two live extractions with slightly different record counts.

The final evidence identity is `19b0d7fedadaa7218299fada41af8d95f34441d9ee1af75d617756b8fa4f1a66`.
The source directory is `generated/viscous-rust-state/deadlock-build-sync/offline/results/viscous-review-20260912-features`.
The evidence file is `generated/viscous-rust-optimized/build-evidence.json`.

Rust generated the three final Viscous guides in 10.680 seconds.
The combined refresh and Viscous generation time was 683.802 seconds, or 11 minutes 24 seconds.
The guide index is `generated/viscous-rust-optimized-build/builds.json`.
The melee guide retains path `35-d41842ad5e6e28e7` and its 11,200-soul core.

All required local gates passed for the final source.
The release archive passed inspection outside the checkout.
The [performance verification record](research/rust-packages/rust-performance-verification.json) contains exact commands, timings, comparisons, artifact identities, and release hashes.
No dependency or repository unit test was added for these performance changes.
No live Steam operation ran.

## All-hero generation and architecture checks

Follow-up verification date: September 12, 2026.

A complete refresh and all-hero generation passed in 670.943 seconds, or 11 minutes 11 seconds.
The run started with fresh extraction and an empty API response cache.
Refresh took 637.108 seconds.
Guide generation took 33.835 seconds and produced 139 guides from 755 paths across all 38 heroes.
This run did not meet the 10-minute target.

API collection now overlaps numerical validation through standard threads and one shared request schedule.
The response cache preserves exact response bytes and original fetch timestamps.
Cache identity includes the request, cohort, cutoff, client version, and epochs.
Responses expire after one hour.
Invalid cache records fail validation.

Later changes skip unnecessary missing-value calculations and use the existing ndarray dot implementation for logistic scores.
Guide projection also uses standard threads and retains source order.
The numerical comparison passed 43,527 checks with a maximum difference of `1.29641575252748e-11` from the Python reference.
All 24 discovery fixtures retained the same groups.
The vector calculation differed from the previous Rust calculation by at most `2.4108492979735274e-13` across 169 fixtures.
Solver tolerances and admission thresholds remain unchanged.
All 16 API concurrency and cache checks passed.
CLI workflow checks passed with 59 local HTTP requests.
The complete timing measurement for these later changes remains in progress.

Arch-lint 0.6.0 now enforces nine explicit restriction rules from `arch-lint.toml`.
The rules cover crate boundaries, guide network and database access, and asynchronous runtime imports.
All 237 Rust files passed, with no violations.
All 298 isolated rule checks passed.
The [Arch-lint report](research/rust-packages/arch-lint.md) records the configuration and verification scope.

The complete local gate passed for these source changes.
This includes formatting, strict Clippy, architecture checks, SQLFluff, documentation, dependency checks, default builds, and release packaging.
The release archive passed inspection and executable checks outside the checkout.
Linux execution and live Steam operations did not run locally.
No repository unit tests were added.
