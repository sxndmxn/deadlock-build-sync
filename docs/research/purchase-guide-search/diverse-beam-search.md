# Diverse beam search

## Algorithm

Diverse beam search changes frontier retention to preserve different continuations.
The [original paper](https://arxiv.org/abs/1610.02424) divides sequence beams into groups and penalizes similarity to earlier groups.
This experiment uses a simpler inventory-based adaptation.
It does not reproduce the paper's grouped language-generation algorithm.

## Experiment implementation

The first retained state has the highest common search score.
Each additional state balances that score against its maximum similarity to an already selected inventory.
Similarity uses Jaccard overlap among newly owned items.
Initial items do not create a diversity reward merely because the query already owns them.

The diversity penalty affects frontier retention only.
The final alternatives retain the same unmodified score used by greedy and constrained beam.
Purchase rules, Bayesian smoothing, support floors, and depth remain identical.

The sensitivity study tests widths 8, 16, and 32.
It also tests diversity strengths 0.02, 0.05, and 0.10.
The final comparison uses width 16 and strength 0.02.

## Correctness and limits

The regression tests distinguish inventory diversity from a different item order.
A zero diversity penalty reduces retention to ordinary beam retention.
Final selection still removes identical inventories and strict subset cores.

The diversity parameter depends on the score scale.
Changing Bayesian shrinkage can change its relative strength.
Therefore, a value that helps one scorer may not help another scorer.
Diversity also adds comparison work proportional to retained states and candidate inventories.

Different inventories do not necessarily have different tactical purposes.
The experiment does not invent archetype names or item mechanics from Jaccard distance.
Each displayed alternative needs a complete recipe and its own evidence.

## Selection before test

Diverse beam at width 16 was the primary candidate before the test evaluation.
It offered a useful validation compromise between guide coverage and runtime.
Its advantage over ordinary beam was small.
The [selection record](selection-rationale.md) preserves that decision before test access.

## Final held-out results

The final test contains 17,995 eligible matches after the documented cohort correction.
The guide comparison uses 342 scenarios; the decision comparison uses 3,648 sampled purchases.
All emitted actions passed independent replay under the declared cash, capacity, and catalog assumptions.

| Method | Guide coverage | Test owners ≥30 | Test owners ≥100 | Median guide time | Inventory distance |
| --- | ---: | ---: | ---: | ---: | ---: |
| Diverse beam 16 | 95.32% | 92.11% | 50.88% | 6.41 ms | 0.477 |

Support percentages use all 342 scenarios as the denominator.
Inventory distance also uses all scenarios, with zero for fewer than two returned alternatives.

| Method | Next-action agreement | Alternative agreement | Two-action agreement | Median decision time |
| --- | ---: | ---: | ---: | ---: |
| Diverse beam 16 | 10.31% | 20.12% | 1.56% | 2.05 ms |

Action agreement measures observed purchasing behavior, not a win-rate improvement.
Alternative agreement allows up to three distinct returned paths.
Greedy normally returns only one path.
Two-action agreement uses only observations with an unambiguous two-action suffix.

The [comparison report](comparison-report.md) contains paired intervals, model calibration, limitations, and the recommendation.
The [test correction record](test-data-correction.md) explains the failed first attempt and corrected evaluation.
The [reproduction instructions](reproducibility.md) identify the code, settings, and saved evidence.
