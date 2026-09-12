# Steam purchase panels

Verification date: September 12, 2026.

Each build starts with `MAIN CORE` and ends with `TIER 1` through `TIER 4`.
Builds with alternatives place `ALT CORE` and separate numbered `VARIANT` panels between these sections.
Only `MAIN CORE` enters the automatic purchase queue.

The source evidence groups remain unchanged.
Display grouping partitions each source group by its first purchase and imbue target.
The frozen selection rank determines the main path and variant numbers.
Each admitted path occurs once as a main path or variant.
The main path identifier determines the stable build identity.
Build titles use the selected main path's archetype.

`ALT CORE` contains the longest common purchase prefix across the alternative paths.
The prefix ends before the last purchase of every variant.
A single alternative retains its last purchase in `VARIANT 1`.
Paths without a valid prefix or continuation become standalone builds.
No additional item limit applies to `ALT CORE`.
The existing category size bound and dimension calculation remain in effect.

The prefix comparison includes ordered purchase actions, costs, consumed components, resulting inventory, and imbue targets.
Required components and repeated purchases remain in their original order.
Variant panels contain titles and item cards only.
Their descriptions contain no composition instructions or state summaries.
Item tooltips retain purchase windows, statistics, and imbue targets.
`ALT CORE` tooltips identify `VARIANT 1` as their statistics source.

The build description contains complete purchase instructions and evidence limitations for every path.
All four price tiers retain supported optional items.
Optional items with different imbue targets retain separate cards.
Conditional item cards retain their instructions in the applicable tier.
Long conditional instructions use consecutive cards because Steam limits each tooltip to 240 bytes.
Other optional purchase instructions remain in the complete build description.

CLI Markdown, saved Markdown, Steam JSON, and Steam protobuf use the same validated presentation.
The `--details` option adds the existing purchase report after the Steam presentation.
Steam JSON schema 1 again uses `item` for the item name.
The technical `item_pool` field remains unchanged.
Display group schema 2 records `source_group_id`, `shared_prefix_length`, and each path's frozen `selection_rank`.
Canonical guide projection version 4 rejects old derived presentations.
Compatible evidence artifacts remain valid.

## Verification scope

Isolated executable checks cover shared prefixes, incompatible starting items, component upgrades, repeated purchases, and conflicting imbue targets.
They also cover single alternatives, standalone builds, and a 31-purchase shared prefix.
Invalid panel names, missing panels, missing items, changed order, queue flags, annotations, dimensions, and targets fail validation.
No repository unit tests were added.

Kelvin generated 10 builds from 13 paths.
Viscous generated 5 builds from 11 paths.
Abrams generated 3 builds from 24 paths.
Their Markdown, JSON, and decoded protobuf records agree.
The review files contain separate Steam sections for every generated build.

The recorded all-hero comparison contains 260 display builds and all 755 admitted paths across 38 heroes.
The previous presentation contained 139 builds.
Source cores, costs, evidence, cohorts, purchase guidance, optional item membership, and ability orders match the previous Rust output.
The Python comparison permits six existing error-message changes in path `50-ed14d9f35803ad5e`.
Python used `purchase exceeds four active-item bindings`.
Rust uses `Purchase exceeds four active item bindings`.
No purchase decision changes accompany this wording change.

The earlier Rust guide-generation comparison took 275.943 seconds.
The equivalent Python generation took 289.494 seconds.
Both runs used the same evidence and recorded API responses with empty response caches.
This comparison excludes extraction and evidence production.
The separate earlier complete Rust pipeline took 545.893 seconds, or 9 minutes 6 seconds.

## Complete fresh pipeline

The final complete pipeline passed in 562.381 seconds, or 9 minutes 22 seconds.
Evidence refresh took 516.161 seconds.
All-hero guide generation took 46.219 seconds.
The run used eight workers on the recorded Mac with 10 logical processors and 16 GiB memory.
It started with fresh extraction and an empty API response cache.
Rank expansion remained off.
The cutoff remained `2026-09-12T12:02:45Z`.
Compilation remained outside the measurement.

| Stage | Elapsed seconds |
| --- | ---: |
| Source capture | 1.993 |
| Extraction | 134.626 |
| Discovery | 67.738 |
| Numerical validation | 305.155 |
| Evidence admission | 2.463 |
| Complete refresh | 516.161 |
| Guide generation | 46.219 |
| Complete pipeline | 562.381 |

The live source contained 81,113 matches, 973,356 player appearances, and 16,485,567 purchases.
It added 168 matches within the fixed cutoff after the earlier reference extraction.
The final evidence admitted 752 paths across all 38 heroes.
The layout contains 270 builds, including 105 standalone builds and 482 variant paths.
The 141 source evidence groups remain unchanged by display grouping.
The longest live shared prefix contains nine purchases.
No admitted path is missing or repeated.

All live output paths passed reconstruction checks against their admitted purchase actions and imbue targets.
Panel order, dimensions, optional flags, item names, and tooltip limits passed.
CLI Markdown matches the saved Markdown exactly apart from the command's final separator newline.
Saved JSON and decoded protobuf agree with the validated presentation.

An isolated cache fixture checked the derived build coverage and rejected incomplete installed coverage.
Process refusal, backup contents, unrelated Steam sections, repeated installation, and recovery checks passed.
No cache check accessed user Steam data.

The [verification record](research/rust-packages/steam-layout-verification.json) contains exact commands, timings, comparisons, artifact identities, and archive hashes.
Final-commit Linux CI and CodeQL results appear in the verification notes for [PR #30](https://github.com/sxndmxn/deadlock-build-sync/pull/30).

No live Steam installation ran.
Fixture validation does not certify live builds.
In-game panel placement remains unverified pending a separate authorized client check.
