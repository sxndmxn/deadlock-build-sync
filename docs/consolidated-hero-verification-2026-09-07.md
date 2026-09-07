# Guide consolidation verification — 2026-09-07

Normal generation produced **140 guide groups for all 38 heroes**. They retain all **761 supported exact-core variants**. Abrams has **2 groups with 9 and 12 variants**. The second group contains all 11 Arcane Surge cores. There is no fixed group or variant count limit.

All variants still use **Emissary I–Eternus V (71–115)**. No hero needed rank expansion. The evidence statuses remain **5 outcome_supported and 756 observed**. These statuses belong to individual variants; support counts are not combined across a group.

The [complete JSON record](consolidated-hero-admissions-2026-09-07.json) lists every group and variant, its default, core, Queue, cost, ranks, support, evidence limits, timing, and pool counts. The generated guide bundle contains the complete purchase plans and pools.

## Abrams defaults

| Group | Variants | Default core | Souls | Owners: discovery / selection / validation | Evidence |
| --- | ---: | --- | ---: | --- | --- |
| Melee Charge / Bullet Resist Shredder | 9 | Stalker → Melee Charge → Bullet Resist Shredder → Hunter's Aura → Superior Duration | 11,200 | 898 / 232 / 366 | observed |
| Arcane Surge / Healing Booster | 12 | Arcane Surge → Healing Booster → Healbane → Dispel Magic | 8,000 | 582 / 166 / 182 | observed |

The Queue follows the default variant and includes required components. Other variants appear as compact changes from that default. Detailed Markdown and JSON retain each complete order, optional choice, cost, and pool. All Steam variant rows are optional. Pool notes identify which variant can use each item.

## Grouping and evidence

Shared core items determine groups. Edges require at least two common items and item Jaccard ≥ 0.5. The existing Leiden routine uses resolution 1, ten iterations, and seeds 42, 43, and 44. Complete-link merging requires pairwise agreement from at least two seeds. The group default is the member with the best frozen selection rank. Mechanics explain labels after grouping.

This release reused the completed uncapped evidence. Grouping read the saved frozen core items and selection ranks. A complete payload comparison confirmed that paths, pools, evidence, source data, ranks, and the correction family did not change. The production refresh path now saves group assignments before validation.

Checks with reversed input rows and changed validation results kept all group assignments and defaults unchanged. An isolated mutation that restored the direct-edge restriction was detected. Old schema 11 evidence and missing, malformed, or unknown group defaults were rejected. Failed evidence writes preserved the complete previous evidence file. The existing failed-render and failed-replacement integration checks also passed.

The fixed source contains 208,681 matches and 43,326,804 purchase rows from client 6684, DuckLake snapshot 38. Its time range remains 2026-08-22 21:40:46 UTC through 2026-09-07 00:57:40 UTC. The prior source audit found no duplicate match or player keys and excluded all 40,074 reserved test matches from selection and admission. This release verified that the full source and evidence records remain unchanged. The frozen correction family remains 761 core and 165,953 branch hypotheses.

## Verification

- Complete fast local gate passed: 1,322 existing tests, warnings as errors, 96.86% statement coverage and 91.57% branch coverage. No test cases were added; existing fixtures and snapshots were updated.
- Ruff ALL and formatting, strict ty, Complexipy at 21 with ignores disabled, Deptry, exact Tach boundaries including type-only imports, and Vulture at 60% all passed. Numeric, file-size, duplicate-code, lockfile, and dependency checks passed. No limit, exclusion, or suppression was changed.
- The unchanged Steam mutation scope passed with cached results: 1,955 killed, 11 timed out, zero survived.
- Updated uv 0.12.10 built the source distribution and wheel. The normal full-roster build command produced 140 groups and 761 complete variants. The runtime-only wheel outside the checkout reconstructed that bundle and verified every canonical variant and published guide.
- Decoded Steam data matched every Queue, optional flag, description, item note, and pool item. All variant costs, component credits, inventories, and supported choices matched the canonical planner. JSON and both Markdown forms matched the reconstructed groups.
- Temporary-cache installation created 140 guides, then updated the same 140. Upgrade from the previous 761-guide temporary cache updated 140 and removed 621 obsolete managed entries. It added none. Favorites, saved managed copies, selected-build references, unrelated data, backup bytes, and restore behavior were preserved. The source cache remained unchanged. Only the Linux process guard was simulated on macOS.
- The installed wheel retained the exact Arcane Surge Abrams recommendation without optional economy or enemy observations: Extra Stamina owned, 300 liquid souls, 800 incremental cost, 500 cash shortfall, and 7,200 remaining core cost.
- No live Steam sync was run.

## Artifacts

- Evidence: `3563c9e3ad30b4d2ae19323faad17d19b135f419ee633a9d62ffc2688babf7e1`.
- Snapshot: `8653f8a302eccd6a66bbbd99d29a4bb8ca5ecbf031ba6fc6472da270957baa21`.
- Wheel SHA-256: `ea059c9c598ffde452a3732d3666780d7bfce7a11bc50c37909c6e9b6d6cdd0f`.
- Directory: `generated/consolidated-hero-coverage/artifacts`.
- Evidence schema 12; method `eclat-leiden-pairwise-v3`; guide index schema 2; group record schema 1. Purchase-guide and decision-state schemas remain 3.
- Refresh old evidence with `deadlock-build-sync refresh-evidence`, then run `uv run build`.

## Roster coverage

Every hero below uses Emissary I–Eternus V. Exact per-variant support and status are in the linked JSON record.

| Hero | Guide groups | Exact-core variants |
| --- | ---: | ---: |
| Abrams | 2 | 21 |
| Apollo | 3 | 26 |
| Bebop | 6 | 34 |
| Billy | 4 | 36 |
| Calico | 4 | 19 |
| Celeste | 4 | 13 |
| Drifter | 5 | 26 |
| Dynamo | 2 | 27 |
| Graves | 4 | 11 |
| Grey Talon | 4 | 28 |
| Haze | 3 | 28 |
| Holliday | 3 | 23 |
| Infernus | 6 | 25 |
| Ivy | 5 | 20 |
| Kelvin | 3 | 11 |
| Lady Geist | 5 | 20 |
| Lash | 4 | 34 |
| McGinnis | 4 | 18 |
| Mina | 5 | 23 |
| Mirage | 4 | 14 |
| Mo & Krill | 4 | 25 |
| Paige | 3 | 23 |
| Paradox | 6 | 24 |
| Pocket | 3 | 23 |
| Rem | 4 | 16 |
| Seven | 6 | 11 |
| Shiv | 5 | 29 |
| Silver | 2 | 6 |
| Sinclair | 2 | 7 |
| The Doorman | 1 | 1 |
| Venator | 5 | 18 |
| Victor | 2 | 6 |
| Vindicta | 3 | 20 |
| Viscous | 3 | 12 |
| Vyper | 2 | 16 |
| Warden | 2 | 22 |
| Wraith | 5 | 31 |
| Yamato | 2 | 14 |
