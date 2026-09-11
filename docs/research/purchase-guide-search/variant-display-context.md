# Variant evidence and display context

## Scope

This record preserves the findings that preceded the purchase-guide search experiments.
The source implementation is PR #26 at commit `625ecea968b470808b146112ee2dc96c9d64f4f3`.
The merged base is `0ecad50`, which contains PR #26.
No production algorithm or Steam file changed during that review.
The proposed win-rate admission rule remains unimplemented.

## Evidence source

The saved run is `20260909T001949Z`.
Its directory is `/Users/sandmac/.local/state/deadlock-build-sync/offline/results/20260909T001949Z`.
Its evidence fingerprint starts with `d5d6fe6ca7b52f2c`.
The cohort uses ranked Normal matches and badges 71 through 115.
The observation period starts on 2026-08-22 and ends on 2026-09-09.

The analysis used the saved DuckDB database with read-only access.
The earlier reports remain in the PR worktree under `generated/discovery-audit-2026-09-10/`.
The detailed branch counts are in `infernus-shared-core-branches.json` there.

## Statistical meaning

A core owner has every listed item immediately before 20 minutes.
The match lasts at least 20 minutes.
Additional items are permitted.
These observations describe item sets, not exact inventories or purchase sequences.
One match can belong to several cores.
Do not add their match counts or average their win rates.
A subset core does not establish that players omitted the other items.

The raw review used at least 100 owners in each discovery, selection, and validation period.
It also required a win rate above the corresponding hero baseline in selection and validation.
The sample floor was an analysis choice, not a statistically sufficient guarantee.
No proposed admission rule was implemented.

| Period | Infernus matches | Wins | Hero win rate |
| --- | ---: | ---: | ---: |
| Discovery | 16,003 | 7,545 | 47.1474% |
| Selection | 5,203 | 2,393 | 45.9927% |
| Validation | 7,124 | 3,364 | 47.2207% |

The reserved test period was not used in that review.
The existing validation period has now informed discussion and must not become a fresh test set for these experiments.

## Infernus findings

The review checked 2,283 cores, including 1,772 four-to-six-item cores and 511 three-item fallback cores.
Of the four-to-six-item cores, 329 passed the raw review.
Of those 329 cores, 277 were outside the existing candidate cap.
Thirteen of 24 saved variants passed, including five of six group defaults.
No core passed the multiple-comparison uncertainty check in both later periods.
No core had a positive adjusted lower confidence limit in both later periods.
These results do not establish a causal win advantage.

The candidate limit of 50 applies separately to each core size.
It does not limit the item catalog to 50 items.
The audit found that this limit precedes later usability checks.
The audit also identified inconsistent support floors, missing balance features treated as zero, and an invalid one-fold estimation case.
These findings remain outside the new search experiment scope unless they affect experiment correctness.

## Shared core example

These three saved combinations share four required items:

- Swift Striker
- Titanic Magazine
- Spirit Lifesteal
- Toxic Bullets

| Saved combination | Additions to the shared four | Selection win rate | Selection matches | Validation win rate | Validation matches |
| --- | --- | ---: | ---: | ---: | ---: |
| Default, `6-17` | Mystic Vulnerability; Enduring Speed | 52.20% | 341 | 48.92% | 417 |
| Variant 2, `6-49` | Mystic Vulnerability; Superior Duration | 51.05% | 286 | 45.17% | 352 |
| Variant 3, `5-24` | Duration Extender | 44.09% | 558 | 50.00% | 702 |
| Shared four, `4-4` | No additional required item | 46.26% | 1,163 | 48.95% | 1,434 |

Showing the shared four once and each addition separately reduces 17 core card positions to nine.
The first two combinations also share Mystic Vulnerability.
Their display can share five cards when it preserves the complete branch definitions.

### Alternatives are not automatically exclusive

Among validation players with the shared five items, 173 also owned both Enduring Speed and Superior Duration.
The following groups are disjoint within that shared-five population:

| Ownership before 20 minutes | Validation wins | Validation matches | Validation win rate |
| --- | ---: | ---: | ---: |
| Enduring Speed, without Superior Duration | 130 | 244 | 53.28% |
| Superior Duration, without Enduring Speed | 85 | 179 | 47.49% |
| Both | 74 | 173 | 42.77% |
| Neither | 201 | 435 | 46.21% |

The unadjusted two-sided Fisher comparison between the first two groups gave `p = 0.279` in validation.
This does not establish equivalence or a causal treatment effect.
The corresponding selection comparison gave `p = 0.740`.

The item graph identifies Duration Extender as a component of Superior Duration.
The item graph identifies Sprint Boots as a component of Enduring Speed.
Component consumption must remain distinct from a choice between unrelated items.

The shared four preceded every branch addition in only 34 of 417 validation observations for the default combination.
Thus, a shared display must not invent a shared purchase prefix.

## Display requirements

Each visible variant must identify a complete supported combination.
A pool containing every variant item does not preserve that information by itself.
Full variant rows are understandable but repeat many cards.
A shared core with explicit additions can preserve combinations with fewer cards.

Use the exact intersection for a shared required core.
Items that are merely common must not become requirements for variants that omit them.
Keep the full combination, purchase instructions, observation definition, and statistics available for each variant.
Keep item statistics distinct from complete-combination statistics.
Mark uncertain results clearly.

Use `PICK ONE` only when the choice refers to a supported decision.
Ownership overlap alone does not establish exclusive alternatives.
Use `CORE OPTIONS` when the evidence supports co-ownership.
Use a separate upgrade instruction for components and upgrades.

Keep Tier 1 through Tier 4 as optional categories.
Deduplicate these tier cards against the visible core and branch cards.
Queue only one valid default purchase path.
The native interface does not have a confirmed automatic variant selector.

## Screen capacity example

The selected saved group contains eight core combinations.
Its default purchase path contains nine cards, including three components.
Its other core combinations add only Duration Extender and Superior Duration to that item union.
The deduplicated tier pools contain nine Tier 1, ten Tier 2, ten Tier 3, and twelve Tier 4 cards.
The complete union therefore contains 52 unique cards.
Showing all eight full cores requires 38 core card positions before components and tier pools.
No live client check established that either layout fits at every resolution or UI scale.

The existing layout uses six columns for categories with at most 18 cards.
This can produce extra rows for categories that a wider arrangement could display in one row.
The display experiment must measure card positions, rows, duplicate cards, and branch reconstruction accuracy.

## Image references

The attached Mina build-editor image is `/tmp/E40E8E4C-9232-4387-8848-7FAA167A3E52.jpeg`.
It shows 38 cards across ten categories, with short labels and several categories beside each other.
Its category editor exposes name, description, and an Optional flag.

The following images supplied additional native-layout references:

- [Paradox](https://thegamehaus.com/wp-content/uploads/2025/12/paradox-build.png): early, later, and optional item groups.
- [Infernus](https://thegamehaus.com/wp-content/uploads/2025/12/infernus-build.png): separate early, later, and optional groups.
- [Holliday](https://thegamehaus.com/wp-content/uploads/2025/12/holiday-build.png): wide rows and short category notes.
- [Paige](https://www.dexerto.fr/cdn-image/wp-content/uploads/sites/2/2026/03/03/paige-build-deadlock-1024x576.jpg): three wide purchase-stage sections.
- [Rem](https://www.dexerto.com/cdn-image/wp-content/uploads/2026/03/03/Rem-Deadlock-1-1024x576.jpg): three wide purchase-stage sections.
- [Warden](https://thegamehaus.com/wp-content/uploads/2025/12/warden-build.png.webp): category notes beside short headings.
- [Haze](https://thegamehaus.com/wp-content/uploads/2025/12/haze-build.png): early, mid, late, and situational sections.

These images establish layout examples, not current item recommendations.
Markdown remains the requested format for build examples and research reports.

## Experiment requirements

Compare greedy state-aware ranking, constrained beam search, diverse beam search, ECLAT plus beam search, and Leiden plus beam search.
Use the same scoring function and purchase constraints across methods.
Use hero, patch, net-worth-dependent item statistics, and cost.
Use Bayesian smoothing when purchase counts are available.
Evaluate purchase validity, held-out performance, coverage, support, path differences, and runtime.
Do not judge success only through the optimized search score.
Preserve the test boundary and distinguish observational results from policy effects.
Document each algorithm in a separate Markdown file.
Keep experiments separate from the live Steam workflow.
