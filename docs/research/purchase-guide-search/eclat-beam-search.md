# ECLAT plus beam search

## Algorithm

ECLAT represents each item with the transactions that contain it.
It finds joint support through transaction-set intersections.
An itemset extension cannot have more support than its subset.
The [ECLAT paper](https://cdn.aaai.org/KDD/1997/KDD97-060.pdf) describes this vertical itemset approach.

## Experiment implementation

The experiment uses exact reconstructed training inventories just after 20 minutes.
Each transaction represents one hero appearance in one match.
The proposals use no validation or test outcomes.

Eligible proposal items cost at least 1,600 souls.
The support threshold is the larger of 100 owners and 1% of the hero's training transactions.
The default miner enumerates every frequent itemset of sizes two through four.
It does not stop after the first 50 candidates.

Package selection requires at least three items, positive lift, compatible component relationships, and a maximum catalog value of 19,200 souls.
It ranks packages by support fraction multiplied by log lift.
It retains up to 12 packages with sufficient inventory distance.
This is a proposal budget, not an item-catalog limit or a proof of superior outcomes.

The search themes include component ancestors so a package can influence an earlier purchase step.
Half the beam remains available to ordinary score-based retention.
Other positions favor candidates near the proposed packages.
Every purchase remains available through the common transition rules.
The final score contains no ECLAT bonus.

## Sensitivity findings

The default miner found 44,324 frequent itemsets across 38 heroes.
A size-three limit found 26,468; a size-six limit found 58,547.
Increasing the size limit did not improve validation guide support.
The full default structure preparation took approximately 0.30 seconds on the test machine.
That time includes both ECLAT and Leiden preparation plus inventory loading.

Lower and higher proposal-support thresholds changed the number of mined itemsets substantially.
They changed final guide support only slightly.
The main constraint on useful output was complete-combination support and the common outcome scorer.

ECLAT improved guide support in the original weakly smoothed comparison.
That advantage did not persist after stronger smoothing and combination-support constraints.
Therefore, its apparent benefit depends on the common model settings.

## Correctness and limits

A regression test verifies exact transaction intersections and support pruning.
Deterministic item ordering makes repeated mining reproducible.
A frequent itemset is an owned combination, not a purchase order.
Extra items can be present in every supporting transaction.

Positive lift does not establish synergy or a causal win-rate benefit.
Use the packages to propose candidate build families.
Keep their exact joint counts separate from the counts of individual items.

## Final held-out results

The final test contains 17,995 eligible matches after the documented cohort correction.
The guide comparison uses 342 scenarios; the decision comparison uses 3,648 sampled purchases.
All emitted actions passed independent replay under the declared cash, capacity, and catalog assumptions.

| Method | Guide coverage | Test owners ≥30 | Test owners ≥100 | Median guide time | Inventory distance |
| --- | ---: | ---: | ---: | ---: | ---: |
| ECLAT + beam 8 | 89.77% | 86.26% | 52.05% | 3.06 ms | 0.466 |
| ECLAT + beam 16 | 93.57% | 90.64% | 51.46% | 5.99 ms | 0.486 |

Support percentages use all 342 scenarios as the denominator.
Inventory distance also uses all scenarios, with zero for fewer than two returned alternatives.

| Method | Next-action agreement | Alternative agreement | Two-action agreement | Median decision time |
| --- | ---: | ---: | ---: | ---: |
| ECLAT + beam 8 | 10.31% | 19.85% | 1.59% | 1.16 ms |
| ECLAT + beam 16 | 10.28% | 19.90% | 1.56% | 2.03 ms |

Action agreement measures observed purchasing behavior, not a win-rate improvement.
Alternative agreement allows up to three distinct returned paths.
Greedy normally returns only one path.
Two-action agreement uses only observations with an unambiguous two-action suffix.

The [comparison report](comparison-report.md) contains paired intervals, model calibration, limitations, and the recommendation.
The [test correction record](test-data-correction.md) explains the failed first attempt and corrected evaluation.
The [reproduction instructions](reproducibility.md) identify the code, settings, and saved evidence.
