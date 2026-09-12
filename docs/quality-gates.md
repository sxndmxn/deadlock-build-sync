# Quality gates

All repository Rust code forbids unsafe code and treats warnings as errors.
The application contains no asynchronous functions, blocks, or await expressions.
No unit tests were added during the rewrite, as requested.
The current gates do not claim unit-test coverage or mutation coverage.

## Required limits

| Check | Requirement | Enforcement |
| --- | --- | --- |
| Compiler warnings | Zero | Cargo workspace lints and `.cargo/config.toml` |
| Unsafe repository code | Forbidden | Compiler lint with `forbid` |
| Clippy findings | Zero in `all`, `pedantic`, and `nursery` | Cargo workspace lints |
| Cognitive complexity | At most 21 | Clippy and `clippy.toml` |
| Asynchronous repository code | Zero | Code review; Cargo Deny separately rejects prohibited runtimes |
| Cyclic crate or module dependencies | Zero | Cargo checks crate cycles; code review checks module cycles |
| Project dependencies outside the architecture | Zero | Manifest review against the architecture |
| Imports outside the architecture | Zero | Arch-lint rules in `arch-lint.toml` |
| Panic helpers and unfinished macros | No `unwrap`, `expect`, `panic`, `todo`, `unimplemented`, or `dbg` calls | Clippy |
| Lint exceptions without a reason | Zero | Clippy |
| SQL violations | Zero outside the recorded syntax exceptions | SQLFluff |
| Known dependency advisory failures | Zero | Cargo Deny |
| Unapproved dependency sources or licenses | Zero | Cargo Deny |
| Duplicate package versions | Only the named, explained exceptions | `deny.toml` |

The unsafe restriction applies to repository crates, including build scripts.
Safe interfaces in dependencies can use unsafe Rust or native implementation code.
The dependency policy rejects asynchronous runtimes, including Tokio, Async-std, Smol, and Async-executor.
It also rejects Reqwest because its blocking client requires Tokio.

## Tool setup

Rustup selects Rust 1.92.0 through `rust-toolchain.toml`.
A C++ compiler is necessary for bundled DuckDB.
Install the two pinned Rust check tools:

```bash
cargo install cargo-deny --version 0.20.2 --locked
cargo install arch-lint-cli --version 0.6.0 --locked
```

SQLFluff remains a development tool.
Its isolated `uvx` environment does not supply an application runtime.
No Python application environment or Node workflow is required.

Arch-lint runs as a separate development executable.
It adds no application dependency and generates no unit tests.
The configuration selects architecture rules and rejects unwrap and expect calls.
Compiler and Clippy settings enforce their configured Rust lints.
Code review covers the requirements that these tools do not check.
Do not enable rules that require asynchronous I/O or unselected logging and error packages.

## Complete local gate

Run these commands from the repository root:

```bash
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
arch-lint --config arch-lint.toml check --engine syn .
uvx --from sqlfluff==4.3.0 sqlfluff lint crates/deadlock-analysis/sql
cargo doc --workspace --all-features --no-deps --locked
cargo deny --locked check --deny warnings
cargo build --package deadlock-build-sync --locked
```

Each command returns its own check result directly.
`cargo lint` is an alias for the strict Clippy command above.
The alias resides in `.cargo/config.toml`.
`Cargo.toml` contains compiler and Clippy lint settings.

### Review requirements

Review asynchronous functions, blocks, closures, await expressions, and macro tokens.
Runtime dependency bans do not prohibit asynchronous syntax by themselves.
Review normal, build, and development dependencies against [architecture](architecture.md).
Review module changes for cycles.
Review source-selection patterns to include every repository Rust source file, including build scripts.
CI does not automatically check these review requirements.

Cargo metadata supports manifest inspection:

```bash
cargo metadata --no-deps --format-version 1 --locked
```

Cargo Modules is optional and is not installed by CI.
Use its filtered graph for manual module review:

```bash
cargo install cargo-modules --version 0.26.0 --locked
cargo modules dependencies --package deadlock-data --lib --all-features \
  --no-externs --no-sysroot --no-owns --no-fns --no-types --no-traits
```

Select each changed package and its library or binary target.
Version 0.26.0 applies `--acyclic` before the graph filters.
That option rejects valid relationships between types and their methods.
It does not provide the required cycle check restricted to modules.

Check the default binary before the analysis build:

```bash
target/debug/deadlock-build-sync --help
target/debug/deadlock-build-sync refresh-evidence
```

The second command must fail with the analysis-feature requirement.
It must not contact the API or modify Steam data.
Build and inspect the complete release:

```bash
cargo build --package deadlock-build-sync --features analysis --release --locked
sh scripts/package_release.sh "$PWD/target/release/deadlock-build-sync" "$(rustc -vV | sed -n 's/^host: //p')"
```

The packaging script creates an archive and SHA-256 file under `dist/`.
It extracts the archive into a temporary directory outside the checkout.
It checks the version, license, README, codec notices, and help for all 13 commands there.
The extracted codec notices must match the repository notice file exactly.
The release workflow produces a Linux AMD64 archive with analysis enabled.
CI retains the verified archive and its checksum as a downloadable artifact.
The release job publishes that same archive after checksum and version verification.
It does not rebuild the executable after verification.
Internal workspace crates are not published separately.

CI rejects tracked Python source and Python package files.
It limits Cargo compilation to two jobs and cancels superseded pull request runs.
The Rust cache includes compiled dependencies and the two pinned development tools.
The CodeQL workflow selects Rust and GitHub Actions explicitly.
It uses GitHub's supported `none` build mode and runs on pull requests, master pushes, and a weekly schedule.
The workflow requires advanced CodeQL setup because default setup overrides repository CodeQL workflows.
See [GitHub's setup instructions](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/configure-code-scanning/configuring-advanced-setup-for-code-scanning).

Use `--jobs 2` for Cargo builds when memory or disk space is limited.
Bundled DuckDB omits native debug symbols in development builds.
Application Rust debug symbols remain enabled.
The 512 MiB DuckDB query limit does not bound total producer memory.

## SQL rules

The configuration uses the DuckDB dialect, explicit aliases, uppercase keywords, lowercase identifiers, and final semicolons.
The maximum line length is 88 characters.
Placeholder values permit linting without changing runtime parameter bindings.

SQLFluff 4.3 cannot parse DuckDB `ATTACH`, `DETACH`, `INSTALL`, `LOAD`, or `CREATE SECRET` statements.
Nine administration files retain `PRS` exceptions.
The generic export retains one `AM04` exception because a bound table determines its columns.
Six external column names retain periods from the remote DuckLake schema.
The configuration names these exceptions individually.

Run the SQL check after each SQL change.
Check changed query behavior with an isolated database fixture.
Do not treat a successful parser check as evidence of correct query results.

## Verification reports

Identify every check that passed, failed, or did not run.
Keep fixture checks separate from live verification.
Do not run a live Steam sync without explicit user authorization.
Record cache, backup, artifact, build-count, and skipped-hero results after an authorized live run.

The [Rust verification report](rust-rewrite-verification.md) records the migration comparisons.
The archived Python checks establish the reference behavior only.
They do not certify the Rust executable or live builds.
