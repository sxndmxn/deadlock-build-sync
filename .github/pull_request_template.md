## Summary

Describe the user-visible result and why it is needed.

## Validation

- [ ] `cargo fmt --all --check`
- [ ] `cargo clippy --workspace --all-targets --all-features --locked -- -D warnings`
- [ ] `cargo run --locked --package deadlock-quality`
- [ ] `uvx --from sqlfluff==4.3.0 sqlfluff lint crates/deadlock-analysis/sql`
- [ ] `cargo doc --workspace --all-features --no-deps --locked`
- [ ] `cargo deny --locked check --deny warnings`
- [ ] Default CLI build and missing-analysis-feature check
- [ ] Release build with analysis enabled
- [ ] Release archive inspection and executable checks outside the checkout
- [ ] Relevant fixture checks and limitations recorded

## Safety

- [ ] Steam-data invariants remain intact or are not affected
- [ ] No credentials, account data, cache contents, or generated artifacts are included
