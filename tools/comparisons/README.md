# Development comparisons

Normal commands use `src/deadlock_build_sync`. This directory contains comparison
runners, PrefixSpan, old clustering and completion methods, and historical reports.
Feature tests also run in the main `tests` suite.

The directory was moved from `experiments` during PR #26. Historical reports are
preserved. Paths inside those reports refer to commit `56debec` and earlier source
revisions. Use the new directory for current runner commands.

Run the discovery, path, and guide comparisons from the repository root:

```bash
uv run pytest tools/comparisons/core_discovery tools/comparisons/identity_paths tools/comparisons/build_guides
```

The QDFM comparison uses a separate environment for its training dependencies:

```bash
uv run --project tools/comparisons/qdfm python -m pytest -p no:tach tools/comparisons/qdfm
```

The old analysis runner is `tools.comparisons.legacy.cli`. These comparison and
training dependencies are not part of rendering or Steam installation.
