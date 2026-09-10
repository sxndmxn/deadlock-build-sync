# Greedy state-aware ranking

## Algorithm

Greedy search keeps one continuation at each purchase step.
It selects the valid action with the highest cumulative score at that step.
It does not preserve a lower-scoring action for a possible later benefit.
This is the baseline search rule described in the [University of Wisconsin search notes](https://pages.cs.wisc.edu/~dyer/cs540/notes/search2.html).

## Experiment implementation

The state contains hero, patch context, owned items, previously purchased items, net worth, cash, budget use, and relative wealth.
Each transition consumes direct components and uses their credit once.
Only additional simulated income increases net worth.
The action score uses the training-only Bayesian item estimate, state baseline, uncertainty penalty, incremental cost, and step discount.

Greedy retains supported completed prefixes while continuing its single path.
It returns the highest-scoring supported completion within the depth limit.
A completed guide core needs three final items and 200 training owners in the matched checkpoint state.
A decision query can return one newly purchased item.

This implementation is state aware through wealth, support, inventory rules, and component prices.
It does not learn a complete inventory-conditioned treatment effect.
The [protocol](experiment-protocol.md) defines the common model and constraints.

## Correctness and limits

Width-one beam must equal greedy under identical settings.
The regression tests verify that equality.
They also verify cash, net worth, upgrade credit, slot limits, active-item limits, and unsupported-state abstention.

A synthetic component example demonstrates greedy's delayed-value failure.
A component has lower immediate utility but enables a better later upgrade sequence.
Beam preserves that continuation; greedy removes it.

Greedy is useful as a fast next-action baseline.
Its complete-core coverage is too low for the preferred guide generator in this experiment.
Its speed does not establish higher guide quality.

## Initial failure experiment

With only individual item-cell support, greedy produced almost no supported complete combinations.
Only 2.63% of its top guides had at least 30 validation owners.
The matched checkpoints in this figure are the corrected 600, 1,201, and 1,801-second checkpoints.
Valid individual purchases therefore do not establish a supported build.

The earlier files with empty later state cohorts are superseded.
They did not influence the reserved test evaluation.

## Final held-out results

The final test contains 17,995 eligible matches after the documented cohort correction.
The guide comparison uses 342 scenarios; the decision comparison uses 3,648 sampled purchases.
All emitted actions passed independent replay under the declared cash, capacity, and catalog assumptions.

| Method | Guide coverage | Test owners ≥30 | Test owners ≥100 | Median guide time | Inventory distance |
| --- | ---: | ---: | ---: | ---: | ---: |
| Greedy | 47.95% | 45.61% | 28.36% | 0.44 ms | 0.000 |

Support percentages use all 342 scenarios as the denominator.
Inventory distance also uses all scenarios, with zero for fewer than two returned alternatives.

| Method | Next-action agreement | Alternative agreement | Two-action agreement | Median decision time |
| --- | ---: | ---: | ---: | ---: |
| Greedy | 9.43% | 9.43% | 0.78% | 0.18 ms |

Action agreement measures observed purchasing behavior, not a win-rate improvement.
Alternative agreement allows up to three distinct returned paths.
Greedy normally returns only one path.
Two-action agreement uses only observations with an unambiguous two-action suffix.

The [comparison report](comparison-report.md) contains paired intervals, model calibration, limitations, and the recommendation.
The [test correction record](test-data-correction.md) explains the failed first attempt and corrected evaluation.
The [reproduction instructions](reproducibility.md) identify the code, settings, and saved evidence.
