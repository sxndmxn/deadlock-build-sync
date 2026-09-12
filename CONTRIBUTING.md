# Contributing

Follow the language, naming, safety, and verification requirements in [AGENTS.md](AGENTS.md).

## Development setup

Use Linux and the pinned Rust toolchain.
Install a C++ compiler for bundled DuckDB.

```bash
cargo build --package deadlock-build-sync --features analysis --locked
```

Before opening a pull request, run the complete fast local gate in
[docs/quality-gates.md](docs/quality-gates.md).

Unit tests remain deferred at the user's request.
Verify changes with the documented checks and isolated reference fixtures.

## Pull requests

- Describe the resulting behavior and the reason for each change.
- Retain the Steam data safety rules in [AGENTS.md](AGENTS.md).
- State which checks passed, failed, or did not run.
- Do not include Steam caches, generated artifacts, credentials, or personal
  account data.

## Names and language

Use ASD-STE100 Simplified Technical English for documentation, comments, error messages, commits, and pull request descriptions.
Name each function for its action and the data it processes.
For example, use `select_core_owners` and `classify_item_purpose`.
Use precise module names, such as `inventory_history.rs`.

Update imports, callers, test references, and configuration when you change a name.
Keep CLI commands, external API identifiers, and serialized field names compatible.
