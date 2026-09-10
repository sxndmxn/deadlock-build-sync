# Archived development comparisons

Comparison runners, historical reports, and their tests remain in Git at
[`80b9afc`](https://github.com/sxndmxn/deadlock-build-sync/tree/80b9afcc8a94831b5fbae5a2a291ec4127e241c7/tools/comparisons).
The current application uses `src/deadlock_build_sync`. Tests for shared production
functions remain in the current test suite and import those functions directly.

Use a separate checkout to inspect or run the archived code:

```bash
git worktree add --detach ../deadlock-build-sync-comparisons 80b9afcc8a94831b5fbae5a2a291ec4127e241c7
```

In that checkout, follow its dependency manifests and test commands. The archived
revision passed 69 discovery, path, and guide comparison tests and 28 QDFM tests.
Its identity-path `run` and `synthetic` adapters have missing imports. The original
experiment sources and report paths are available at `56debec` and earlier
revisions. The archive preserves that state; it does not certify every old runner.
