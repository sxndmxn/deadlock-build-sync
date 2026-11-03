# Contributing

Follow the language, naming, safety, and verification requirements in [AGENTS.md](AGENTS.md).

## Development setup

Use Linux and the pinned Rust toolchain.
Install a C++ compiler for bundled DuckDB.

```bash
cargo build --package deadlock-build-sync --locked
```

Run the shared local and CI checks before opening a pull request:

```bash
bash scripts/check_repository.sh
```

Install `fd`, `jaq`, `rg`, and `uv` before running the checks.
Install the pinned Rust verification tools:

```bash
cargo install rust-code-analysis-cli --version 0.0.25 --locked
cargo install arch-lint-cli --version 0.6.0 --locked
cargo install cargo-deny --version 0.20.2 --locked
```

SQLFluff runs through `uvx` at version 4.3.0.
The shared checks validate formatting, code metrics, Clippy, architecture, SQL, documentation, dependencies, and the default CLI.
The safety executable checks temporary caches, backup validation, preservation, repeated installation, process guards, and artifact recovery.
It checks source fingerprints through the resume workflow and rejects stale installations through a local reference API.
It checks that run removal keeps the current run, named runs, locked runs, and new runs without a lock.
It also checks native imbue targets through catalog serialization and Steam encoding.
Focus checks cover supporting CORE items, conflicting targets, reload effects, descriptions, and title limits.
The analysis executable checks imbue selection with an isolated purchase database and reference assets.
The checks do not read or write live Steam files.
Fixture checks do not certify live builds.

For release validation, run:

```bash
bash scripts/check_repository.sh --release
```

This option also builds the release and checks its archive outside the checkout.
CI installs the verification tools and runs this same command.

Unit tests remain deferred at the user's request.
Verify changes with the documented checks and isolated reference fixtures.

## Data formats

Select the format from the consumer's operations and compatibility requirements.

| Format | Use in this repository |
| --- | --- |
| JSON | Run manifests, API source snapshots, and `hero-builds.json` |
| JSONL | Execution traces |
| DuckDB | Extracted match tables in `analysis.duckdb` |
| Markdown | One build file per hero in `builds/` |

Keep external API formats and documented artifact paths compatible.
Use compact canonical JSON for internal document writes.
Keep fingerprints independent of display formatting where the artifact contract permits this.
For JSONL, write one complete UTF-8 JSON value per line.
Validate complete documents before installation. Reject incomplete documents.
Keep deterministic record order where order affects a fingerprint or result.
Before a format change, measure write time, read time, peak memory, file size, and complete workflow time.

## Pull requests

- Describe the resulting behavior and the reason for each change.
- Retain the Steam data safety rules in [AGENTS.md](AGENTS.md).
- State which checks passed, failed, or did not run.
- Do not include Steam caches, generated artifacts, credentials, or personal
  account data.

## Names and language

Use ASD-STE100 Simplified Technical English for all repository names, including existing names and new names.
Apply the complete naming requirements in [AGENTS.md](AGENTS.md).
Use ASD-STE100 Simplified Technical English for documentation, comments, error messages, commits, and pull request descriptions.
Name each function for its action and the data it processes.
For example, use `select_core_owners` and `build_purchase_guidance`.
Use `read_` and `write_` for functions that consume or produce binary data.
Use predicate names such as `is_active_hero` and `can_plan_substitution`.
Use precise module names, such as `inventory_history.rs`.

Update imports, callers, test references, and configuration when you change a name.
Keep CLI commands, external API identifiers, and serialized field names compatible.
