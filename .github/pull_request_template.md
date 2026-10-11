## Summary

Describe the user-visible result and why it is needed.

## Validation

Run `bash scripts/check_repository.sh`.
This command includes Rust code metrics and isolated safety checks.
Run `bash scripts/check_repository.sh --release` for release or packaging changes.
State which checks passed, failed, or did not run.
Record fixture limitations.

## Safety

Confirm that the change preserves the Steam data safety rules.
Exclude credentials, account data, cache contents, and generated artifacts.
