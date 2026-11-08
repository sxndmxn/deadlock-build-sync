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
| `estimate_enemy_item_counters` | Counter effects of item groups against a share of enemy item cost |
| `measure_counter_windows` | Counter evidence in time windows of one run |
| `compare_scoring_pair` | Held-out signal of one effect scale beyond another |
| `compare_variant_agreement` | Held-out signal of additional builds beyond the main build |
| `compare_situational_signal` | Held-out signal of situational items beyond CORE agreement |
| `compare_scoring_by_landmark` | Held-out agreement of score rules at each test landmark |
| `compare_training_fractions` | Held-out agreement of builds from fewer development matches |
| `measure_label_halves` | Per-hero test results on two halves of the test matches |
| `measure_build_stability` | CORE overlap of builds from two match samples |
| `measure_counter_placebo` | z values of the counter test after random moves of team conditions |
| `measure_pair_placebo` | z values of the paired test after random moves of agreements |
| `measure_label_placebo` | z values of the per-hero test after random moves of agreements |

Run a placebo for each new test model. A placebo removes the real relation, so its z values must follow a standard normal distribution.
A placebo found the flaw of entry E30 in the pooled models.

```bash
cargo run --release -p deadlock-analysis --example compare_effect_models -- \
  ~/.local/state/deadlock-build-sync/offline/results/RUN_ID 200:300 200:300:spirit=2
```

## Data formats

Select the format from the consumer's operations and compatibility requirements.

| Format | Use in this repository |
| --- | --- |
| JSON | Run manifests, API source snapshots, and `hero-builds.json` |
| JSONL | Execution traces |
| DuckDB | Extracted match tables in `analysis.duckdb`, and the download cache |
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
