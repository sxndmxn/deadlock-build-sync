# Constrained beam search

## Algorithm

Beam search retains several partial purchase sequences at each depth.
It expands their valid next purchases and retains the best bounded frontier.
The [University of Wisconsin search notes](https://pages.cs.wisc.edu/~dyer/cs540/notes/search2.html) describe this bounded-search principle.
A finite beam does not guarantee a globally optimal sequence.

## Experiment implementation

Every method uses the same transition, item model, combination-support constraint, and final score.
Beam width changes only the number of retained states.
The final comparison includes widths 4, 8, 16, and 32.
The wider sensitivity study also tests width 64.

A state identity includes owned items, purchased items, cash, net worth, and budget use.
The purchased-item history matters because this experiment rejects repeated item actions.
States with identical future constraints retain only the best score and deterministic order.
At a fixed depth, this removal preserves the best continuation under the common scorer.

The support bound includes descendant ownership when checking an intermediate component.
A completed core must pass exact ownership support without that expansion.
The search retains completed supported prefixes, so it can return a partial core before exhausting the budget.

Final selection removes duplicate inventories, strict subset cores, and prefix-only extensions.
It preserves the best returned path.
Thus, reordering identical final items does not create another displayed build.

## Search work

Before pruning, a depth-D beam with width B considers at most D × B × I actions, where I is the item count.
Inventory distance and structure retention add separate work.
The item catalog contains 156 items in this saved snapshot.

The optimized candidate filter removes items unsupported in every reachable net-worth bin.
It includes the maximum affordable future income in that bound.
Every remaining purchase still passes the exact transition and support checks.
All 35,910 final validation records matched the unfiltered implementation, apart from time and attempted-action counts.

## Correctness and limits

Regression tests compare a sufficiently wide beam with exhaustive search on a small catalog.
They verify that width-one beam equals greedy.
They also check a delayed upgrade benefit and independent production-mechanics replay.

A wider beam does not guarantee a better completed result at every query.
Additional partial states can remove a useful continuation at a later depth.
In final validation, greedy could supply a supported fallback for four width-four abstentions.
Widths eight and above had no such lost greedy completions in that comparison.

Depth twelve increased search work without improving validation support.
The final depth is six purchase actions, including consumed components.
Six actions do not necessarily produce six final items.

The search score sums item associations across purchase steps.
It can reward both a component and its upgrade.
It has no duration model that separates their time in use.
The support constraint reduces implausible combinations but does not repair that outcome-model limitation.

## Final held-out results

The final test contains 17,995 eligible matches after the documented cohort correction.
The guide comparison uses 342 scenarios; the decision comparison uses 3,648 sampled purchases.
All emitted actions passed independent replay under the declared cash, capacity, and catalog assumptions.

| Method | Guide coverage | Test owners ≥30 | Test owners ≥100 | Median guide time | Inventory distance |
| --- | ---: | ---: | ---: | ---: | ---: |
| Beam 4 | 78.95% | 75.73% | 44.74% | 1.43 ms | 0.328 |
| Beam 8 | 87.72% | 85.09% | 47.37% | 2.74 ms | 0.407 |
| Beam 16 | 93.86% | 90.64% | 51.46% | 5.10 ms | 0.459 |
| Beam 32 | 96.49% | 93.27% | 52.92% | 9.03 ms | 0.492 |

Support percentages use all 342 scenarios as the denominator.
Inventory distance also uses all scenarios, with zero for fewer than two returned alternatives.

| Method | Next-action agreement | Alternative agreement | Two-action agreement | Median decision time |
| --- | ---: | ---: | ---: | ---: |
| Beam 4 | 9.90% | 18.75% | 1.34% | 0.56 ms |
| Beam 8 | 10.22% | 19.63% | 1.50% | 1.01 ms |
| Beam 16 | 10.28% | 20.12% | 1.56% | 1.76 ms |
| Beam 32 | 10.22% | 20.12% | 1.56% | 2.52 ms |

Action agreement measures observed purchasing behavior, not a win-rate improvement.
Alternative agreement allows up to three distinct returned paths.
Greedy normally returns only one path.
Two-action agreement uses only observations with an unambiguous two-action suffix.

The [comparison report](comparison-report.md) contains paired intervals, model calibration, limitations, and the recommendation.
The [test correction record](test-data-correction.md) explains the failed first attempt and corrected evaluation.
The [reproduction instructions](reproducibility.md) identify the code, settings, and saved evidence.
