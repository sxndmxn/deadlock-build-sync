# Native build display design

## Status: historical experiment

The complete Steam layout replaces the display-budget approach in this experiment.
The exporter retains CORE, separate VARIANT categories, SHARED CORE when applicable, and all four tier panels.
Required variant components remain in the tier panels. Admitted conditional core items use CORE CONDITIONAL.
It does not remove supported items to meet a fixed screen height.
See the [current contract and verification](../../steam-build-layout-2026-09-11.md).
The sections below preserve the original experiment and its limits.

## Result

Use one build for one coherent build family.
Show each common item once where purchase order permits this.
Show complete branch additions with separate statistics.
Keep one default purchase queue.
Mark the other branches and tier options as optional.

A list of unique items cannot preserve every branch relationship.
The available screen area limits both item cards and statistical labels.
Do not use a fixed limit of 50 displayed variants.
Use a measured card and category budget instead.
Keep every complete variant in the saved review artifact.
Three alternatives is the comparison limit, not a proposed global display limit.
The display budget can admit more variants when their complete recipes and statistics fit.

## What the references show

The supplied Mina image shows 38 cards in ten categories.
It uses four horizontal bands with adjacent categories.
Its editor has category names, descriptions, and an Optional control.

The [Holliday image](https://thegamehaus.com/wp-content/uploads/2025/12/holiday-build.png) shows 32 cards in four card rows.
Its wide category headers contain short instructions.
The [Paradox image](https://thegamehaus.com/wp-content/uploads/2025/12/paradox-build.png) separates early, later, and optional purchases.
The [Paige image](https://www.dexerto.fr/cdn-image/wp-content/uploads/sites/2/2026/03/03/paige-build-deadlock-1024x576.jpg) also uses wide purchase-stage rows.

These images show layout choices.
They do not establish current item mechanics, automatic branch selection, or fit at every UI scale.

The repository serializes category width, height, description, and optional status.
Its compact layout uses at most six columns for categories with at most 18 items.
Thus, a nine-card default path currently requires two card rows.
A wider category could reduce that path to one row, subject to a client check.
Category descriptions and item annotations each have a 240-byte limit.

## The earlier Infernus family

This example preserves the earlier analysis.
It is not a recommendation from the new search experiment.
Statistics describe complete owned combinations before 20 minutes in the old validation cohort.
Extra owned items are permitted.
The overall Infernus win rate in that cohort was 47.22%.

```text
INFERNUS — SWIFT / TITANIC FAMILY

SHARED CORE
Swift Striker · Titanic Magazine · Spirit Lifesteal · Toxic Bullets

DEFAULT ADDITIONS             48.92% · 417 matches
Mystic Vulnerability · Enduring Speed

VARIANT 2 ADDITIONS           45.17% · 352 matches
Mystic Vulnerability · Superior Duration

VARIANT 3 ADDITIONS           50.00% · 702 matches
Duration Extender

Each rate describes SHARED CORE + that variant's additions.
These ownership groups can overlap.
```

The three full cores contain 17 card positions.
The factored representation contains nine positions.
Each complete core remains recoverable without a guessed item substitution.

Mystic Vulnerability occurs in two variants, so it is not mandatory for this family.
Using the most common items as mandatory items would change Variant 3.
The strict intersection provides a safe shared core.
A smaller subgroup can have a larger shared core.

Do not label Enduring Speed and Superior Duration as mutually exclusive.
The earlier validation evidence included 173 matches with both items and the shared five-item combination.
A player can also upgrade Duration Extender into Superior Duration.
An upgrade is not an independent permanent alternative.

Only 34 of 417 default-core owners bought the shared four items before all additions.
Therefore, the shared owned core is not an observed common purchase prefix.
Preserve each branch's complete purchase order separately.

## Queue and reference cards

There are two valid display cases.

| Case | Queue treatment | Shared reference treatment |
| --- | --- | --- |
| Variants have an identical ordered prefix | Queue that prefix, then the default branch | Show other branch additions as optional |
| Variants share final items but have different purchase orders | Queue the complete default path | Show the common core as optional reference cards |

Never reorder the default queue solely to place common final items first.
The purchase validator must check the resulting order, component consumption, and incremental prices.
Alternative branches require their own validated order.
Do not assume that an optional item automatically changes the default queue.
State-aware recommendations remain static instructions unless the client supports a verified state-dependent control.

The isolated [display module](../../../tools/purchase_search/display.py) calculates both the final-item intersection and the exact ordered prefix.
Its regression tests reconstruct every complete variant from the shared core and additions.
The tests also reject the assumption that shared ownership implies shared order.

## Statistical labels

The visible branch header needs the branch name, observed win rate, and match count.
A short description must identify the complete combination behind that rate.
A branch annotation can contain the interval, checkpoint, cohort, patch, and order.
A saved Markdown report must contain the complete evidence.

Use a label such as `V2 51% | n92` when space is limited.
Use the same complete branch definition in the report.
Do not assign a shared-core rate to every variant.
Do not sum branch counts because their owner groups can overlap.
Do not display the search utility as a win rate.

The scorer uses Bayesian item estimates.
The example headers use observed complete-combination rates.
Keep those quantities separate.
Show the 95% interval in the detailed evidence.
A small count remains visible even when the posterior estimate appears stable.

A difference between two displayed percentages does not establish a better purchase.
Compare uncertainty and the matched cohort before describing one branch as stronger.
Absence of a significant difference does not establish equivalence.
This experiment does not add a production win-rate admission rule.

## Screen budget

Preserve the default queue before allocating space to optional items.
Then allocate space to branch relationships and statistics.
Use the remaining area for supported Tier 1, Tier 2, Tier 3, and Tier 4 options.
An item tier is a price class, not an instruction to purchase every item in that row.
Do not fill empty space with unsupported options.

For the earlier three-variant family, a conservative representation uses nine default-queue cards and nine factored reference cards.
It intentionally repeats some default items to preserve both order and branch meaning.

| Layout assumption | Default queue | Factored core references | Optional tier cards | Total cards |
| --- | ---: | ---: | ---: | ---: |
| Smaller pane | 9 | 9 | 2 / 2 / 2 / 3 | 27 |
| Larger pane | 9 | 9 | 4 / 4 / 4 / 4 | 34 |

These are capacity examples, not item admission limits.
The larger example needs four horizontal category bands.
The smaller example can use three bands when each tier row remains compact.

The repository uses 84 logical width units per compact card, plus 12 units per category.
Its minimum category width is 128 units.
A one-row category has a height of 164 units.
With 12-unit gaps, three bands need 516 height units; four bands need 692.
These calculations exclude the surrounding application controls.

A 900-by-650 logical content pane can contain the smaller proposed arrangement.
A 1,120-by-750 content pane can contain the larger arrangement.
These dimensions describe the content pane, not the display resolution.
Actual client scale, text wrapping, and category placement still require a live display check.
No live Steam sync or client layout test was performed.

The earlier 52-card union exceeds both proposed budgets.
Reducing duplicate icons alone does not solve its information-density problem.
If every branch cannot fit, retain the most supported distinct branches in the visible guide.
Keep the remaining complete recipes in the review artifact.
Use another build only for a distinct archetype that needs a different default purchase order.

## Display acceptance checks

1. Reconstruct every displayed complete core from the shared items and branch additions.
2. Replay each branch's purchase order and cost independently.
3. Verify that the non-optional categories equal the default queue exactly.
4. Associate each statistical label with one complete combination and one cohort.
5. Keep upgrades separate from mutually exclusive choices.
6. Measure category sizes and text limits at the target UI scale.
7. Preserve the full evidence when a visible label uses rounded values.

These checks belong before production integration.
The experiment adds no Steam serialization or installation changes.
