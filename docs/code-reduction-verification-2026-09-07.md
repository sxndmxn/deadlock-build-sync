# Code reduction verification: 7 September 2026

The cleanup started from a clean `feat/build-purchase-guidance` branch at
`80b9afcc8a94831b5fbae5a2a291ec4127e241c7`. The local backup branch is
`backup/pr26-before-lean-20260907`. The cleanup is one commit, so one revert can
restore the source and lockfile.

| Python files | Before | After | Lines removed |
| --- | ---: | ---: | ---: |
| Application: `src/` and `scripts/` | 28,918 | 28,243 | 675 |
| Root tests | 27,159 | 22,773 | 4,386 |
| Comparison tools and their tests | 16,979 | 0 | 16,979 |
| Total | 73,056 | 51,016 | 22,040 |

These are physical lines, including comments and blank lines. The application
reduction removes obsolete reconstruction helpers, unused producer inputs,
experimental PrefixSpan code, duplicate write code, and a repeated effect rule.
Hero collection now returns its inputs directly. Public result fields stay the
same. The current recommendation API remains in place.

Comparison code and its historical tests remain at the starting revision. See
[the archive instructions](../tools/comparisons/README.md). Tests for shared
production functions now import their current owners. Artifact checks use the
current bundle loader. The public category description contract and frozen
cohort metadata also retain regression coverage.

The cleanup keeps the current discovery limits, admission rules, data splits,
schemas, commands, and output formats. It does not apply the separate behavior
changes proposed in the PR audit. Artifact data and the Steam write modules are
unchanged. The producer still uses the same sorted JSON serialization, temporary
replacement, file flush, and directory flush through the shared byte writer.

Verification completed:

- The complete fast local gate passed, including 1,214 tests with warnings
  treated as errors. No check, threshold, or exclusion was relaxed.
- Statement coverage is 96.84%; branch coverage is 91.57%. A comparison against
  the original coverage found no lost statement coverage in unchanged functions.
- The normal fixture build matches the original eight output files. Its clock
  is fixed, and its temporary directory path is normalized before comparison.
  The existing producer document fingerprint also remains unchanged.
- A runtime-only wheel installed outside the checkout loaded the saved full
  bundle. All 140 guides, 38 heroes, and 761 variants were retained. Complete
  guide records, regular and detailed Markdown, and encoded Steam bytes matched
  the original wheel. Both installed CLI help commands passed outside the checkout.
- The wheel contains 160 entries and is 317,148 bytes. It contains no comparison
  tools. The lockfile removes seven unused plotting packages. Retained package
  versions did not change.

The full statistical fit and mutation suite were not rerun. No live Steam sync
was run. The full-bundle comparison used the saved evidence and did not fetch new
analytics. It verifies output compatibility for those inputs.
