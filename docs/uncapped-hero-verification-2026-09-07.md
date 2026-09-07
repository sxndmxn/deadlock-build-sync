# Build coverage without a hero limit: 2026-09-07

Generation produced **761 supported legal builds for all 38 heroes**. There is no fixed build-count limit per hero. Each build is the first usable candidate in its discovery identity group.

Abrams has **21 builds**, including **11 with Arcane Surge** in the exact core. Billy has the most builds: 36.

The release has 5 builds with `outcome_supported` status and 756 with `observed` status. Evidence limits are shown in each guide. These records do not establish a causal win advantage.

All heroes use Emissary I–Eternus V (badges 71–115). No hero needed rank expansion. The previous 112 identities, their purchase paths and pools, and all 38 defaults are unchanged. The previous artifact bundle has the same file hashes.

The fixed source contains 208,681 whole matches, 2,504,172 player appearances, and 43,326,804 purchase rows from DuckLake snapshot 38. The time range is 2026-08-22 21:40:46 UTC through 2026-09-07 00:57:40 UTC. The client version is 6684. Source hashes, mechanics, patch, time boundaries, and ranks match the previous release. The 40,074 reserved test matches were not used for selection or admission. Duplicate match and player keys were both zero.

Evidence ID: `16cc8848ca71543248eda3bc08b4b1c24ba6a7855ba38ae719d7b7927f423b8e`.

The cores contain four to six items: 510 four-item cores, 154 five-item cores, and 97 six-item cores. The lowest support is 117 discovery owners and 100 selection owners. Of the admitted builds, 679 occur after the first three candidates in the selection ranking.

There are 122 builds with uncertain purchase timing and one empty optional pool tier. The legal Queue stays fixed. The empty tier shows that no supported options are available. Complete pools contain 14 to 40 items.

Full export found 17 item-timing buyer counts that did not match the discovery pools. Item metrics included purchases recorded after match end. The shared query now uses the same match-end boundary as discovery, including for purchase-event counts. Strict validation then passed. This change did not alter the frozen identities, ranking, paths, pools, branches, or rank ranges. The failed export preserved the prior bundle.

## Actual build counts

The [complete JSON record](uncapped-hero-admissions-2026-09-07.json) contains every build, exact core, Queue, cost, support count, effective rank range, expansion history, evidence status, evidence limit, and pool count.

| Hero | Builds | Outcome supported | Observed |
| --- | ---: | ---: | ---: |
| Abrams | 21 | 0 | 21 |
| Apollo | 26 | 0 | 26 |
| Bebop | 34 | 0 | 34 |
| Billy | 36 | 0 | 36 |
| Calico | 19 | 0 | 19 |
| Celeste | 13 | 0 | 13 |
| Drifter | 26 | 1 | 25 |
| Dynamo | 27 | 0 | 27 |
| Graves | 11 | 0 | 11 |
| Grey Talon | 28 | 0 | 28 |
| Haze | 28 | 0 | 28 |
| Holliday | 23 | 0 | 23 |
| Infernus | 25 | 0 | 25 |
| Ivy | 20 | 0 | 20 |
| Kelvin | 11 | 0 | 11 |
| Lady Geist | 20 | 0 | 20 |
| Lash | 34 | 1 | 33 |
| McGinnis | 18 | 0 | 18 |
| Mina | 23 | 0 | 23 |
| Mirage | 14 | 0 | 14 |
| Mo & Krill | 25 | 0 | 25 |
| Paige | 23 | 0 | 23 |
| Paradox | 24 | 0 | 24 |
| Pocket | 23 | 0 | 23 |
| Rem | 16 | 0 | 16 |
| Seven | 11 | 0 | 11 |
| Shiv | 29 | 0 | 29 |
| Silver | 6 | 0 | 6 |
| Sinclair | 7 | 0 | 7 |
| The Doorman | 1 | 0 | 1 |
| Venator | 18 | 0 | 18 |
| Victor | 6 | 1 | 5 |
| Vindicta | 20 | 1 | 19 |
| Viscous | 12 | 0 | 12 |
| Vyper | 16 | 0 | 16 |
| Warden | 22 | 1 | 21 |
| Wraith | 31 | 0 | 31 |
| Yamato | 14 | 0 | 14 |

## Abrams builds

D, S, and V are exact-core owner counts in discovery, selection, and validation. All rows use Emissary I–Eternus V.

| Core | Souls | D / S / V | Evidence |
| --- | ---: | --- | --- |
| Melee Charge, Bullet Resist Shredder, Warp Stone, Hunter's Aura | 9,600 | 3169 / 1155 / 1545 | `observed` |
| Arcane Surge, Duration Extender, Healbane, Restorative Locket | 6,400 | 545 / 142 / 208 | `observed` |
| Arcane Surge, Healing Booster, Dispel Magic, Spirit Snatch | 9,600 | 436 / 107 / 120 | `observed` |
| Arcane Surge, Healing Booster, Healbane, Dispel Magic | 8,000 | 582 / 166 / 182 | `observed` |
| Arcane Surge, Healing Booster, Restorative Locket, Healbane | 6,400 | 1067 / 279 / 366 | `observed` |
| Arcane Surge, Healing Booster, Healbane, Superior Duration | 8,000 | 646 / 171 / 201 | `observed` |
| Stalker, Melee Charge, Battle Vest, Hunter's Aura | 8,000 | 2271 / 456 / 612 | `observed` |
| Stalker, Melee Charge, Bullet Resist Shredder, Warp Stone | 8,000 | 4044 / 1481 / 2074 | `observed` |
| Arcane Surge, Duration Extender, Healing Booster, Spirit Snatch | 8,000 | 669 / 171 / 296 | `observed` |
| Stalker, Melee Charge, Battle Vest, Bullet Resist Shredder | 6,400 | 2899 / 572 / 758 | `observed` |
| Arcane Surge, Duration Extender, Healbane, Spirit Snatch | 8,000 | 407 / 114 / 197 | `observed` |
| Arcane Surge, Healing Booster, Dispel Magic, Superior Duration | 9,600 | 392 / 109 / 120 | `observed` |
| Arcane Surge, Duration Extender, Healing Booster, Healbane | 6,400 | 794 / 207 / 313 | `observed` |
| Healing Booster, Restorative Locket, Healbane, Spirit Snatch | 8,000 | 547 / 141 / 208 | `observed` |
| Arcane Surge, Healing Booster, Healbane, Spirit Snatch | 8,000 | 786 / 213 / 322 | `observed` |
| Arcane Surge, Duration Extender, Healing Booster, Dispel Magic | 8,000 | 430 / 105 / 128 | `observed` |
| Stalker, Battle Vest, Bullet Resist Shredder, Hunter's Aura, Warp Stone | 11,200 | 999 / 185 / 234 | `observed` |
| Melee Charge, Bullet Resist Shredder, Warp Stone, Hunter's Aura, Superior Duration | 12,800 | 611 / 137 / 216 | `observed` |
| Stalker, Melee Charge, Battle Vest, Bullet Resist Shredder, Warp Stone | 9,600 | 1344 / 245 / 318 | `observed` |
| Stalker, Melee Charge, Bullet Resist Shredder, Hunter's Aura | 8,000 | 5227 / 1737 / 2399 | `observed` |
| Stalker, Melee Charge, Bullet Resist Shredder, Hunter's Aura, Superior Duration | 11,200 | 898 / 232 / 366 | `observed` |

## Verification

All six mandatory tools passed: Ruff `ALL` and formatting, strict ty with warnings fatal, Complexipy at 21 with ignores disabled, Deptry, exact Tach boundaries with type-only imports, and Vulture at 60%. No quality limit was raised and no suppression was added.

- The complete fast local gate passed: 1,322 tests, with warnings treated as errors. Coverage was 96.86% for statements and 91.57% for branches. The numeric, file-size, duplicate-code, lockfile, and dependency checks passed.
- Ten focused mutations were detected in an isolated checkout copy. The Steam mutation gate passed with cached results: 1,955 killed, 11 timed out, zero survived. The Steam mutation modules are unchanged.
- All 69 comparison tests passed. The branch changes produced identical choices and validation records on a sample from 141,365 real Abrams decision rows.
- CI passed on implementation commit `829dcc84bd62b5cf340535fe6be6893c037cec55`.
- Updated `uv` 0.12.10 passed the lockfile check and built the source distribution and wheel. Both CLI help commands passed outside the checkout. The isolated wheel environment contained runtime dependencies only.
- Normal `build` commands generated all 761 guides in the checkout and again from the wheel outside the checkout. No requested hero was skipped.
- Decoded Steam records matched every Queue action, optional flag, annotation, row description, build description, tag, and complete item pool. Purchase execution confirmed component credits, incremental costs, total costs, inventory, and choice costs.
- Temporary-cache installation created 761 builds. A second installation updated the same 761 builds. The upgrade from the previous release updated 112 builds and added 649, with zero removals.
- The wheel recommendation CLI accepted a real Arcane Surge Abrams state without economy or enemy observations. With Extra Stamina owned and 300 liquid souls, the next Arcane Surge upgrade costs 800 souls, has a 500-soul cash shortfall, and leaves 7,200 souls in the core path. The relative-wealth estimate is unavailable.
- Favorites, saved and selected builds, unrelated private builds, unknown fields, original cache bytes, backups, and restore behavior were preserved.
- The saved selection, identities, ranking, paths, pools, cohorts, and correction family match the final evidence. All builds meet the discovery and selection owner floor and the purchase-order support floor. All reserved-test denominators are zero.

## Execution and local files

The normal discovery code completed all 38 heroes and saved the full family before validation: 761 core hypotheses and 165,953 branch hypotheses. After an interruption, validation resumed from that file with the existing validator. Six hero workers saved completed results. One additional worker later processed the remaining Lash checks from the end of its fixed list. It used the same validator and shared result cache. Only the main worker exported the original frozen order. Source reads were serialized to control memory. No production parallel framework was added. Validation did not restart selection.

The current evidence schema is 11, the guide schema is 3, and the selection method is `eclat-leiden-pairwise-v2`. A real build attempt with the old capped method failed with a clear refresh instruction and preserved the previous bundle.

The artifact bundle is in `generated/uncapped-hero-coverage/artifacts`. The frozen source run is `full-hero-coverage-20260906`. The isolated wheel, decoded-output checks, temporary caches, and backups are in:

`/var/folders/jt/s88jx1px65n165_bhj0550cw0000gn/T/deadlock-uncapped-wheel-_tbj31_f`

The temporary-cache check ran on macOS. Only the Linux `/proc` process guard was simulated for these temporary caches. **No live Steam sync was run.**

Commands used after the fixed-source validation export:

```bash
uv run --locked build --artifacts generated/uncapped-hero-coverage/artifacts --format json
uv build
# In the isolated wheel environment, outside the checkout:
build --artifacts artifacts --format json
python verify_wheel.py
```

The previous capped report remains in [full-hero-verification-2026-09-07.md](full-hero-verification-2026-09-07.md).
