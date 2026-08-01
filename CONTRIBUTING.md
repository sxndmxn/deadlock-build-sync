# Contributing

Thanks for helping improve `deadlock-build-sync`.

## Development setup

Use Linux, Python 3.12 or newer, and `uv` 0.12.x:

```bash
uv sync --frozen
```

Before opening a pull request, run the complete local gate:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv pip check
uv build
```

Add a regression test for correctness or safety fixes. Prompt or validator
changes should also run the relevant DeepEval suite when Codex credentials and
fresh evaluation context are available.

## Pull requests

- Keep changes focused and explain their user-visible effect.
- Preserve the Steam-data safety invariants in [AGENTS.md](AGENTS.md).
- Document checks that were run and any model-backed evaluation that was
  intentionally skipped.
- Do not include Steam caches, generated artifacts, credentials, or personal
  account data.
