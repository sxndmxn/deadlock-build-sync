# Arch-lint integration

Review date: September 12, 2026.

Use `arch-lint-cli` 0.6.0 as a pinned development executable.
The user requested this package for the Rust rewrite.
The application dependency graph remains unchanged.

The registry published version 0.6.0 on September 11, 2026.
It declares Rust 1.88 as its minimum version and uses MIT or Apache-2.0 licensing.
The package remains small in adoption: the registry reported 334 total downloads for the facade crate during this review.
Recent releases establish current maintenance activity, but they do not establish long-term maintenance.
Sources: [registry metadata](https://crates.io/api/v1/crates/arch-lint), [upstream repository](https://github.com/ynishi/arch-lint).

## Scope and cost

The upstream CLI supports Rust syntax analysis and Tree-sitter analysis.
Our command selects the Rust syntax engine explicitly.
The published CLI lockfile contains 116 packages, including cross-language parser packages.
It contains no Tokio, Async-std, Smol, or Async-executor package.
The installed executable occupies 12,367,488 bytes on this Mac.
These development dependencies do not enter either application build.

`arch-lint.toml` declares import restrictions for all seven workspace crates.
It also restricts network and database access in guide logic and rejects asynchronous runtime imports.
The configuration fails on warnings.
Compiler, Clippy, and source checks continue to enforce unsafe-code, asynchronous-syntax, and cognitive-complexity requirements.

The upstream scope dependency rule assumes one `src/` directory and resolves `crate::` paths.
It does not resolve workspace crate imports.
We therefore use explicit `restrict-use` rules for workspace boundaries.
Cargo metadata and Cargo Modules retain resolved dependency and cycle checks.
Source: [scope dependency implementation](https://docs.rs/crate/arch-lint-core/0.6.0/source/src/declarative/rules/scope_dep.rs).

## Verification

The Rust 1.92.0 installation passed with the published lockfile.
Arch-lint checked all 237 repository Rust files with zero violations.
The complete architecture gate also passed.

An isolated executable check passed 298 cases without adding repository unit tests.
It checked all 42 directed crate pairs through six path forms.
The cases covered imports, grouped imports, aliases, re-exports, inline expressions, and qualified type paths.
They also checked runtime restrictions, guide boundaries, ignored source files, and warning failures.

The quality checker verifies the tool version and compares its file count with the complete source scan.
This prevents a successful check from silently omitting repository Rust files.
The CLI writes progress lines before JSON output in version 0.6.0.
The quality checker locates the JSON document and validates the complete result.
