# Contributing

Follow the language, naming, safety, and verification requirements in [AGENTS.md](AGENTS.md).

## Development setup

Use Linux, Python 3.12 or newer, and `uv` 0.12.x:

```bash
uv sync --frozen
```

Before opening a pull request, run the complete fast local gate in
[docs/quality-gates.md](docs/quality-gates.md).

Add a regression test for correctness or safety fixes.

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
Use `make_` and the record name for shared test data constructors.
Use precise module names, such as `inventory_reconstruction.py`.

Update imports, callers, test references, and configuration when you change a name.
Keep CLI commands, external API identifiers, and serialized field names compatible.
