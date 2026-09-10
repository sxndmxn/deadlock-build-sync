# Purchase-guide search research

State-aware beam search is the preferred search foundation from this experiment.
Diverse beam at width 16 gives a useful coverage and runtime compromise.
ECLAT and Leiden do not establish a clear overall advantage.
The current outcome model still produces cores that fail the requested win-rate comparison.
Therefore, the result is a tested research prototype, not a production guide change.

## Main reports

- [Algorithm comparison and recommendation](comparison-report.md)
- [Results for all 38 heroes](per-hero-results.md)
- [Saved variant and image context](variant-display-context.md)
- [Native build display design](display-design.md)
- [Actual Infernus core-panel example](infernus-display-example.md)
- [Experiment protocol](experiment-protocol.md)
- [Configuration selection before test](selection-rationale.md)
- [Test-data correction and repeated-run disclosure](test-data-correction.md)
- [Verification](verification.md)
- [Reproduction instructions](reproducibility.md)

## Algorithm reports

| Method | Report |
| --- | --- |
| Greedy state-aware ranking | [Greedy](greedy-state-aware-ranking.md) |
| Constrained beam search | [Beam](constrained-beam-search.md) |
| Diverse beam search | [Diverse beam](diverse-beam-search.md) |
| ECLAT plus beam search | [ECLAT](eclat-beam-search.md) |
| Leiden plus beam search | [Leiden](leiden-beam-search.md) |

## Review artifacts

The [results directory](results/) contains aggregate measurements and paired analyses.
The [final settings](final-settings.json) apply to every final comparison.
The [corrected freeze](frozen-specification-corrected.json) binds those settings to the final code and data.
The [original freeze](frozen-specification.json) preserves the failed initial test attempt.

The branch is `experiment/purchase-guide-search`.
The experiment makes no production selection or Steam installation changes.

## Later optional integration

The [integration guide](integration.md) describes the optional production beam generator.
The [accepted plan](integration-plan.md) records its scope.
The [integration comparison](integration-comparison.md) covers every current group.
The [integration verification](integration-verification.md) records the completed checks and limits.
The reports above describe the earlier research experiment.
Their results and frozen settings remain unchanged.

## Pure beam checkpoint comparison

The [20-minute and 30-minute comparison](thirty-minute-beam.md) uses pure state-aware beam search for all 38 heroes.
It removes ECLAT and Leiden group restrictions for both checkpoints.
The [Viscous examples](thirty-minute-viscous-builds.md) include complete purchase sequences and Tier 1–4 option pools.
