# Contributing

Follow the language, naming, safety, and verification requirements in [AGENTS.md](AGENTS.md).

## Development setup

Use Linux and the pinned Rust toolchain.
Install a C++ compiler for bundled DuckDB.

```bash
cargo build --package deadlock-build-sync --features analysis --locked
```

Before opening a pull request, run the verification checks in [AGENTS.md](AGENTS.md).

Unit tests remain deferred at the user's request.
Verify changes with the documented checks and isolated reference fixtures.

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
