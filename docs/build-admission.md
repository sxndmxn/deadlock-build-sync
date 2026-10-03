# Build admission methods

## Decision

Admit a main core or alternate path only when its validation evidence meets all four requirements:

1. The core win rate exceeds the hero win rate in the same validation sample.
2. The adjusted difference between core owners and comparable nonowners exceeds zero.
3. The comparison includes at least 100 core owners.
4. The comparison includes at least 80% of all validation core owners.

Equal rates and zero differences do not qualify.
Missing comparisons prevent admission.
Malformed rates, inconsistent counts, and inconsistent adjusted differences invalidate the source artifact.
Direct selection and artifact reconstruction use the same requirements as the evidence catalog.

The numerical thresholds already apply to outcome support in this repository.
They are operational requirements, not universal statistical guarantees.
This change does not select thresholds to retain a specified number of heroes.
If a requested hero has no admitted path, generation stops before artifact replacement.

## Comparison

The current analysis measures core ownership at 20 minutes in matches that last at least 20 minutes.
It uses separate discovery, selection, validation, and reserved test partitions.
The admission rule uses validation results.
It does not use the reserved test partition.

For each hero, the analysis groups validation observations by these values:

- Player wealth in intervals of 5,000 souls.
- Relative team lead, with boundaries at -10%, -3%, 3%, and 10%.
- Rank groups from the integer badge identifier divided by 20.

Each comparison group must contain at least ten core owners and ten nonowners.
Both groups use the same weight: the group's share of comparable core owners.
The adjusted difference is the weighted core win rate minus the weighted nonowner win rate.
The 80% requirement limits how much owner evidence the comparison can omit.

The raw hero baseline includes core owners.
It is not an independent control sample for a two-sample significance test.
The adjusted comparison instead uses nonowners from the same observation groups.
This change retains the existing estimator and uncertainty calculations.

## Research assessment

Confounding can produce differences between observed associations and causal effects.
An adjustment can also introduce bias when it uses variables that the intervention could affect.
These limitations apply to our observational comparison.
[Cochrane's methods guidance](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-25#section-25-2-1) explains both problems.

Our wealth and team-state measurements occur before the 20-minute observation, but they can occur after item purchases.
Thus, they are not necessarily measurements from before the build's effects.
The comparison describes outcomes among similar observed states.
It does not estimate the causal effect of choosing the build at match start.
Missing state data, coarse rank groups, and unmeasured player differences can still affect results.

An uncertainty interval adds information that a point estimate cannot provide.
[NIST compares interval methods for differences between proportions](https://itl.nist.gov/div898/software/dataplot/refman1/auxillar/diffprop.htm).
Its simple two-sample formulas do not directly replace our weighted comparison.
A replacement would require verification of weights, sample dependence, and interval coverage.

The existing analysis also calculates a lower confidence bound with a correction for multiple comparisons.
[NIST describes the Bonferroni correction](https://www.itl.nist.gov/div898/handbook/prc/section4/prc473.htm).
Its error control depends on valid underlying statistical calculations and the specified comparison family.
Changing the admission rule does not establish those assumptions.

The [American Statistical Association](https://www.amstat.org/asa/files/pdfs/p-valuestatement.pdf) advises against decisions based only on a p-value threshold.
Statistical significance does not measure practical value.
Failure to establish a positive difference does not establish that a build is useless.
Therefore, admission and the existing `observed` and `outcome_supported` labels remain separate.
Admission does not promote an `observed` path to `outcome_supported`.

## Alternatives

| Method | Benefit | Limitation | Decision |
| --- | --- | --- | --- |
| Raw win rate above the hero baseline | Simple comparison within the same sample | Ignores game state and sampling uncertainty | Retain as one requirement |
| Positive adjusted difference with sufficient comparison coverage | Rejects paths with no positive adjusted estimate or insufficient comparison data | Small positive estimates can still reflect sampling variation | Add to admission |
| Positive lower confidence bound after multiple-comparison correction | Stronger evidence under the statistical assumptions | Inconclusive paths can include useful builds | Retain in outcome support |
| A minimum practical difference | Rejects advantages too small to justify another build | Requires a justified threshold and independent evaluation | Do not invent a threshold |

Future evaluation can compare admission stability across later time periods and patches.
It should measure prediction performance, calibration, and comparison coverage.
It must keep the reserved test partition separate from threshold selection.

## Admission report

Successful artifact generation writes `build-admission.json` with schema version 1.
The report contains the source artifact identifier, method, thresholds, counts, and one decision per source path.
Each path record includes raw rates, the adjusted difference, comparison coverage, and every applicable rejection reason.
The report also lists excluded heroes.
It preserves the distinction between missing evidence and a nonpositive estimate.

The report is diagnostic output.
It cannot authorize installation or replace source validation.
The reader retains the original evidence bytes and fingerprints.
Old bundles with paths that fail the new requirements must be regenerated.

Research review date: 2026-09-14.
