# Repository audit: September 12, 2026

## Result and scope

The custom quality crate is removed.
One high-priority recovery finding remains.
The main measured performance opportunity is a narrower SQL decision projection.

The audit started from remote `master` at `d650e45985e0d8bf88ab6280bb748244aebfbac4`.
Implementation branch: `refactor/direct-quality-checks`.
The existing rewrite branch and two untracked user documents remain intact.

The review covers crate boundaries, Steam recovery, artifact handling, HTTP caching, numerical production, SQL, CI, packaging, and documentation.
Runtime checks used temporary Steam fixtures and the recorded `all-guides-20260912-layout` database.
No live extraction, API benchmark, or Steam operation ran.
The audit does not certify current live builds.

Priorities use these criteria:

- **HIGH PRIO:** A confirmed defect affects Steam data integrity or recovery.
- **MED PRIO:** A concrete change can reduce significant work, resource use, release omissions, or operational confusion.
- **LOW PRIO:** Maintenance improvements or performance candidates need further measurement.

The quality-tool replacement and all six MED findings are implemented.
HIGH and LOW findings remain open.
The findings below preserve baseline observations; the final implementation section records the new behavior and verification.

## Completed: direct quality commands

Removed the 307-line Rust checker, its package manifest, workspace entry, lockfile entry, and Cargo alias.
Removed its Arch-lint restrictions and the CI installation of Cargo Modules.
CI now calls this command directly:

```sh
arch-lint --config arch-lint.toml check --engine syn .
```

Formatting, Clippy, SQLFluff, documentation, dependency, build, and release checks remain separate tool commands.
No replacement checker or development dependency was added.
The existing external packages remain necessary elsewhere in the dependency graph.
This change does not establish a measured application speed improvement.

Code review now checks asynchronous syntax, declared dependency boundaries, module cycles, and source-selection changes.
The user selected this coverage explicitly.
Arch-lint still checks imports and qualified paths.
Cargo Deny still rejects prohibited runtimes.
The [quality gates](quality-gates.md) identify automatic checks and review requirements separately.

Cargo Modules 0.26.0 has `--acyclic`, but it checks the graph before applying output filters.
The direct command rejected `deadlock_data::error::Error` and its `new` method as a cycle.
It cannot directly replace the previous check restricted to modules.
Cargo Modules remains an optional command for manual graph inspection.

The analysis build fingerprint includes the workspace manifest and lockfile.
Their changes invalidate earlier analysis resume identities after recompilation.
Existing evidence formats remain unchanged.
See [fingerprint inputs](../crates/deadlock-analysis/build.rs) and [resume admission](../crates/deadlock-analysis/src/refresh.rs).

## HIGH PRIO

### H1. Require complete backup validation before restoration

**Evidence:** [restore_latest](../crates/deadlock-steam/src/cache_restore.rs#L38) checks the cache hash only when the manifest field contains a string.
Missing, null, and numeric values bypass that check.
A valid KV3 structure alone does not establish that the backup bytes match the recorded backup.

Six temporary cases exercised the public restoration interface:

| Manifest case | Accepted | Destination changed |
| --- | --- | --- |
| Correct hash | Yes | Yes |
| Missing hash | Yes | Yes |
| Null hash | Yes | Yes |
| Numeric hash | Yes | Yes |
| Incorrect string hash | No | No |
| Valid backup plus malformed older manifest | No | No |

The final case also exposes a selection defect.
[latest_backup](../crates/deadlock-steam/src/cache_restore.rs#L74) aborts when any candidate manifest fails parsing.
An invalid older manifest therefore blocks a valid newer backup.

**Recommended change:** Require a valid SHA-256 field, matching bytes, valid account, valid destination, and valid timestamp for each candidate.
Select the newest fully validated candidate.
Report rejected candidates without deleting their files.
Retain the existing process checks, recovery backup, and atomic cache replacement.

**Acceptance:** Reject malformed hash fields before writing the destination.
Restore the newest valid candidate when an older candidate is malformed.
Refuse restoration when no candidate passes complete validation.

## MED PRIO

### M1. Remove unused SQL fields before JSON conversion

[select_decision_rows.sql](../crates/deadlock-analysis/sql/discovery/select_decision_rows.sql) returns 45 fields.
[load_checkpoints](../crates/deadlock-analysis/src/checkpoint_data.rs) derives inventory and economy fields, then removes unused input fields.
The [database reader](../crates/deadlock-analysis/src/database.rs#L96) first converts every result row into JSON text and parses it again.

An isolated projection retained the 23 SQL fields needed by the current checkpoint reader.
It removed unused descriptions, item metadata, and candidate-slate JSON before conversion.
All 559,023 projected rows matched the corresponding original values and order.

| Hero ID | Rows | Original median seconds | Narrow median seconds | Reduction |
| --- | ---: | ---: | ---: | ---: |
| 1 | 146,608 | 1.166 | 0.626 | 46.3% |
| 12 | 82,255 | 0.679 | 0.383 | 43.7% |
| 31 | 230,422 | 1.778 | 0.955 | 46.3% |
| 35 | 99,738 | 0.812 | 0.449 | 44.7% |

Serialized result size fell from 838,034,077 bytes to 288,273,134 bytes across these four heroes: 65.6%.
These sizes describe normalized JSON arrays produced by the probe, not database storage or peak process memory.

**Recommended change:** Narrow the production projection to its consumed fields.
Keep the existing Rust reader and its error handling.
The user selected a SQL-only implementation for this finding.

**Acceptance:** Compare complete checkpoint outputs, missing values, row order, and downstream admission decisions against the baseline.
The current measurement covers SQL execution and JSON decoding.
It does not measure inventory reconstruction, numerical fitting, or complete generation.

### M2. Make extraction resource limits configurable

Extraction fixes [memory at 12 GB](https://github.com/sxndmxn/deadlock-build-sync/blob/d650e45985e0d8bf88ab6280bb748244aebfbac4/crates/deadlock-analysis/sql/extract/set_memory_limit.sql) and [threads at eight](https://github.com/sxndmxn/deadlock-build-sync/blob/d650e45985e0d8bf88ab6280bb748244aebfbac4/crates/deadlock-analysis/sql/extract/set_threads.sql).
[connect_database](../crates/deadlock-analysis/src/extraction.rs) applies these values independently of `--workers`.
Reducing hero workers therefore does not reduce these extraction settings.

**Recommended change:** Add validated extraction memory and thread settings.
The user selected the existing 12 GB and eight-thread defaults.
Document the distinction between extraction resources and hero-worker resources.
Include Rust-owned records and numerical matrices when measuring total memory.
The 512 MiB worker database limit does not bound those allocations.

**Acceptance:** Demonstrate that reduced settings reach DuckDB and preserve extraction results on a fixed snapshot.
No fresh extraction or resource-limit benchmark ran during this audit.

### M3. Avoid cloning the complete evidence catalog for all heroes

[select_hero_subset](../crates/deadlock-guides/src/evidence_catalog.rs#L114) returns `self.clone()` when the requested roster equals the complete roster.
The catalog owns parsed hero records, asset records, and the complete raw artifact bytes.
[generate_guides](../crates/deadlock-build-sync/src/generation.rs) calls this method for normal generation.

The recorded evidence file contains 141,656,493 bytes.
A full clone copies these bytes in addition to its parsed records.
This byte count is measured; the runtime and peak-memory effects were not measured.

**Recommended change:** Borrow the unchanged catalog or share immutable catalog storage.
Create a separate owned catalog only when a real subset requires a new identity.
Preserve subset validation and fingerprint rules.

### M4. Reduce complete artifact-directory copying

[ArtifactTransaction::new](../crates/deadlock-build-sync/src/artifact_transaction.rs#L37) copies the existing destination into staging.
[copy_directory](../crates/deadlock-build-sync/src/artifact_transaction.rs#L104) copies and synchronizes each file before generation rewrites current artifacts.

The recorded `generated/rust-layout-final` directory contains 1,607 files and 889,383,614 logical bytes.
Every repeat walks this complete directory.
Physical copy cost depends on the filesystem; no repeated-copy benchmark ran.

**Recommended change:** Stage the required current artifacts and retained user files explicitly.
Evaluate filesystem cloning for immutable retained files where supported.
Keep a portable copy fallback and the complete recovery protocol.
Do not replace isolated staging with in-place writes or mutable hard links.

**Acceptance:** Check unchanged repeats, retained files, interrupted commits, and recovery before comparing I/O and disk use.

### M5. Correct current documentation that points to retired code

The baseline contains 65 tracked Markdown files totaling 1,381,079 bytes.
A relative-link scan found 174 missing local file targets in five documents.
The scan checks file existence; it does not validate heading anchors or external links.

| Document | Missing local link occurrences |
| --- | ---: |
| `docs/sql-query-audit-2026-09-11.md` | 161 |
| `docs/deadlock-build-usage-audit.md` | 6 |
| `docs/repository-and-deadlock-build-research-2026-08-17.md` | 5 |
| `docs/monitoring-runbook.md` | 1 |
| `docs/research/purchase-guide-search/display-design.md` | 1 |

[tools/comparisons/README.md](../tools/comparisons/README.md) also describes the removed Python source directory as the current application.
The [monitoring runbook](monitoring-runbook.md) retains an implementation-contract label and links to a removed Python test.

**Recommended change:** Correct current operational documents for Rust.
Give historical source references permanent links to their recorded Git revision.
Identify unimplemented monitoring requirements explicitly.
Do not substitute historical verification results for current checks.

### M6. Include the existing codec notices in release archives

The [codec notice file](../crates/deadlock-steam/THIRD_PARTY_NOTICES.md) records three upstream projects and their copyright notices.
The [packaging script](../scripts/package_release.sh) copies only the executable, project license, and README.
The codec notice file is absent from that package definition and the inspected historical archive.

**Recommended change:** Include the existing notice file in the release archive.
Check its presence and contents during archive inspection.
This requires no application dependency or runtime change.

## LOW PRIO

### L1. Review historical report duplication

Several reports describe successive verification runs rather than separate current interfaces.
Examples include the September 7 full-hero, uncapped-hero, consolidated-hero, and code-reduction reports.
The Rust verification report also combines migration evidence with several later performance iterations.

**Recommended change:** Maintain one current verification index with revision, scope, result, and evidence links.
Keep detailed historical records under a clearly identified archive or link to their Git revisions.
Retain current architecture, quality gates, build rules, and operating instructions as separate authoritative documents.

### L2. Measure repeated partition construction

[ExportContext::open_database](../crates/deadlock-analysis/src/discovery_models.rs#L52) prepares discovery partitions for every opened hero connection.
The [fixed-partition query](../crates/deadlock-analysis/sql/discovery/create_fixed_partitions.sql) groups the shared player table.
Discovery and validation open connections separately.

**Recommended change:** Measure this setup cost separately from hero-specific queries.
If material, persist the frozen partition mapping once with the extraction identity.
Preserve connection isolation and exact split boundaries.
No speed improvement is claimed for this candidate.

### L3. Validate personal-snapshot ordering explicitly

[create_purchases.sql](../crates/deadlock-analysis/sql/extract/create_purchases.sql) selects the last eligible array position with `list_last`.
This assumes chronological source arrays.
The query does not enforce that assumption itself.
The [earlier SQL audit](sql-query-audit-2026-09-11.md) identified the same concern.

**Recommended change:** Check array alignment and timestamp ordering before deriving purchase wealth.
Alternatively, use a validated latest-observation relation with an explicit policy for duplicate timestamps.
First measure the invariant in recorded source data.
This audit did not establish malformed live arrays or quantify their effect.

## Initial audit measurement method

The query probe used the repository's cached Rust release dependencies and DuckDB `v1.5.5`.
The database opened read-only with one thread and a 512 MiB database memory limit.
Temporary partition tables remained connection-local.
The spill limit was 128 MiB.

Each query received one warmup and three measured runs.
The probe alternated original and narrow execution order.
Rank bounds were 71 through 115.
Build processes were idle during these query measurements.
Results use medians and do not estimate whole-pipeline savings.

Recorded source:

```text
generated/viscous-rust-state/deadlock-build-sync/offline/results/all-guides-20260912-layout/raw/analysis.duckdb
```

The source manifest records DuckLake snapshot 56 and cutoff `2026-09-12T12:02:45Z`.
The local probes and detailed result files remain under `/tmp/deadlock-repository-audit-20260912/`.
They are isolated audit artifacts, not repository tools or CI dependencies.
The completed profiling executable was removed to recover build space; its source and results remain.

## Initial audit verification

| Check | Result |
| --- | --- |
| Fast-forward local master and preserve user documents | Passed |
| Workspace metadata, TOML, CI YAML, removal references, and changed document links | Passed |
| `cargo fmt --all --check` | Passed |
| Direct Arch-lint, 233 Rust files | Passed; zero violations |
| 22 isolated permitted/prohibited import cases | Passed |
| SQLFluff 4.3.0 across all 53 SQL files | Passed |
| Cargo Deny advisories, bans, licenses, and sources | Passed |
| Default CLI build | Passed |
| Default help and missing-analysis-feature refusal | Passed |
| Strict Clippy, all targets and features | Both development-profile attempts failed: insufficient disk space |
| Strict Clippy, all targets and features, `--release` | Passed |
| Cargo documentation, all features, `--release` | Passed |
| Cargo documentation, default profile | Did not run after the repeated native archive failure |
| Current release build | Failed at linking: insufficient disk space |
| Existing historical archive, checksum and 15 executable checks outside the checkout | Passed; does not certify a new release |
| Six isolated restoration cases | Completed; H1 records the defects |
| Four-hero SQL projection comparison and timing | Passed; 559,023 projected rows agree |
| Fresh full-pipeline measurement, Linux CI, and live Steam operations | Did not run |

The initial standalone recovery probe failed to link against release LLVM bitcode without the matching LTO setting.
Recompilation with `-C lto=thin` passed, and all six cases completed.
Both development-profile Clippy attempts exhausted disk space while creating the bundled DuckDB archive.
Cleanup removed only incomplete archives from those attempts, obsolete quality-crate build files, and the completed profiling executable.

The release-profile Clippy and documentation checks passed using cached native dependencies.
The fresh release link later failed with `errno=28` because temporary link files exhausted disk space.
At the initial audit, the required development-profile gate and a fresh release remained unverified.
The historical archive check does not change those results.


## MED implementation and verification

All six MED changes are implemented on the existing branch.
M1 is limited to SQL, as requested.
No row-mapping visitor, application dependency, CI wrapper, or repository unit test was added.
HIGH and LOW findings remain open.

### Implemented behavior

| Finding | Change |
| --- | --- |
| M1 | Explicit CTE and final projections return 23 decision fields. Joins, filters, ordering, and the Rust reader remain unchanged. |
| M2 | `--extraction-memory-mb` and `--extraction-threads` configure DuckDB directly. Defaults remain 12000 decimal MB and eight threads. |
| M3 | Full-roster selection shares immutable catalog storage through `Arc`. Real subsets retain separate admission and identity calculation. |
| M4 | Staging writes the generated bundle first. Commit copies retained files without copying generated replacements. |
| M5 | Historical source links use permanent Git revisions. Current documents identify Rust behavior and distinguish proposed monitoring requirements. |
| M6 | Release archives include `THIRD_PARTY_NOTICES.md`. Archive inspection compares its contents with the codec notice file. |

`RefreshRequest` now includes an `ExtractionResources` record with positive memory and thread limits.
Extraction options do not change hero-worker limits.
Resume continues to require completed extraction and a compatible implementation identity.
The source changes alter that identity; earlier runs require a new run identifier after recompilation.
Evidence schemas and admission rules remain unchanged.
Catalog accessors retain their return types; `metadata` and `heroes` are no longer `const` functions.

### SQL results

The final benchmark used the same recorded database, DuckDB 1.5.5, ranks, and memory limits as the initial audit.
It compared the original SQL with the actual modified SQL.
Build processes were idle during the final benchmark.
Each query received one warmup and three alternating measured runs.
The table reports median query execution and JSON-decoding time.

| Hero ID | Rows | Original seconds | Modified seconds | Reduction |
| --- | ---: | ---: | ---: | ---: |
| 1 | 146,608 | 1.172 | 0.548 | 53.2% |
| 12 | 82,255 | 0.682 | 0.338 | 50.4% |
| 31 | 230,422 | 1.758 | 0.833 | 52.6% |
| 35 | 99,738 | 0.810 | 0.397 | 51.0% |

Normalized JSON size fell from 838,034,077 bytes to 288,273,134 bytes, a 65.6% reduction.
All 559,023 projected rows matched their original values and order.
Separate checks compared complete checkpoint outputs, including reconstructed inventories and economy fields.
All 559,023 complete checkpoint outputs also matched.
The unchanged numerical consumers therefore receive identical checkpoint inputs for these four heroes.
Complete downstream numerical production was not rerun.

Seven local checkpoint cases passed under both extraction configurations.
They cover complete state, null team wealth, incomplete teams, missing enemies, null personal wealth, stale observations, and same-second observations.
The stale and same-second cases produced zero checkpoints under both queries.
`EXPLAIN ANALYZE` plans for the original and modified queries remain with the verification records.

Separate hero-31 checkpoint processes recorded maximum resident sizes of 2,372,927,488 bytes before the change and 2,357,510,144 bytes afterward.
These single-run memory measurements do not establish a sustained memory reduction or complete-pipeline performance.

### Resource, evidence, and transaction checks

A local source fixture produced identical contents in all 11 derived extraction tables under both resource configurations.
The configurations used 12000 MB with eight threads and 256 MB with one thread.
The comparison includes frozen split boundaries and 720 decision opportunities.
DuckDB reported the expected thread counts and corresponding memory limits.
Zero-valued resources failed before database creation.
CLI checks rejected zero, negative, malformed, and overflowing resource values.

Full-roster catalog selection shared all parsed records and 141,656,493 raw bytes.
Pointer checks covered metadata, hero records, assets, and raw bytes.
Subset checks verified independent storage, changed identity, retained parent identity, repeat admission, and rejection of empty or unknown selections.
The shared catalog remained usable after the original handle was dropped.

The artifact fixture reduced copied logical data from 18,874,368 bytes to 2,097,152 bytes.
This count measures data passed to file copying, not physical storage writes.
Historical builds and unrelated files retained their contents.
Checks covered unchanged repeats, narrative reuse, abandoned staging, locking, symbolic links, special files, and both file-versus-directory conflicts.
An injected installation failure restored the original destination.
Injected rollback and directory-synchronization failures retained recovery files.
A child process terminated between directory replacements retained the original bundle in its recovery directory.
No full-size artifact-directory I/O benchmark or machine power-loss check ran.

### Final checks

| Check | Result |
| --- | --- |
| `cargo fmt --all --check` | Passed |
| Strict development-profile Clippy, workspace, all targets and features, locked | Passed; zero findings |
| Direct Arch-lint across 233 Rust files | Passed; zero violations |
| SQLFluff 4.3.0 across all 51 current SQL files | Passed |
| Development-profile Cargo documentation, workspace and all features, locked | Passed |
| Cargo Deny advisories, bans, licenses, and sources, locked | Passed |
| Default CLI build and missing-analysis-feature refusal | Passed |
| Fresh analysis-enabled release build | Passed |
| Twelve CLI checks, including recorded-artifact quality admission | Passed; the quality report correctly returned `unevaluated` |
| Fresh archive inspection outside the checkout | Passed; version, notices, license, README, and all 13 command help checks |
| Repository Markdown file links and archived Git targets | Passed; zero missing targets |
| `git diff --check` | Passed |
| New live extraction, full numerical production, Linux CI, and live Steam writes | Did not run |

The complete local gate passed with Rust 1.92.0.
Cargo used two build jobs, with incremental compilation disabled for development checks.
Removal of disposable Cargo incremental files supplied enough space for verification.
Recorded data and user documents remain intact.

The verified archive is `dist/deadlock-build-sync-0.1.0-aarch64-apple-darwin.tar.gz`.
Its SHA-256 file remains beside it.
No release was published.
Temporary verification sources, execution plans, and results remain under `/tmp/deadlock-med-verification/`.
Fixture results do not certify live builds.
