## Summary

Describe the user-visible result and why it is needed.

## Validation

- [ ] `uv lock --check`
- [ ] `uv run ruff format --check .`
- [ ] `uv run ruff check .`
- [ ] `uv run ty check`
- [ ] `uv run pytest`
- [ ] `uv pip check`
- [ ] `uv build`
- [ ] Relevant DeepEval suite run, or the reason it was skipped is documented

## Safety

- [ ] Steam-data invariants remain intact or are not affected
- [ ] No credentials, account data, cache contents, or generated artifacts are included
