# Guide consolidation verification — 2026-09-07

Normal generation produced **140 guide groups for all 38 heroes**. They retain all **761 supported exact-core variants**. Abrams has **2 groups with 9 and 12 variants**. The second group contains all 11 Arcane Surge cores. There is no fixed group or variant count limit.

All variants still use **Emissary I–Eternus V (71–115)**. No hero needed rank expansion. The evidence statuses remain **5 outcome_supported and 756 observed**. These statuses belong to individual variants; support counts are not combined across a group.

The [complete JSON record](consolidated-hero-admissions-2026-09-07.json) lists every group and variant, its default, core, Queue, cost, ranks, support, evidence limits, timing, and pool counts. The generated guide bundle contains the complete purchase plans and pools.

## Abrams defaults

| Group | Variants | Default core | Souls | Owners: discovery / selection / validation | Evidence |
| --- | ---: | --- | ---: | --- | --- |
| Melee Charge / Bullet Resist Shredder | 9 | Stalker → Melee Charge → Bullet Resist Shredder → Hunter's Aura → Superior Duration | 11,200 | 898 / 232 / 366 | observed |
| Arcane Surge / Healing Booster | 12 | Arcane Surge → Healing Booster → Healbane → Dispel Magic | 8,000 | 582 / 166 / 182 | observed |

The Queue follows the default variant and includes required components. CORE OPTIONAL contains additional variant items once. Detailed Markdown and JSON retain each complete order, optional choice, cost, and pool. All sections except CORE are optional. Item notes identify variant scope.

## Compact layout

All guides now have five or six subcategories: CORE, CORE OPTIONAL when needed, and TIER 1–4. There are 123 guides with six sections and 17 with five. The total fell from 9,186 to 823 sections. Items in CORE or CORE OPTIONAL are not repeated in the tier sections. Every supported item remains visible; each variant's original pool remains unchanged.

| Abrams guide | Previous sections | Current sections | Unique items | CORE OPTIONAL |
| --- | ---: | ---: | ---: | --- |
| Melee Charge / Bullet Resist Shredder | 80 | 6 | 51 | Warp Stone, Battle Vest |
| Arcane Surge / Healing Booster | 85 | 6 | 51 | Duration Extender, Restorative Locket, Spirit Strike, Spirit Snatch, Superior Duration |

Sections use sizes based on item count. A single-item section uses 128 units of width; empty tiers use a 256-by-48-unit panel. Full instructions are in the build description and detailed Markdown. They do not add subcategories.

Both Abrams geometry previews have an estimated height of 762 units at the recorded 1,039.5-unit content width. Actual Steam scale and screen fit remain unverified. The previews are in `generated/compact-hero-guides/previews`.

## Grouping and evidence

Shared core items determine groups. Edges require at least two common items and item Jaccard ≥ 0.5. The existing Leiden routine uses resolution 1, ten iterations, and seeds 42, 43, and 44. Complete-link merging requires pairwise agreement from at least two seeds. The group default is the member with the best frozen selection rank. Mechanics explain labels after grouping.

This release reused the completed uncapped evidence. Grouping read the saved frozen core items and selection ranks. A complete payload comparison confirmed that paths, pools, evidence, source data, ranks, and the correction family did not change. The production refresh path now saves group assignments before validation.

Checks with reversed input rows and changed validation results kept all group assignments and defaults unchanged. An isolated mutation that restored the direct-edge restriction was detected. Old schema 11 evidence and missing, malformed, or unknown group defaults were rejected. Failed evidence writes preserved the complete previous evidence file. The existing failed-render and failed-replacement integration checks also passed.

The fixed source contains 208,681 matches and 43,326,804 purchase rows from client 6684, DuckLake snapshot 38. Its time range remains 2026-08-22 21:40:46 UTC through 2026-09-07 00:57:40 UTC. The prior source audit found no duplicate match or player keys and excluded all 40,074 reserved test matches from selection and admission. This release verified that the full source and evidence records remain unchanged. The frozen correction family remains 761 core and 165,953 branch hypotheses.

## Verification

- Complete fast local gate passed after the layout change: 1,322 existing tests, warnings as errors, 96.85% statement coverage and 91.52% branch coverage. No test cases were added; existing fixtures and snapshots were updated.
- Ruff ALL and formatting, strict ty, Complexipy at 21 with ignores disabled, Deptry, exact Tach boundaries including type-only imports, and Vulture at 60% all passed. Numeric, file-size, duplicate-code, lockfile, and dependency checks passed. No limit, exclusion, or suppression was changed.
- The unchanged Steam mutation scope passed with cached results: 1,955 killed, 11 timed out, zero survived.
- Updated uv 0.12.10 built the source distribution and wheel. The normal full-roster build command produced 140 groups and 761 complete variants. The runtime-only wheel outside the checkout reconstructed that bundle and verified every canonical variant and published guide.
- Decoded Steam data matched every Queue, optional flag, description, item note, and pool item. All variant costs, component credits, inventories, and supported choices matched the canonical planner. JSON and both Markdown forms matched the reconstructed groups.
- Temporary-cache installation created 140 guides, then updated the same 140. Upgrade from the previous 761-guide temporary cache updated 140 and removed 621 obsolete managed entries. It added none. Favorites, saved managed copies, selected-build references, unrelated data, backup bytes, and restore behavior were preserved. The source cache remained unchanged. Only the Linux process guard was simulated on macOS.
- The installed wheel retained the exact Arcane Surge Abrams recommendation without optional economy or enemy observations: Extra Stamina owned, 300 liquid souls, 800 incremental cost, 500 cash shortfall, and 7,200 remaining core cost.
- The compact layout reused the same evidence, strategy contexts, policies, and narratives without changing their bytes. All 761 canonical variant records were unchanged. The runtime-only wheel outside the checkout reconstructed all 140 guides and checked every decoded category, dimension, note, optional flag, Queue, and Markdown/JSON output. Three injected layout faults were detected: incorrect Queue flags, duplicate cards, and insufficient height.
- Temporary-cache installation of the compact layout updated 140 guides and did the same on rerun, with none created or removed. User data, backup bytes, restore behavior, and the source cache were preserved. No source fetch or statistical fit was repeated.
- No live Steam sync was run.

## Artifacts

- Evidence: `3563c9e3ad30b4d2ae19323faad17d19b135f419ee633a9d62ffc2688babf7e1`.
- Snapshot: `8653f8a302eccd6a66bbbd99d29a4bb8ca5ecbf031ba6fc6472da270957baa21`.
- Compact-layout wheel SHA-256: `82297b807d3434c50de78d4a9ee118eb4dc15256a33cd22a071be4f96048cdcb`.
- Directory: `generated/compact-hero-guides/artifacts`.
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
