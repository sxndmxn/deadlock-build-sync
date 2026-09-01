# Contributing

Thanks for helping improve `deadlock-build-sync`.

## Development setup

Use Linux, Python 3.12 or newer, and `uv` 0.12.x:

```bash
uv sync --frozen
```

Before opening a pull request, run the complete fast local gate in
[docs/quality-gates.md](docs/quality-gates.md).

Add a regression test for correctness or safety fixes.

## Pull requests

- Keep changes focused and explain their user-visible effect.
- Preserve the Steam-data safety invariants in [AGENTS.md](AGENTS.md).
- Document the checks that were run.
- Do not include Steam caches, generated artifacts, credentials, or personal
  account data.
