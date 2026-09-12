# Rust package selection

Research date: 2026-09-11.
Repository reference: `d603d6b53bb110d0ac48a689f037861e6453b243`.

## Decisions

Prefer the standard library when the required code is small and clear.
Use a dependency when it removes substantial implementation work or difficult correctness risks.
Compare that benefit with maintenance, integration, build, and transitive dependency costs.
The objective is a maintainable synchronous implementation with justified dependencies.
Keep database production and numerical analysis in a separate crate.
Use existing SQL and artifact contracts as the compatibility reference.
Do not replace the numerical methods because another package has a similar name.

The initial research covers 58 crates and 28 dependency configurations.
It includes registry metadata, upstream activity, published source, dependency graphs, advisory checks, and executable probes.
The [evidence directory](research/rust-packages/) contains the results.

The runtime uses Ureq, Clap, Serde, JSON, SHA-2, Chrono, Tempfile, LZ4, Zstandard, Base64, Prost, Htmlize, Regex Lite, and Statrs.
`num-traits` supplies checked numeric conversion support.
The local Steam display-name lookup does not justify a VDF package.
Every selected direct dependency has an implemented use.

DuckDB is the appropriate database engine for the analysis crate.
Basin and `leiden-rs` supply the numerical methods.
Completed fixture comparisons support these selections.
The comparisons do not establish identical behavior for every future input.

## Dependency tradeoffs

Evaluate the actual repository requirement before selecting a package.
Record the code it replaces and the behavior that application code must still provide.
Use package counts and executable measurements as supporting evidence.
Do not use them as the selection objective.

| Requirement | Dependency benefit | Decision basis |
| --- | --- | --- |
| HTTP and TLS | Provides protocol handling, secure connections, connection reuse, timeouts, and redirects. | A maintained client avoids substantial protocol implementation. |
| JSON and typed serialization | Provides parsing, escaping, numeric conversion, and structural decoding. | Serde avoids a custom format implementation. |
| CLI parsing | Provides command dispatch inputs, help, validation, and argument relationships. | Clap reduces repeated code across 13 commands. |
| Hashing and compression | Provides established algorithms and format compatibility. | Custom implementations would add substantial correctness risks. |
| Temporary files | Provides secure file creation and atomic persistence. | The package removes difficult filesystem details; transaction validation remains application code. |
| Database queries | Preserves the existing SQL engine and its execution behavior. | DuckDB avoids replacing the query engine and existing SQL. |
| Dataframe operations | Can replace repeated joins, grouping, filtering, and null handling. | Compare the actual transformations before removing a dataframe dependency. |
| Numerical methods | Can replace substantial solver and distribution implementations. | Require maintenance evidence and compatible results, regardless of package size. |
| Local Steam display name | Would replace a small read-only lookup for one account field. | Use a limited reader without an additional VDF package. |

Maintenance requires evidence about the package and its dependencies.
The hosting service alone does not establish quality.
The no-async requirement still applies to every selected configuration.

## Requirements and interpretation

The Rust code must use synchronous I/O.
The workspace forbids unsafe code and denies compiler warnings.
Clippy denies its `all`, `pedantic`, and `nursery` groups.
Additional restrictions reject unchecked panic helpers and unfinished implementation macros.
The rewrite must preserve the existing commands, artifact formats, and Steam data protections.
No new unit tests form part of this work.

The unsafe restriction applies to repository code, including generated code compiled into repository crates.
This interpretation permits safe dependency interfaces.
It does not mean that the complete dependency graph contains no unsafe implementation.
The standard library, TLS implementation, compression decoder, and database bindings contain trusted implementation boundaries.
`ruzstd` contains unsafe allocation and buffer operations despite its pure Rust implementation.
DuckDB uses native C++ code through Rust bindings.
These dependencies cannot support a claim that all compiled code is unsafe-free.
See the [decoder source](https://docs.rs/crate/ruzstd/0.9.0/source/src/decoding/ringbuffer.rs) and [DuckDB client source](https://github.com/duckdb/duckdb-rs).

## Method and limits

Registry checks used the latest stable, non-yanked package release available during collection.
The [registry snapshot](research/rust-packages/registry.json) records versions, publication dates, licenses, minimum Rust versions, repositories, and archive checksums.
Downloaded source archives were checked against registry checksums before inspection.

Maintenance checks considered release history, accessible source, archive status, recent code changes, and advisory results.
A recent release alone does not establish maintenance quality.
An old release alone does not establish abandonment.
Stars and download totals did not determine selection.
The [repository snapshot](research/rust-packages/repositories.json) records the available upstream activity data.

Each graph probe used a separate Cargo project and an exact direct dependency version.
This prevents one candidate from enabling another candidate's optional features.
Counts include unique package versions in normal and build dependencies.
Counts exclude the probe package and development dependencies.
The target was `x86_64-unknown-linux-gnu`.
Counts measure dependency scope, not runtime memory or final executable size.

The HTTP executable probes used Rust 1.92.0 on macOS 15.5 with an ARM64 processor.
Each probe had an independent release build directory.
Each executable contained a request path and accepted its URL as an argument.
The smoke runs used no arguments and performed no network requests.
The timings are single samples, not performance benchmarks.
They do not measure Linux builds, request throughput, or memory consumption.

## Runtime packages

| Requirement | Selection | Release date | Features and scope |
| --- | --- | --- | --- |
| HTTP and TLS | `ureq 3.4.1` | 2026-09-06 | Disable defaults. Enable `rustls,gzip`. |
| CLI parsing | `clap 4.6.6` | 2026-08-06 | Disable defaults. Enable `std,derive,env,help,usage,error-context`. |
| Typed data | `serde 1.0.229` | 2026-07-18 | Enable `derive`. |
| JSON | `serde_json 1.0.151` | 2026-07-20 | Enable `float_roundtrip`. Preserve explicit domain validation. |
| Fingerprints | `sha2 0.11.0` | 2026-03-25 | Retain SHA-256. |
| UTC timestamps | `chrono 0.4.45` | 2026-06-04 | Disable defaults. Enable `std,now`. |
| Temporary files | `tempfile 3.27.0` | 2026-03-11 | Use temporary files in the destination directory. |
| LZ4 blocks | `lz4_flex 0.14.0` | 2026-07-14 | Disable defaults. Enable `std,safe-encode,safe-decode,checked-decode`. |
| Zstandard decoding | `ruzstd 0.9.0` | 2026-07-26 | Disable defaults. Enable `std,hash`. |
| Base64 data | `base64 0.23.1` | 2026-08-04 | Use only where an existing artifact requires Base64. |
| Protobuf messages | `prost 0.14.4` | 2026-06-07 | Disable defaults. Enable `std,derive`. Encode the known hero-build messages. |
| Steam display name | Standard library | Not applicable | Read the selected account's local display name. Do not add a VDF package. |

Publication dates and minimum Rust versions come from the [registry snapshot](research/rust-packages/registry.json).
Feature selections come from the published manifests recorded in the [graph probes](research/rust-packages/dependency-graphs.json).
The selected versions declare minimum Rust versions no higher than 1.92.
The workspace compiler checks provide additional evidence for dependencies already in use.

### HTTP

Choose `ureq`.
It provides synchronous requests, connection reuse, TLS, timeouts, redirects, and bounded body reads.
Its implementation does not require an asynchronous runtime.
The project must still implement retry policy, request spacing, response recording, and schema validation.
[Ureq documentation](https://docs.rs/ureq/latest/ureq/), [upstream repository](https://github.com/algesten/ureq).

| Candidate configuration | Packages | Executable bytes | Cold build seconds | Decision |
| --- | ---: | ---: | ---: | --- |
| `ureq`, `rustls,gzip` | 30 | 2,445,728 | 14.73 | Select. |
| `minreq`, `https-rustls` | 21 | 3,521,936 | 34.28 | Smaller graph, but no measured executable advantage. |
| `reqwest`, `blocking,rustls,gzip` | 102 | 4,873,024 | 47.13 | Reject. Its blocking client still uses Tokio. |
| `ureq` plus direct `url` | 65 | Not measured | Not measured | Avoid for the current endpoint requirements. |

The [build measurements](research/rust-packages/build-probe-summary.json) support this comparison only for the stated probe programs.
The `minreq` probe does not include equivalent gzip functionality.
Package counts alone would therefore give an incomplete comparison.
Reqwest explicitly documents its blocking interface over the asynchronous client.
[Reqwest blocking documentation](https://docs.rs/reqwest/latest/reqwest/blocking/), [Minreq documentation](https://docs.rs/minreq/latest/minreq/).

Use Ureq's HTTP URI type and query construction methods.
Validate absolute HTTP or HTTPS endpoints before requests.
Do not write another general URL parser.
The direct `url` dependency added 35 packages in these probes.
International domain handling is not a requirement for the configured analytics endpoints.

`attohttpc` and `curl` remain usable synchronous alternatives.
The former introduces another TLS feature selection without a demonstrated requirement advantage.
The latter introduces a native libcurl boundary and deployment requirements.
Neither improves the present scope enough to replace Ureq.
[Attohttpc](https://github.com/sbstp/attohttpc), [Curl Rust bindings](https://github.com/alexcrichton/curl-rust).

### CLI, JSON, time, and errors

Clap supplies 13 commands and their shared options, including deterministic narrative generation.
The reduced feature configuration has 10 packages, compared with 17 for the tested default configuration.
Lexopt has one package and remains a credible alternative for a smaller CLI.
Here, it would move help generation and argument relationship checks into application code.
Pico-args has an older release and a smaller interface, but neither fact alone means that it is defective.
[Clap](https://docs.rs/clap/latest/clap/), [Lexopt](https://github.com/blyxxyz/lexopt), [Pico-args](https://github.com/RazrFalcon/pico-args).

Serde replaces the data conversion role of `cattrs`.
Use typed structures for closed contracts and reject unknown fields where the contract requires this.
Use explicit validation for identifiers, numeric bounds, completeness, and cross-field relationships.
Serde does not perform those domain checks automatically.
Retain original response bytes separately from decoded data.
[Serde container attributes](https://serde.rs/container-attrs.html).

JSON fingerprint compatibility requires more than sorted keys.
Python and Rust must agree on floating point text, Unicode, negative zero, and key ordering.
The rank catalog also uses integer keys before Python serialization.
A lexical sort of decoded string keys would change that fingerprint.
SIMD JSON does not address these compatibility requirements.
No measured parser bottleneck currently justifies it.

Chrono with `std,now` provides UTC time without the `clock` feature's local timezone dependencies.
The isolated graph decreased from six packages to three.
Use `std::time::Instant` for request intervals.
`time` and Jiff are maintained alternatives, but they do not solve an additional requirement here.
[Chrono features](https://docs.rs/chrono/latest/chrono/#features), [Time](https://github.com/time-rs/time), [Jiff](https://github.com/BurntSushi/jiff).

Use the standard error traits for the initial error types.
`thiserror` is appropriate if typed error variants make repeated implementations necessary.
Do not add `anyhow` and `thiserror` together without separate requirements.
Keep recoverable Steam errors distinguishable from invalid artifact errors.
[Thiserror](https://github.com/dtolnay/thiserror).

### Steam data and file operations

No reviewed general Steam crate supplies this repository's complete transaction requirements.
Steam account selection, process checks, managed markers, backup manifests, and recovery remain application responsibilities.

Tempfile supplies secure temporary file creation and atomic persistence on the same filesystem.
Its `persist` method does not synchronize file content or the parent directory.
The installer must perform those operations explicitly.
The installer must also validate the replacement and create a recoverable backup before replacement.
Rust's standard file locks remove the need for a separate locking crate on the selected toolchain.
[Tempfile persistence](https://docs.rs/tempfile/latest/tempfile/struct.NamedTempFile.html#method.persist), [standard file locks](https://doc.rust-lang.org/std/fs/struct.File.html#method.lock).

Prost fits the small protobuf message set and has 10 packages in the tested configuration.
Its `tokio-rs` repository owner does not make Tokio a dependency.
The measured graph contains no Tokio.
Derive the known message definitions directly to avoid `protoc` and `prost-build`.
Keep unrelated protobuf blobs unchanged as bytes.
Decoding and encoding every unknown message would risk losing fields or changing their representation.
[Prost](https://github.com/tokio-rs/prost).

`quick-protobuf` is a smaller alternative with a separate code generator.
The project does not need that additional generation workflow.
The broader `protobuf` package also exceeds the current message requirements.
[Quick-protobuf](https://github.com/tafia/quick-protobuf), [Rust protobuf](https://github.com/stepancheg/rust-protobuf).

Rust `keyvalues3` and `kv3` parse textual KV3.
They do not replace the Python binary KV3 reader used for Steam build caches.
The `binary` feature in the reviewed `keyvalues3` package refers to its command executable.
It does not establish binary KV3 support.
Keep a small, bounded binary codec inside the Steam crate.
Reject unsupported encodings before any write.
[KeyValues3](https://github.com/TheCursedApple/KeyValues3), [KV3](https://docs.rs/kv3/latest/kv3/).

Use `lz4_flex` for LZ4 blocks and dictionary decoding.
Disable frame support because the container already supplies block metadata.
Keep the safe encoder, safe decoder, and checked decoder features enabled.
The old 0.12.0 release has a RustSec advisory; 0.12.1 fixed that release line.
The selected 0.14.0 release also passes the advisory check.
[LZ4 changelog](https://github.com/PSeitz/lz4_flex/blob/main/CHANGELOG.md), [RUSTSEC-2026-0041](https://rustsec.org/advisories/RUSTSEC-2026-0041.html).

`ruzstd` has two packages with the selected features and supports the required decoding direction.
The native `zstd` alternative adds a C build boundary.
Neither package removes the need for decoded-size limits and container validation.
[Ruzstd](https://docs.rs/ruzstd/latest/ruzstd/), [Zstandard bindings](https://github.com/gyscos/zstd-rs).

Do not add `vdf-rs`, `keyvalues-parser`, or `keyvalues-serde` for the local display-name lookup.
The `install-artifacts` command reads `config/loginusers.vdf` when the user does not supply `--persona`.
Normal guide generation already obtains the display name through the Deadlock API.
Preserve the local lookup with a limited read-only implementation.
The [Steam identity reader](../crates/deadlock-steam/src/steam_identity.rs) implements this small requirement.

The VDF package measurements remain in the research records as rejected alternatives.
A complete VDF parser would provide more functionality than this lookup needs.
Steamlocate also does not remove the account selection and build cache transaction code.
Its manifest depends on both `keyvalues-parser` and `keyvalues-serde`.
[Steamlocate manifest](https://docs.rs/crate/steamlocate/2.1.1/source/Cargo.toml).

## Offline analysis packages

| Python requirement | Rust decision | Packages | Compatibility condition |
| --- | --- | ---: | --- |
| DuckDB and DuckLake SQL | `duckdb 1.10505.0` | 117 | Use the same engine and SQL contracts. |
| Polars and PyArrow conversion | Existing DuckDB SQL and typed row visitors | No additional direct package | Keep joins, grouping, and null handling in SQL. |
| Dense NumPy operations | Standard vectors; `ndarray 0.17.2` for the graph interface | 7 for Ndarray | Preserve standardization and explicit matrix dimensions. |
| SciPy distributions | `statrs 0.19.1`, defaults disabled, `std` | 11 | Compare numerical tails and acceptance thresholds. |
| Logistic regression | `basin 1.11.0`, defaults disabled | 11 | Standardized probability and contrast comparisons passed. |
| Weighted Leiden discovery | `leiden-rs 0.8.1`, defaults disabled | 16 | Frozen core and group comparisons passed. |
| Thread limits and workers | Standard scoped threads and database settings | No additional direct package | Keep worker limits and deterministic output order. |
| Python timezone bridge | Remove | No additional direct package | Keep timestamps in UTC. |

### Database and arrays

Select DuckDB because the repository already depends on DuckDB SQL and DuckLake behavior.
The Rust crate version `1.10505.0` corresponds to engine `1.5.5`.
The current Python dependency uses engine `1.5.5`.
Disable default features and select `bundled,json,parquet`.
Do not select `modern-full`, connection pools, Polars integration, or user-defined function support.
[DuckDB Rust client](https://duckdb.org/docs/current/clients/rust/overview).

Extraction explicitly installs and loads ICU, DuckLake, and HTTPFS through DuckDB's extension manager.
ICU supplies arithmetic between `TIMESTAMPTZ` and `INTERVAL` for the match cutoff query.
The connection uses UTC so timezone-naive Rust parameters preserve their intended UTC values.
This requires no additional Cargo package or bundled CMake feature.
[DuckDB ICU extension](https://duckdb.org/docs/current/core_extensions/icu), [timestamp arithmetic](https://duckdb.org/docs/current/sql/functions/timestamptz).

The Rust DuckDB wrapper still requires Arrow with these features.
Its 117-package graph is substantial and must remain outside the basic evidence consumer.
The `refresh-evidence` command requires the analysis feature.
`sync` consumes previously admitted evidence and does not start extraction automatically.
The current binding replaced its build-time Reqwest use with Ureq.
The tested graph contains no Tokio.
SQLite and DataFusion would require database semantic changes and provide no clear benefit for this migration.
[DuckDB manifest](https://docs.rs/crate/duckdb/1.10505.0/source/Cargo.toml), [DuckDB releases](https://github.com/duckdb/duckdb-rs/releases).

The tested Polars configuration has 136 packages, including Tokio and Rayon.
Its `parquet,rows` features therefore fail the asynchronous runtime restriction.
The package count does not by itself justify replacing Polars with custom table code.
The implementation retains 53 SQL resources for extraction, joins, grouping, and null handling.
Typed row visitors convert query results directly into domain records.
Vectors hold the numerical feature matrices and explicit inventory histories.
This division does not require another general dataframe engine.
It avoids the Python-to-Arrow-to-Polars conversion boundary while retaining the existing database semantics.
[Polars manifest](https://docs.rs/crate/polars/0.55.2/source/Cargo.toml).

Ndarray is appropriate for matrix views when standard vectors become error-prone.
Disable BLAS and Rayon support initially.
Statrs supplies the required distributions without a general machine learning framework.
Its tested default configuration has 27 packages; the `std` configuration has 11.
[Ndarray](https://github.com/rust-ndarray/ndarray), [Statrs manifest](https://docs.rs/crate/statrs/0.19.1/source/Cargo.toml.orig).

### Logistic regression

The Python implementation uses L-BFGS-B with unbounded coefficients and a logistic objective.
Its intercept is unpenalized.
Its settings include history 10, `factr=64`, `pgtol=1e-4`, 50 line-search evaluations, and 500 iterations.
The objective uses `C=0.5` and training-sample scaling.
The existing implementation remains the reference for preprocessing and fallback behavior.
[Reference solver](https://github.com/sxndmxn/deadlock-build-sync/blob/d603d6b53bb110d0ac48a689f037861e6453b243/src/deadlock_build_sync/offline/logistic_solver.py).

| Candidate | Finding | Decision |
| --- | --- | --- |
| [`argmin 0.11.0`](https://docs.rs/crate/argmin/0.11.0/source/Cargo.toml) | Includes unmaintained `paste`, even with the tested reduced features. | Reject this configuration. |
| [`linfa-logistic 0.8.1`](https://docs.rs/crate/linfa-logistic/0.8.1/source/Cargo.toml) | Includes the same `paste` dependency; 43 packages. | Reject this configuration. |
| [`smartcore 0.6.14`](https://docs.rs/crate/smartcore/0.6.14/source/src/linear/logistic_regression.rs) | Maintained, but its public logistic settings do not expose the required iteration and tolerance controls. | Do not treat it as an equivalent estimator. |
| [`lbfgs 0.3.0`](https://docs.rs/lbfgs/latest/lbfgs/struct.Lbfgs.html) | Supplies an L-BFGS approximation helper, not a complete replacement solver. | Reject as a direct replacement. |
| [`lbfgsb-rs-pure 0.1.2`](https://docs.rs/crate/lbfgsb-rs-pure/0.1.2/source/Cargo.toml) | The advertised repository returned HTTP 404 during inspection. | Maintenance could not be verified. |
| [`liblbfgs 0.1.0`](https://docs.rs/liblbfgs/0.1.0/liblbfgs/) | Older release and a different solver lineage. | No advantage established. |
| [`liblbfgs-compliant-rs 0.1.6`](https://docs.rs/crate/liblbfgs-compliant-rs/0.1.6) | Recent release; documentation warns about its translated implementation. It follows libLBFGS. | No equivalence established. |
| [`basin 1.11.0`](https://docs.rs/crate/basin/1.11.0) | Includes L-BFGS-B and Moré–Thuente; builds without an external matrix backend. | Select with the verified adapter. |

RustSec identifies `paste` as unmaintained and supplies no patched version.
This finding is a maintenance failure, not evidence of a reachable runtime exploit in the proposed solver.
Do not suppress it to accept Argmin or Linfa.
[RUSTSEC-2024-0436](https://rustsec.org/advisories/RUSTSEC-2024-0436.html).

Basin's upstream source includes comparisons with the L-BFGS-B 3.0 reference.
The release offers configurable projected-gradient tolerance, line-search limits, history size, and execution limits.
Its standard relative-cost helper differs from the repository's `factr` stopping formula.
The probe therefore used an explicit stopping condition.
The release was published on the research date, so its release age provides limited operational evidence.
[Basin source](https://docs.rs/crate/basin/1.11.0/source/src/solver/lbfgs.rs), [Basin upstream](https://github.com/jolars/basin).

Six deterministic samples compared Basin against the repository's current Python solver.
Each sample contained 400 rows and 12 features.
The balanced, imbalanced, correlated, constant-column, and separable samples converged in both implementations.
Their maximum probability difference was less than `5e-16`.
The scaled sample reached Basin's 500-iteration limit while the Python solver converged.
Its maximum probability difference was approximately `0.001121`.
The [solver results](research/rust-packages/solver-probe-summary.json) include every sample and input checksum.

These initial probes exposed a termination difference on unstandardized input.
The final adapter preserves preprocessing, the objective, intercept handling, convergence settings, and fallback behavior.
The completed comparisons below use the production adapter.
Rust extraction records include an implementation fingerprint and cannot resume an old Python extraction.

### Leiden discovery

`leiden-rs` provides weighted graphs, RBConfiguration quality, resolution, iteration limits, and an explicit seed.
Disable its default features to avoid CLI and parallel execution dependencies.
The upstream GitCode repository was accessible.
The checked revision includes a degree calculation correction from 2026-05-16.
The recorded commit is `fad950eea78feab2c9a839c93986edc3ac8d716f`.
[Leiden documentation](https://docs.rs/leiden-rs/latest/leiden_rs/), [quality functions](https://docs.rs/leiden-rs/latest/leiden_rs/quality/index.html), [upstream repository](https://gitcode.com/lileeei/leiden-rs).

An identical seed does not imply identical partitions across implementations.
The random generator and node traversal can differ from Python igraph and Leidenalg.
Compare weighted graphs, objective values, partition stability, and admitted build paths.
This package has less maintenance evidence than the main runtime packages.
Retain that uncertainty in the migration decision.

`graphrs 0.12.0` has a Leiden implementation, but its inspected public entry point lacks a seed parameter.
Its internal random generator uses an unspecified seed.
The package's Louvain seed option does not correct this Leiden behavior.
Its dependency graph also includes an unmaintained terminal crate and affected Quick XML releases.
Petgraph supplies graph structures, not an equivalent Leiden implementation.
[Graphrs source](https://docs.rs/crate/graphrs/0.12.0/source/src/algorithms/community/leiden/mod.rs), [Petgraph](https://github.com/petgraph/petgraph).

## Dependency policy and verification

Use `Cargo.lock` for application builds.
Review direct and transitive changes together.
Keep optional analysis dependencies outside the default runtime graph.
Require a concrete implementation benefit before adding a dependency.
Keep simple application-specific operations in repository code when a package would add little benefit.
Do not implement substantial protocol, database, or numerical machinery merely to avoid dependencies.
Do not add an asynchronous runtime.

The [Cargo Deny policy](../deny.toml) rejects known advisory failures and unapproved sources.
It bans Tokio, Async-std, Smol, Async-executor, and Reqwest.
It permits ten named duplicate-version exceptions required by the selected TLS, temporary-file, Arrow, database, graph, and derive dependencies.
Each exception records its exact package version and dependency reason in `deny.toml`.
No advisory or source exception admits a rejected solver.
The policy checks Linux AMD64, Linux ARM64, and macOS ARM64 graphs.
This graph check does not replace compilation on those systems.

Advisory probes passed for the selected runtime, Basin, and Leiden configurations.
The complete workspace dependency gate also passed after the analysis implementation.
Argmin, Linfa, and Graphrs failed for the reasons recorded above.
Graphrs findings include `RUSTSEC-2021-0139`, `RUSTSEC-2026-0194`, and `RUSTSEC-2026-0195`.
The [advisory results](research/rust-packages/advisories.json) retain those findings.
A successful advisory check means that the database reported no matching finding at that time.
It does not certify the absence of defects.
[RustSec database](https://github.com/RustSec/advisory-db).

The existing complete Python fast gate passed during this research.
The [gate results](research/rust-packages/python-gates.json) record each command and result.
The Rust workspace has separate formatting, strict Clippy, documentation, release-build, and dependency checks.
All five checks passed for the initial workspace; those historical results cover only that implementation stage.
The [Rust gate results](research/rust-packages/rust-gates.json) record the commands and results.
The local HTTP checks covered query encoding, redirects, gzip, retries, permanent errors, malformed JSON, and invalid parameters.
Canonical JSON matched Python for 100,009 deterministic samples.
Rank parsing and temporary artifact replacement checks also passed.
The [workspace probe results](research/rust-packages/workspace-probes.json) record these checks.
Those initial probes exercise the data and HTTP crates.
The completed rewrite also includes guide generation, numerical production, Steam transactions, and all CLI commands.
The [Rust verification report](rust-rewrite-verification.md) records the complete migration checks.
No live Steam sync ran.
No new unit tests were written.
The research and compiler probes do not certify live builds.

## Reproduce the package checks

Use the exact manifest from the [dependency graph records](research/rust-packages/dependency-graphs.json) in an independent temporary directory.
Run these commands in that directory:

```bash
cargo tree --target x86_64-unknown-linux-gnu --edges normal,build --prefix none --format '{p}'
cargo install cargo-deny --version 0.20.2 --locked
cargo deny --locked check advisories
```

Count unique package name and version pairs after removing the probe package.
Retain the resulting lockfile when comparing future updates.
New transitive releases can change results unless the recorded resolution is retained.
The [provenance record](research/rust-packages/provenance.json) identifies the toolchain, target, repository revision, and collection time.

## Completed selection checks

The final production probability adapter passed 100 deterministic standardized fixtures.
Cases included missing values, constant features, class imbalance, and single-class fallback.
The maximum absolute probability difference from Python was `7.78e-16`.

Core mining, grouping, outcomes, and 12 complete doubly robust contrasts passed 43,527 comparisons.
The largest numerical difference was `1.30e-11`.
All 24 discovery graph fixtures produced the same groups as the reference.
The reference comparison centered constant features for balance calculations, as described in the verification report.

A database fixture with 2,400 hero appearances produced three admitted current builds.
A second fixture produced three supported beam routes.
The Python artifact validator accepted both generated evidence documents.
The CLI passed complete resume, repeated identity, changed-source rejection, and output-preservation checks.
These checks justify the adapters within the measured scope.
They do not prove identical graph partitions for every possible input.

## Additional runtime requirements

`htmlize 1.1.0` decodes named and numeric HTML entities in item and ability text.
Its `unescape_fast` feature avoids maintaining a local HTML entity table.
The package exposes a dedicated decoding operation rather than a browser document model.
The selected source forbids unsafe Rust. [Htmlize manifest](https://docs.rs/crate/htmlize/1.1.0/source/Cargo.toml).

`regex-lite 0.1.9` handles the existing mechanics patterns and limited read-only account-name lookup.
Its restricted expression engine avoids a general Unicode regex dependency in the default application graph.
The application still defines each domain pattern and validates its result. [Regex Lite documentation](https://docs.rs/regex-lite/latest/regex_lite/).

`statrs 0.19.1` supplies normal-distribution calculations used by deterministic analytics and effect estimates.
`num-traits 0.2.19` supplies explicit numeric conversions without unchecked casts.
These packages replace mathematical implementation details rather than application admission rules.
[Statrs documentation](https://docs.rs/statrs/0.19.1/statrs/), [Num Traits documentation](https://docs.rs/num-traits/0.2.19/num_traits/).

## Complete application dependency graph

The locked Linux AMD64 graph contains 81 external package versions for the default CLI.
Enabling analysis increases that count to 165.
These counts include normal and build dependencies and exclude workspace and development packages.
Neither selected graph includes a prohibited asynchronous runtime.
The [final graph record](research/rust-packages/final-dependency-graphs.json) lists every counted package.

DuckDB and its required Arrow binding account for most additional build scope.
Analysis remains optional so artifact consumers do not compile or link that producer.
Native DuckDB debug symbols are disabled in development builds to reduce build-directory disk use.
The application retains Rust debug symbols.

No application throughput or memory benchmark was run.
The initial package build probes do not establish that the rewritten CLI is faster.
