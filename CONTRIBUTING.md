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
It also checks native imbue targets through catalog serialization and Steam encoding.
Focus checks cover supporting CORE items, conflicting targets, reload effects, descriptions, and title limits.
Variant checks cover shared heroes, duplicate identities, complete Markdown exports, and separate Steam build IDs.
They also check repeated installation, variant removal, and compatibility with schema 5 catalogs.
Counter checks cover the panel order, the evidence text, the Markdown export, and catalogs with invalid counter panels.
The analysis executable checks imbue selection with an isolated purchase database and reference assets.
The strategy executable checks distinct item combinations, unique player counts, stable selection, and heroes with only one observed strategy.
The item statistics executable checks purchase counts, rank filters, calibration exclusion, variant consistency, legacy display, and invalid counts.
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

## Experiments

Test each change to the build method on extracted runs before you change a default.
Record the hypothesis, method, result, and decision in [docs/research-log.md](docs/research-log.md).
Repeat a result on at least one other patch before a change of the installed builds.

These examples read one run directory and write tab-separated text:

| Example | Measurement |
| --- | --- |
| `compare_item_scoring` | Held-out agreement and CORE adoption for each effect scale |
| `compare_effect_models` | Held-out log loss for ridge penalties and match condition interactions |
| `export_split_item_effects` | Item effects from two halves of the development matches |
| `estimate_counter_interactions` | Counter effects of defensive item groups at each phase |

```bash
cargo run --release -p deadlock-analysis --example compare_effect_models -- \
  ~/.local/state/deadlock-build-sync/offline/results/RUN_ID 200:300 200:300:spirit=2
```

## Data formats

Select the format from the consumer's operations and compatibility requirements.
File size alone does not determine the format.

| Format | Use | Repository application |
| --- | --- | --- |
| JSON | A complete nested document with shared metadata and validation | Manifests, API responses, build evidence, strategy context, policies, and descriptions |
| JSONL | Independent records that a consumer processes one at a time, or events that a writer appends | Execution traces and future record streams |
| CSV | Flat tables for manual inspection or exchange with tools that require CSV | Optional report exports |
| Parquet | Typed tables for repeated filters, joins, aggregations, and selected-column reads | Extracted match, purchase, inventory, and cohort tables |

Keep external API formats and documented artifact paths compatible.
Use compact canonical JSON for internal document writes.
Keep fingerprints independent of display formatting where the artifact contract permits this.
Keep exact byte fingerprints where the artifact contract requires them.

For JSONL, write one complete UTF-8 JSON value per line.
Process records incrementally when memory reduction is the purpose.
Validate each record before use.
For complete snapshots, validate the schema, record count, unique identifiers, coverage, and fingerprint before installation.
Reject incomplete snapshots.
Keep deterministic record order where order affects a fingerprint or result.
The [JSON Lines specification](https://jsonlines.org/) defines the record format.

For CSV exports, specify column names, data types, null representation, timestamp format, and quoting rules.
Keep Parquet as the internal analytical format when a CSV export is necessary.
Use explicit schemas for analytical tables.
The current Parquet exports use Zstandard compression and 100,000-row groups.
Measure changes to compression and row-group size with representative queries.
[DuckDB supports selected-column reads and filter pushdown for Parquet](https://duckdb.org/docs/current/data/parquet/overview).

The evidence reader validates one hero record at a time and retains the complete typed roster.
It retains the original JSON bytes for byte fingerprints and artifact writes.
The context reader indexes hero records in its document without duplicate record copies.
These readers still require complete artifacts for admission.
A JSONL conversion alone would not remove that requirement.
Before a format migration, measure write time, read time, peak memory, file size, and complete workflow time.
Include conversion costs in the measurements.
Compare identifiers, types, nulls, timestamps, ordering, and numerical values with the previous format.
Retain admission checks, recovery, and atomic installation.

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
