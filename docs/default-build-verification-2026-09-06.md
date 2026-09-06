# Integration verification: 2026-09-06

The fresh cohort contains 78,573 whole matches, 942,876 player appearances, and
15,979,002 purchase rows. The source cutoff is 2026-09-06 21:19:47 UTC.
The cohort starts with the August 22 patch. Client version: 6684.
The producer requested all 38 current heroes. Six identities passed across four
heroes. The 34 other heroes have evidence exclusions. No automatic branch passed.
The reserved test split was not used.

Evidence ID: `daacd0dfe2b5853e2089ba8ee4b21bd40fd5a0de65aff488e4449a4dd7ef72ba`.

| Hero | Frozen rank | Core | Selection owners | Validation owners | Pool counts, tiers 1–4 |
| --- | ---: | --- | ---: | ---: | --- |
| Haze | 0 | Veil Walker, Surge of Power, Burst Fire, Bullet Resist Shredder, Enchanter's Emblem, Swift Striker | 258 | 288 | 4, 6, 5, 10 |
| Haze | 1 | Veil Walker, Surge of Power, Burst Fire, Enchanter's Emblem, Swift Striker | 388 | 416 | 7, 9, 6, 10 |
| Haze | 2 | Veil Walker, Surge of Power, Bullet Resist Shredder, Enchanter's Emblem, Swift Striker | 329 | 373 | 8, 7, 7, 10 |
| Shiv | 1 | Compress Cooldown, Torment Pulse, Healbane, Radiant Regeneration | 349 | 458 | 10, 10, 10, 10 |
| Lash | 0 | Quicksilver Reload, Siphon Bullets, Recharging Rush, Headhunter | 557 | 751 | 10, 10, 10, 10 |
| Victor | 0 | Torment Pulse, Infuser, Enduring Speed, Healing Booster | 1193 | 1514 | 10, 10, 10, 10 |

Haze rank 0 is its default. Shiv rank 1 is its default because rank 0 failed
admission. Lash and Victor use rank 0. Core validation used 39 frozen hypotheses.
All pool options remain available as manual choices.

The [machine-readable admission report](default-build-admissions-2026-09-06.json)
contains each path ID, the validation win rate, exact fold counts for excluded
heroes, and all recorded exclusion reasons. Win rates are descriptive associations.

| Excluded hero | Candidates | Recorded reasons |
| --- | ---: | --- |
| Infernus | 150 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; observed win rate below 52%; win lower bound does not exceed 50% |
| Seven | 150 | Core order conflicts with observed component wealth windows; No shared documented kit channel supported by two core items; adjusted evidence fails family correction; win evidence fails family correction |
| Vindicta | 150 | Core order conflicts with observed component wealth windows; adjusted evidence fails family correction; win evidence fails family correction |
| Lady Geist | 150 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; observed win rate below 52%; win lower bound does not exceed 50% |
| Abrams | 121 | adjusted evidence fails family correction |
| Wraith | 150 | Frozen order lacks discovery, selection, or validation support; No shared documented kit channel supported by two core items; adjusted evidence fails family correction; win evidence fails family correction |
| McGinnis | 130 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; observed win rate below 52%; win lower bound does not exceed 50% |
| Paradox | 122 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; observed win rate below 52%; win lower bound does not exceed 50% |
| Dynamo | 96 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; observed win rate below 52%; win lower bound does not exceed 50% |
| Kelvin | 125 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; joint ownership lift below 1.1; observed win rate below 52%; win lower bound does not exceed 50% |
| Holliday | 123 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; joint ownership lift below 1.1; observed win rate below 52%; win lower bound does not exceed 50% |
| Bebop | 150 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; observed win rate below 52%; win lower bound does not exceed 50% |
| Calico | 150 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; observed win rate below 52%; win lower bound does not exceed 50% |
| Grey Talon | 138 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; joint ownership lift below 1.1; observed win rate below 52%; win lower bound does not exceed 50% |
| Mo & Krill | 150 | No shared documented kit channel supported by two core items; adjusted evidence fails family correction |
| Ivy | 114 | No shared documented kit channel supported by two core items; adjusted evidence fails family correction; observed win rate below 52%; win evidence fails family correction |
| Warden | 150 | Core order conflicts with observed component wealth windows; Frozen order lacks discovery, selection, or validation support; No shared documented kit channel supported by two core items |
| Yamato | 150 | No shared documented kit channel supported by two core items; adjusted evidence fails family correction; insufficient comparable-state overlap; win evidence fails family correction |
| Viscous | 112 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; observed win rate below 52%; win lower bound does not exceed 50% |
| Pocket | 150 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; observed win rate below 52%; win lower bound does not exceed 50% |
| Mirage | 150 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; joint ownership lift below 1.1; observed win rate below 52%; win lower bound does not exceed 50% |
| Vyper | 121 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; observed win rate below 52%; win lower bound does not exceed 50% |
| Sinclair | 52 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; joint ownership lift below 1.1; observed win rate below 52%; win lower bound does not exceed 50% |
| Mina | 132 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; joint ownership lift below 1.1; observed win rate below 52%; win lower bound does not exceed 50% |
| Drifter | 150 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; observed win rate below 52%; win lower bound does not exceed 50% |
| Venator | 150 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; observed win rate below 52%; win lower bound does not exceed 50% |
| Paige | 82 | Core order conflicts with observed component wealth windows; No shared documented kit channel supported by two core items; adjusted evidence fails family correction; insufficient comparable-state overlap; win evidence fails family correction |
| The Doorman | 70 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; observed win rate below 52%; win lower bound does not exceed 50% |
| Billy | 150 | adjusted evidence fails family correction; observed win rate below 52%; win evidence fails family correction |
| Graves | 136 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; observed win rate below 52%; win lower bound does not exceed 50% |
| Apollo | 111 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; joint ownership lift below 1.1; observed win rate below 52%; win lower bound does not exceed 50% |
| Rem | 87 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; joint ownership lift below 1.1; observed win rate below 52%; win lower bound does not exceed 50% |
| Silver | 78 | adjusted lower bound does not exceed zero; fewer than 100 core owners; insufficient comparable-state overlap; joint ownership lift below 1.1; observed win rate below 52%; win lower bound does not exceed 50% |
| Celeste | 121 | Core order conflicts with observed component wealth windows; adjusted evidence fails family correction; win evidence fails family correction |

## Checks

All checks in `docs/quality-gates.md` passed: frozen lock and environment checks,
Ruff format and lint, Ty, Deptry, Tach, Complexipy, coverage, the numeric quality
gate, Vulture, Pylint duplicate-code checks, dependency checks, and wheel build.

- Main suite: 1,253 passed with warnings treated as errors.
- Coverage: 96.80% statements and 91.43% branches.
- Development comparisons: 69 discovery/path/guide tests and 28 QDFM tests passed.
- Steam boundary mutation check: 1,955 killed, 11 timed out, zero survived.
  The repository mutation gate passed for all 1,966 mutations.
- Fresh `uv run build --artifacts generated/default-integration-final/artifacts
  --format json` generated six complete guides. All six passed artifact loading
  and canonical reconstruction.
- An isolated wheel environment outside the checkout rebuilt the same six guides
  and ran `recommend` in JSON and Markdown. It had no analysis or training packages,
  no `experiments` directory, and no comparison tools.
- Decoded Steam records matched all six validated Queue paths. Every pool item
  remained in optional rows. The six builds contained 25 to 40 pool items each.
- Temporary-cache installation created six builds, then updated the same six on
  the next run. It preserved an existing managed build for an excluded hero,
  favorites, selected builds, saved data, unrelated private builds, and unknown
  user data. Backup and restore checks passed.

The [wheel verification record](default-build-wheel-verification-2026-09-06.json)
contains Queue lengths, pool counts, row counts, and the wheel digest. The cache
check used temporary files on macOS. Only the Linux `/proc` process check was
simulated. The normal unit suite also tests the process guard. No live Steam sync
was run.

The source extraction is in the local state run
`default-integration-20260906`. Frozen nominations were saved before validation.
The fresh review bundle is in
`generated/default-integration-final/artifacts`. Large source data, generated
artifacts, and local cache backups are not committed.

Fresh data exposed shared-component ordering, JSON key-order, and UTF-8 splitting
errors during integration. Regression tests cover those cases. Other regression
cases cover weak evidence, missing hero dispositions, combined optional choices,
owned upgrades, component rebuys, wealth boundaries, stale and future observations,
enemy conditions, separate core substitution evidence, and old artifact rejection.
