# Full hero verification: 2026-09-07

Fresh generation produced 112 supported legal builds for all 38 current heroes.
Viscous has three builds. The Doorman has one. All other heroes have three.
All heroes stopped at Emissary I–Eternus V (badges 71–115); no hero needed a lower
rank cutoff. The Doorman did not expand to seek more identities.

Four builds have `outcome_supported` status. The other 108 have `observed` status
with explicit evidence limits. This is observational evidence, not a causal
win advantage. No automatic branch passed the strict corrected checks. All
supported pool choices remain available for manual selection.

The fixed source contains 208,681 whole matches, 2,504,172 player appearances,
and 43,326,804 purchase rows from DuckLake snapshot 38. The requested time range
is 2026-08-22 21:40:46 UTC through 2026-09-07 00:57:40 UTC. Client version: 6684.
Extraction includes ranked badges 11–115. Each hero used only its effective
range. Time boundaries were fixed from the starting range before discovery.
The reserved test split was outside selection, expansion, and admission.

Evidence ID: `8463401c08a1bdc97009000e7263b0066585ac21102e255f416df18bb9978ad8`.

The cores contain four to six items in this dataset: 79 four-item, 17 five-item,
and 16 six-item builds. The three-item fallback is covered by regression tests.
Thirty admitted builds occur after the first three candidates in the selection
ranking. Twenty-one builds have uncertain timing. Pool counts range from 21 to
40 items per build. Empty optional tiers are covered by regression tests.

The earlier Viscous 76.6% overlap case is a regression fixture. On this fresh
source, its first selection candidate has 77.8% overlap and remains available.
Its other two builds have negative adjusted selection lower bounds and also
remain available. Validation never starts a new candidate search.

## Actual builds

All rows use Emissary I–Eternus V. D, S, and V are exact core owner counts in
discovery, selection, and validation. The full
[machine-readable record](full-hero-admissions-2026-09-07.json) includes every
path ID, core, Queue, cost, pool count, effective range, expansion history,
evidence status, and evidence limit.

| Hero | Core | D / S / V | Evidence |
| --- | --- | --- | --- |
| Infernus | Swift Striker, Titanic Magazine, Spirit Lifesteal, Mystic Vulnerability, Toxic Bullets, Superior Duration | 755 / 240 / 324 | `observed` |
| Infernus | Swift Striker, Spirit Lifesteal, Mystic Vulnerability, Toxic Bullets | 2507 / 861 / 1204 | `observed` |
| Infernus | Improved Spirit, Swift Striker, Spirit Lifesteal, Mystic Vulnerability | 3935 / 1324 / 1839 | `observed` |
| Seven | Arcane Surge, Cultist Sacrifice, Spirit Shredder Bullets, Spirit Shielding, Bullet Resist Shredder, Superior Duration | 467 / 162 / 217 | `observed` |
| Seven | Cultist Sacrifice, Spirit Shredder Bullets, Healbane, Spirit Shielding, Spirit Lifesteal, Superior Duration | 635 / 240 / 293 | `observed` |
| Seven | Cultist Sacrifice, Spirit Shielding, Mystic Vulnerability, Bullet Resist Shredder | 863 / 290 / 354 | `observed` |
| Vindicta | Opening Rounds, Quicksilver Reload, Rapid Recharge, Long Range, Swift Striker, Burst Fire | 726 / 274 / 304 | `observed` |
| Vindicta | Opening Rounds, Quicksilver Reload, Long Range, Swift Striker, Counterspell, Burst Fire | 473 / 174 / 184 | `observed` |
| Vindicta | Opening Rounds, Rapid Recharge, Long Range, Swift Striker, Counterspell, Burst Fire | 620 / 220 / 259 | `observed` |
| Lady Geist | Kinetic Dash, Berserker, Healing Booster, Spirit Resilience | 985 / 292 / 310 | `observed` |
| Lady Geist | Radiant Regeneration, Kinetic Dash, Berserker, Spirit Resilience | 1317 / 392 / 422 | `observed` |
| Lady Geist | Cultist Sacrifice, Kinetic Dash, Healing Booster, Berserker | 1011 / 259 / 309 | `observed` |
| Abrams | Stalker, Melee Charge, Bullet Resist Shredder, Hunter's Aura, Superior Duration | 898 / 232 / 366 | `observed` |
| Abrams | Melee Charge, Bullet Resist Shredder, Warp Stone, Hunter's Aura | 3169 / 1155 / 1545 | `observed` |
| Abrams | Stalker, Melee Charge, Bullet Resist Shredder, Warp Stone | 4044 / 1481 / 2074 | `observed` |
| Wraith | Tesla Bullets, Swift Striker, Surge of Power, Enchanter's Emblem | 2165 / 818 / 1116 | `observed` |
| Wraith | Bullet Resist Shredder, Swift Striker, Spirit Lifesteal, Dispel Magic | 1000 / 343 / 422 | `observed` |
| Wraith | Quicksilver Reload, Bullet Resist Shredder, Swift Striker, Spirit Lifesteal, Dispel Magic, Healing Booster | 593 / 199 / 263 | `observed` |
| McGinnis | Heroic Aura, Enchanter's Emblem, Healbane, Suppressor | 466 / 140 / 192 | `observed` |
| McGinnis | Intensifying Magazine, Heroic Aura, Healbane, Suppressor | 649 / 184 / 286 | `observed` |
| McGinnis | Intensifying Magazine, Heroic Aura, Enchanter's Emblem, Healbane | 647 / 166 / 243 | `observed` |
| Paradox | Mystic Shot, Sharpshooter, Trophy Collector, Tankbuster, Veil Walker | 1648 / 512 / 682 | `observed` |
| Paradox | Mystic Shot, Sharpshooter, Trophy Collector, Tankbuster | 3237 / 908 / 1195 | `observed` |
| Paradox | Mystic Shot, Sharpshooter, Tankbuster, Express Shot | 1719 / 523 / 655 | `observed` |
| Dynamo | Arcane Surge, Trophy Collector, Compress Cooldown, Warp Stone | 793 / 196 / 302 | `observed` |
| Dynamo | Arcane Surge, Rapid Recharge, Headhunter, Recharging Rush | 1012 / 293 / 375 | `observed` |
| Dynamo | Headhunter, Recharging Rush, Enchanter's Emblem, Rapid Recharge | 633 / 196 / 238 | `observed` |
| Kelvin | Healing Booster, Healbane, Improved Spirit, Mystic Vulnerability | 636 / 259 / 282 | `observed` |
| Kelvin | Torment Pulse, Healing Booster, Enduring Speed, Healbane | 622 / 211 / 232 | `observed` |
| Kelvin | Torment Pulse, Healing Booster, Enduring Speed, Rapid Recharge | 496 / 177 / 191 | `observed` |
| Haze | Swift Striker, Bullet Resist Shredder, Surge of Power, Enchanter's Emblem, Veil Walker, Burst Fire | 766 / 257 / 285 | `observed` |
| Haze | Swift Striker, Surge of Power, Enchanter's Emblem, Veil Walker, Burst Fire | 1180 / 391 / 417 | `observed` |
| Haze | Swift Striker, Bullet Resist Shredder, Surge of Power, Enchanter's Emblem, Veil Walker | 1010 / 328 / 372 | `observed` |
| Holliday | Improved Spirit, Mystic Shot, Rapid Recharge, Recharging Rush, Stamina Mastery | 1023 / 334 / 426 | `observed` |
| Holliday | Rapid Recharge, Trophy Collector, Recharging Rush, Stamina Mastery | 1497 / 562 / 710 | `observed` |
| Holliday | Improved Spirit, Mystic Shot, Rapid Recharge, Trophy Collector, Recharging Rush, Stamina Mastery | 624 / 200 / 259 | `observed` |
| Bebop | Headhunter, Veil Walker, Spirit Snatch, Enduring Speed, Fleetfoot | 580 / 163 / 201 | `observed` |
| Bebop | Headhunter, Spirit Snatch, Enduring Speed, Fleetfoot | 937 / 265 / 337 | `observed` |
| Bebop | Stalker, Headhunter, Veil Walker, Slowing Hex, Spirit Snatch | 951 / 472 / 594 | `observed` |
| Calico | Stalker, Trophy Collector, Mystic Shot, Spirit Shredder Bullets, Arctic Blast | 594 / 159 / 198 | `observed` |
| Calico | Stalker, Spirit Snatch, Spirit Shredder Bullets, Mystic Vulnerability, Dispel Magic | 605 / 195 / 241 | `observed` |
| Calico | Stalker, Cold Front, Spirit Snatch, Dispel Magic | 3506 / 1275 / 1626 | `observed` |
| Grey Talon | Opening Rounds, Swift Striker, Battle Vest, Sharpshooter | 496 / 168 / 209 | `observed` |
| Grey Talon | Opening Rounds, Enchanter's Emblem, Compress Cooldown, Recharging Rush | 694 / 251 / 322 | `observed` |
| Grey Talon | Mystic Shot, Rapid Recharge, Compress Cooldown, Improved Spirit | 643 / 177 / 253 | `observed` |
| Mo & Krill | Trophy Collector, Cold Front, Torment Pulse, Healbane, Improved Spirit, Tankbuster | 484 / 182 / 224 | `observed` |
| Mo & Krill | Trophy Collector, Veil Walker, Improved Spirit, Tankbuster | 1009 / 376 / 473 | `observed` |
| Mo & Krill | Trophy Collector, Cold Front, Improved Spirit, Tankbuster | 1451 / 509 / 636 | `observed` |
| Shiv | Restorative Locket, Healbane, Healing Booster, Radiant Regeneration, Torment Pulse, Dispel Magic | 565 / 188 / 273 | `observed` |
| Shiv | Radiant Regeneration, Healbane, Restorative Locket, Torment Pulse, Compress Cooldown | 608 / 188 / 236 | `observed` |
| Shiv | Radiant Regeneration, Healbane, Torment Pulse, Compress Cooldown | 1119 / 361 / 457 | `outcome_supported` |
| Ivy | Titanic Magazine, Tesla Bullets, Fleetfoot, Quicksilver Reload | 440 / 133 / 146 | `observed` |
| Ivy | Titanic Magazine, Healbane, Fleetfoot, Spirit Lifesteal | 625 / 192 / 206 | `observed` |
| Ivy | Titanic Magazine, Healbane, Fleetfoot, Quicksilver Reload | 984 / 284 / 313 | `observed` |
| Warden | Titanic Magazine, Swift Striker, Fleetfoot, Mercurial Magnum | 1304 / 1809 / 2929 | `observed` |
| Warden | Opening Rounds, Titanic Magazine, Swift Striker, Veil Walker, Fleetfoot, Mercurial Magnum | 830 / 1357 / 2196 | `outcome_supported` |
| Warden | Swift Striker, Titanic Magazine, Veil Walker, Enduring Speed, Fleetfoot, Mercurial Magnum | 440 / 868 / 1478 | `observed` |
| Yamato | Mystic Shot, Stalker, Recharging Rush, Healbane | 1730 / 466 / 466 | `observed` |
| Yamato | Mystic Shot, Improved Spirit, Spirit Snatch, Restorative Locket, Healbane, Hunter's Aura | 873 / 283 / 422 | `observed` |
| Yamato | Stalker, Recharging Rush, Restorative Locket, Spirit Snatch | 1260 / 336 / 292 | `observed` |
| Lash | Quicksilver Reload, Headhunter, Recharging Rush, Siphon Bullets | 1567 / 556 / 771 | `outcome_supported` |
| Lash | Quicksilver Reload, Improved Spirit, Majestic Leap, Mystic Shot, Headhunter | 578 / 193 / 244 | `observed` |
| Lash | Quicksilver Reload, Headhunter, Recharging Rush, Restorative Locket | 5304 / 1697 / 2321 | `observed` |
| Viscous | Express Shot, Mystic Shot, Veil Walker, Spirit Snatch | 679 / 243 / 348 | `observed` |
| Viscous | Melee Charge, Spirit Snatch, Lifestrike, Ballistic Enchantment | 417 / 160 / 143 | `observed` |
| Viscous | Mystic Shot, Express Shot, Veil Walker, Tankbuster | 1416 / 511 / 686 | `observed` |
| Pocket | Cold Front, Enchanter's Emblem, Majestic Leap, Mystic Shot | 1669 / 607 / 842 | `observed` |
| Pocket | Cold Front, Mystic Vulnerability, Enchanter's Emblem, Improved Spirit | 1253 / 492 / 705 | `observed` |
| Pocket | Cold Front, Cultist Sacrifice, Enchanter's Emblem, Mystic Shot | 1510 / 553 / 772 | `observed` |
| Mirage | Suppressor, Healbane, Headhunter, Recharging Rush | 1772 / 283 / 254 | `observed` |
| Mirage | Recharging Rush, Compress Cooldown, Mystic Vulnerability, Dispel Magic | 1299 / 275 / 275 | `observed` |
| Mirage | Suppressor, Healbane, Headhunter, Recharging Rush, Mystic Vulnerability | 1382 / 215 / 212 | `observed` |
| Vyper | Improved Spirit, Quicksilver Reload, Bullet Resist Shredder, Tesla Bullets | 660 / 187 / 217 | `observed` |
| Vyper | Improved Spirit, Quicksilver Reload, Bullet Resist Shredder, Burst Fire | 568 / 169 / 184 | `observed` |
| Vyper | Split Shot, Burst Fire, Swift Striker, Spirit Shielding | 662 / 249 / 433 | `observed` |
| Sinclair | Improved Spirit, Rapid Recharge, Trophy Collector, Veil Walker | 724 / 268 / 334 | `observed` |
| Sinclair | Improved Spirit, Rapid Recharge, Enchanter's Emblem, Veil Walker | 1224 / 480 / 631 | `observed` |
| Sinclair | Opening Rounds, Improved Spirit, Rapid Recharge, Veil Walker | 1076 / 430 / 599 | `observed` |
| Mina | Improved Spirit, Dispel Magic, Reactive Barrier, Swift Striker, Tankbuster, Stamina Mastery | 457 / 195 / 279 | `observed` |
| Mina | Quicksilver Reload, Improved Spirit, Reactive Barrier, Tankbuster | 2381 / 735 / 1061 | `observed` |
| Mina | Quicksilver Reload, Improved Spirit, Dispel Magic, Reactive Barrier, Swift Striker | 997 / 430 / 647 | `observed` |
| Drifter | Stalker, Kinetic Dash, Fleetfoot, Fortitude, Hunter's Aura | 610 / 131 / 200 | `observed` |
| Drifter | Kinetic Dash, Fleetfoot, Enduring Speed, Fortitude | 799 / 237 / 380 | `observed` |
| Drifter | Stalker, Kinetic Dash, Enduring Speed, Fortitude | 1032 / 310 / 462 | `observed` |
| Venator | Intensifying Magazine, Weakening Headshot, Swift Striker, Fleetfoot | 1039 / 480 / 499 | `observed` |
| Venator | Intensifying Magazine, Weakening Headshot, Bullet Lifesteal, Fleetfoot | 2861 / 910 / 1255 | `observed` |
| Venator | Battle Vest, Intensifying Magazine, Bullet Lifesteal, Fleetfoot | 3851 / 947 / 1343 | `observed` |
| Victor | Torment Pulse, Enduring Speed, Healing Booster, Infuser | 3548 / 1200 / 1518 | `outcome_supported` |
| Victor | Improved Spirit, Torment Pulse, Enduring Speed, Healing Booster | 5213 / 1720 / 2193 | `observed` |
| Victor | Torment Pulse, Enduring Speed, Healing Booster, Mystic Vulnerability, Infuser | 2580 / 873 / 1075 | `observed` |
| Paige | Trophy Collector, Guardian Ward, Vortex Web, Healbane | 297 / 119 / 107 | `observed` |
| Paige | Opening Rounds, Trophy Collector, Guardian Ward, Vortex Web | 549 / 200 / 232 | `observed` |
| Paige | Opening Rounds, Trophy Collector, Guardian Ward, Knockdown | 1660 / 511 / 730 | `observed` |
| The Doorman | Trophy Collector, Rapid Recharge, Improved Spirit, Tankbuster | 428 / 132 / 217 | `observed` |
| Billy | Stalker, Cultist Sacrifice, Battle Vest, Enchanter's Emblem, Spirit Snatch, Point Blank | 549 / 167 / 190 | `observed` |
| Billy | Cultist Sacrifice, Enchanter's Emblem, Bullet Resist Shredder, Spirit Snatch | 1657 / 474 / 562 | `observed` |
| Billy | Cultist Sacrifice, Battle Vest, Bullet Resist Shredder, Spirit Snatch | 1868 / 530 / 612 | `observed` |
| Graves | Improved Spirit, Mystic Shot, Arcane Surge, Healbane | 618 / 139 / 156 | `observed` |
| Graves | Mystic Shot, Arcane Surge, Healbane, Heroic Aura | 634 / 150 / 172 | `observed` |
| Graves | Mystic Shot, Improved Spirit, Arcane Surge, Heroic Aura | 1302 / 291 / 434 | `observed` |
| Apollo | Cold Front, Improved Spirit, Healing Booster, Dispel Magic | 574 / 153 / 183 | `observed` |
| Apollo | Improved Spirit, Cold Front, Healing Booster, Healbane | 1228 / 302 / 491 | `observed` |
| Apollo | Improved Spirit, Cold Front, Restorative Locket, Healbane | 900 / 220 / 378 | `observed` |
| Rem | Trophy Collector, Improved Spirit, Rapid Recharge, Tankbuster | 550 / 140 / 232 | `observed` |
| Rem | Trophy Collector, Arcane Surge, Decay, Healing Booster | 517 / 247 / 269 | `observed` |
| Rem | Opening Rounds, Trophy Collector, Arcane Surge, Healing Booster | 1038 / 437 / 583 | `observed` |
| Silver | Stalker, Battle Vest, Hunter's Aura, Slowing Hex | 555 / 137 / 125 | `observed` |
| Silver | Stalker, Battle Vest, Hunter's Aura, Spirit Shielding | 590 / 145 / 146 | `observed` |
| Silver | Stalker, Restorative Locket, Hunter's Aura, Slowing Hex | 579 / 165 / 150 | `observed` |
| Celeste | Radiant Regeneration, Suppressor, Healing Booster, Torment Pulse, Greater Expansion | 1300 / 544 / 580 | `observed` |
| Celeste | Radiant Regeneration, Healing Booster, Torment Pulse, Greater Expansion | 2067 / 872 / 951 | `observed` |
| Celeste | Radiant Regeneration, Suppressor, Spirit Shielding, Torment Pulse, Greater Expansion | 920 / 413 / 404 | `observed` |

## Checks

All six mandatory tools passed: Ruff with `ALL` and formatting, ty with all rules
as errors and warnings fatal, Complexipy at 21 with ignores disabled, Deptry,
Tach with exact boundaries and type-only imports, and Vulture at 60% confidence.
Broad Ruff exceptions were narrowed. Obsolete Vulture ignores were removed.
No limit was raised and no new suppression was added.

- Main suite: 1,313 tests passed with warnings treated as errors.
- Coverage: 96.83% statements and 91.43% branches. The numeric quality gate passed,
  including file size, both complexity limits, difficulty, CRAP, and type names.
- Pylint reported no duplicate code in source and scripts.
- Comparison tests: 69 discovery/path/guide tests and 28 QDFM tests passed.
- Steam mutation gate: 1,955 killed, 11 timed out, zero survived. All 1,966
  mutations were detected under the existing gate.
- Lockfile, frozen environment, runtime dependency checks, source distribution,
  and wheel build passed.
- The wheel generated all 112 builds outside the checkout using runtime
  dependencies only. CLI help, artifact reconstruction, and Viscous recommendations
  in JSON and Markdown passed. The 800-soul cash shortfall was correct. Analysis,
  training, and comparison packages were absent from that environment.
- Decoded Steam records matched every Queue action, optional flag, item annotation,
  row description, build description, and full pool. Costs were checked again by
  applying purchases to the mechanics inventory, including component credits.
- Temporary-cache installation created 112 builds, then updated the same 112.
  It preserved favorites, saved and selected builds, unrelated private data, and
  unknown fields. The original backup and restore checks passed.

Regression tests cover Viscous overlap, negative and absent estimates, missing
validation, missing optional state, empty pools, uncertain timing, alternate
orders, failed early candidates, three-item seeds, rank boundaries, stable splits,
duplicate prevention, unchanged heroes, rank exhaustion, effective ranges in
consumers, frozen validation, old and malformed artifacts, and bundle preservation.

The temporary cache check ran on macOS. Only the Linux `/proc` process check was
simulated. The normal tests cover the process guard. No live Steam sync was run.

## Local files

The source extraction is in the local state run
`full-hero-coverage-20260906`. Frozen nominations were saved before validation.
The complete review bundle is in `generated/full-hero-coverage/artifacts`.
The isolated wheel, verification script, cache, and backups are in
`/var/folders/jt/s88jx1px65n165_bhj0550cw0000gn/T/deadlock-full-hero-wheel-konqzlhy`.
Large source data and generated bundles are not committed.

Commands used for the main generation and package check:

```bash
uv run deadlock-build-sync refresh-evidence --rank-expansion auto \
  --run-id full-hero-coverage-20260906 \
  --artifacts generated/full-hero-coverage/artifacts
uv run build --artifacts generated/full-hero-coverage/artifacts --format json
uv build
# In the isolated wheel environment, outside the checkout:
build --artifacts artifacts --format json
python verify_wheel.py
```

Extraction completed under the refresh command. The evidence export was then
restarted from that fixed source with the final discovery code. The complete
repository checks are listed in [quality-gates.md](quality-gates.md).
