## Summary

Describe the user-visible result and why it is needed.

## Validation

- [ ] `uv lock --check`
- [ ] `uv run ruff format --check .`
- [ ] `uv run ruff check .`
- [ ] `uv run sqlfluff lint .`
- [ ] `uv run ty check`
- [ ] `uv run deptry .`
- [ ] `uv run tach check`
- [ ] `uv run coverage run -m pytest -W error && uv run coverage json`
- [ ] `uv run complexipy && uv run tools/quality_gate.py`
- [ ] `uv run vulture`
- [ ] `uv run pylint --disable=all --enable=duplicate-code src scripts`
- [ ] `uv pip check`
- [ ] `uv build`
- [ ] Mutation gate passed, or the reason it was not run is documented
- [ ] Relevant DeepEval suite run, or the reason it was skipped is documented

## Safety

- [ ] Steam-data invariants remain intact or are not affected
- [ ] No credentials, account data, cache contents, or generated artifacts are included
