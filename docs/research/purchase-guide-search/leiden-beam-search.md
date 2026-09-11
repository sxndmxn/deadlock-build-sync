# Leiden plus beam search

## Algorithm

Leiden detects communities through local moves, refinement, and graph aggregation.
The [Leiden paper](https://doi.org/10.1038/s41598-019-41695-z) explains how refinement addresses disconnected-community failures.
The [official API reference](https://leidenalg.readthedocs.io/en/stable/reference.html) defines the partition, resolution, iteration, and seed parameters.

## Experiment implementation

Vertices represent eligible items from the same training inventories used by ECLAT.
An edge requires at least the proposal support threshold and positive co-ownership lift.
Its weight is normalized pointwise mutual information, multiplied by support / (support + 100).
This reduces the weight of weakly supported edges.

The partition uses the constant Potts model, resolution 0.08, seed 7, and iterations until no quality improvement remains.
The experiment verifies community connectivity.
Singleton communities do not become build proposals.

Community themes include component ancestors.
Half the search frontier retains ordinary score-ranked states.
The other positions can preserve states near different communities.
The final score and every purchase constraint remain common to all methods.

A community can contain items that never form a supported complete build together.
Connectedness does not mean that every pair has an edge.
Therefore, every completed guide still requires exact joint ownership support.

## Sensitivity findings

The default graph produced 216 non-singleton communities across 38 heroes.
Changing resolution to 0.04 or 0.16 changed community relationships substantially.
Mean co-community pair Jaccard agreement with the default was approximately 0.55 and 0.48.
Changing only the seed to 23 or 71 produced agreements of approximately 0.92 and 0.91.

These structural changes did not produce a consistent guide-support improvement.
The final comparison therefore retains the original graph settings.
A fixed seed provides repeatability within the tested environment.
It does not establish stability across graph definitions, versions, or patches.

## Correctness and limits

A regression test repeats a seeded graph partition and checks connected communities.
The graph uses ownership associations, not causal effects.
Its resolution controls the scale of the proposed communities.
No tested resolution establishes the correct number of tactical archetypes.

Leiden adds graph construction, weighting, resolution, and seed choices.
That complexity needs a measured benefit before production adoption.
A visually distinct community is not sufficient evidence for a useful alternative build.

## Final held-out results

The final test contains 17,995 eligible matches after the documented cohort correction.
The guide comparison uses 342 scenarios; the decision comparison uses 3,648 sampled purchases.
All emitted actions passed independent replay under the declared cash, capacity, and catalog assumptions.

| Method | Guide coverage | Test owners ≥30 | Test owners ≥100 | Median guide time | Inventory distance |
| --- | ---: | ---: | ---: | ---: | ---: |
| Leiden + beam 16 | 95.32% | 92.40% | 50.58% | 5.70 ms | 0.488 |

Support percentages use all 342 scenarios as the denominator.
Inventory distance also uses all scenarios, with zero for fewer than two returned alternatives.

| Method | Next-action agreement | Alternative agreement | Two-action agreement | Median decision time |
| --- | ---: | ---: | ---: | ---: |
| Leiden + beam 16 | 10.31% | 20.09% | 1.56% | 1.90 ms |

Action agreement measures observed purchasing behavior, not a win-rate improvement.
Alternative agreement allows up to three distinct returned paths.
Greedy normally returns only one path.
Two-action agreement uses only observations with an unambiguous two-action suffix.

The [comparison report](comparison-report.md) contains paired intervals, model calibration, limitations, and the recommendation.
The [test correction record](test-data-correction.md) explains the failed first attempt and corrected evaluation.
The [reproduction instructions](reproducibility.md) identify the code, settings, and saved evidence.
