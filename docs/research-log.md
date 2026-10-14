# Research log

This log records experiments on the build method.
Each entry states a hypothesis, the method, the result, and the decision.
The examples in `crates/deadlock-analysis/examples` repeat each experiment on an extracted run.
Run them with `--release`. Each example writes tab-separated text to standard output.

Unless an entry states otherwise, the data is run `20261012T233433Z`.
This run uses the patch of 2026-10-09, Ritualist I to Eternus V, 41 heroes, and 270,708 player matches.
The test fold contains the last 20% of matches by start time.

## E0: effect scale of the item score

**Hypothesis.** The item score `ln(adoption / 0.03) + effect / scale` gives better builds than adoption alone.

**Method.** `compare_item_scoring` estimates item effects once from development matches.
It assembles every hero's build for each scale and tests all builds with one pooled agreement model on the test fold.

**Result.** The scales from `inf` (adoption only) to 0.05 gave agreement coefficients from 0.078 to 0.115, with standard errors near 0.020.
The scale 0.025 gave 0.281 ± 0.021. See the table in [Build method](build-method.md#comparison-with-simpler-choices).

**Analysis.** At the scale 0.025, 32.9% of CORE items had an adoption below 3%. At the scale 0.1, the share was 1.1%.
The median CORE item adoption fell from 40.5% to 9.5%.
Healing Rite entered CORE for all 41 heroes with a mean adoption of 1.1%.
Players sell Healing Rite in 83% of matches, after a median of 11.5 minutes.
Thus, ownership of Healing Rite at a late landmark identifies the rare players who did not sell it.

The team lead before each purchase was at most 0.017 for every item with at least 300 buyers.
Thus, these items do not win because players buy them when their team is already ahead.

**Decision.** Do not change the scale. The agreement test rewards the same association that the effect estimate measures.

## E1: reliability of item effects

**Hypothesis.** Effect estimates for rare items are mostly noise.

**Method.** `export_split_item_effects` estimates item effects separately on development matches with even and odd identifiers.
The correlation between the two samples measures reliability. Each sample has half of the development data.

**Result.**

| Adoption | Hero model correlation | Global model correlation | Global effect standard deviation |
| --- | --- | --- | --- |
| Below 1% | 0.33 | 0.21 | 0.143 |
| 1% to 3% | 0.48 | 0.56 | 0.111 |
| 3% to 10% | 0.46 | 0.63 | 0.087 |
| 10% or more | 0.46 to 0.52 | 0.70 | 0.077 |

**Analysis.** Rare items have the least reliable effects and the largest spread of effects.
The global ridge penalty of 5 does not shrink rare items enough. Hero models inherit this noise from the global prior.

**Decision.** Test stronger ridge penalties (E2).

## E2: ridge penalties

**Hypothesis.** The ridge penalties of 5 (global) and 100 (hero) are too weak.

**Method.** `compare_effect_penalties` fits the effect models on development matches for each penalty pair.
It predicts the match result of each test state at the three phase landmarks and measures the mean log loss.
The difference to the first pair uses the same states. Its standard error treats each match as one independent unit.
Penalties of 10⁹ remove all item effects and give the baseline.

**Result.** The test has 144,195 states.

| Global penalty | Hero penalty | Log loss | Difference to current | Standard error |
| --- | --- | --- | --- | --- |
| 5 | 100 | 0.514579 | 0 | 0 |
| 10⁹ | 10⁹ | 0.514723 | +0.000144 | 0.000189 |
| 200 | 200 | 0.514379 | −0.000200 | 0.000050 |
| 200 | 300 | 0.514363 | −0.000216 | 0.000065 |
| 1000 | 300 | 0.514360 | −0.000219 | 0.000084 |
| 1000 | 1000 | 0.514425 | −0.000154 | 0.000117 |
| 5000 | 3000 | 0.514543 | −0.000036 | 0.000154 |

**Analysis.** With the current penalties, item effects do not predict match results significantly better than no item effects.
Penalties near 200 (global) and 200 to 300 (hero) are better than the current penalties by 3 to 4 standard errors.
After net worth, team lead, and rank, item ownership adds little information about the match result.

**Replication.** The same test ran on two earlier patches.

| Run | Patch | Test states | No item effects | Penalties 200 and 300 |
| --- | --- | --- | --- | --- |
| `20261012T233433Z` | 2026-10-09 | 144,195 | +0.000144 ± 0.000189 | −0.000216 ± 0.000065 |
| `20261003T172322Z` | 2026-09-30 | 77,683 | −0.000385 ± 0.000270 | −0.000497 ± 0.000116 |
| `20260913T235155Z` | 2026-08-22 | 546,581 | +0.000468 ± 0.000099 | −0.000180 ± 0.000025 |

Each value is the log loss difference to the penalties 5 and 100.
The penalties 200 and 300 were better on each patch, by 3.3 to 7.2 standard errors.
They were best or within one standard error of the best pair in each run.
On the largest run, the item effects predict significantly better than no item effects. Thus, the effects are a weak but real signal.

**Decision.** Use the penalties 200 (global) and 300 (hero).

## E0 repeated with the new penalties

**Result.**

| Effect scale | 2026-10-09 coefficient | Rare CORE share | 2026-09-30 coefficient | Rare CORE share |
| --- | --- | --- | --- | --- |
| `inf` | 0.078 ± 0.021 | 0% | 0.011 ± 0.028 | 0% |
| 0.4 | 0.133 ± 0.021 | 0% | 0.013 ± 0.027 | 0% |
| 0.2 | 0.120 ± 0.020 | 0% | 0.030 ± 0.027 | 0% |
| 0.1 (installed) | 0.086 ± 0.020 | 0% | 0.032 ± 0.027 | 0.4% |
| 0.05 | 0.144 ± 0.020 | 1.4% | 0.041 ± 0.028 | 0.6% |
| 0.025 | 0.222 ± 0.021 | 14.7% | 0.054 ± 0.028 | 7.2% |

A rare CORE item has an adoption below 3% at the phase that added it.

**Analysis.** The large coefficient at the scale 0.025 did not replicate on the earlier patch. On that patch, all scales are within one standard error.
The new penalties reduced the rare CORE share at the scale 0.025 from 32.9% to 14.7%.

**Decision.** Keep the scale 0.1. The agreement test cannot separate the scales. A test with more statistical power is necessary.

## E3: net worth growth as the outcome

**Hypothesis.** The match result depends on ten other players, so it is a noisy outcome for one item choice.
The net worth growth after a landmark depends more directly on the player and can give more reliable item effects.

**Method.** A linear ridge model predicted the logarithm of net worth growth from each phase landmark to the next landmark (9 to 12, 20 to 25, and 30 to 35 minutes).
The covariates and owned items came from the phase landmark. The penalties were four times the win model penalties, because a linear row has about four times the weight of a logistic row.
The split-half method of E1 measured reliability. The code is not in the repository, because the hypothesis failed.

**Result.** Growth effects were more reliable than win effects. The correlations were 0.87 to 0.97 for growth and 0.45 to 0.75 for win.
The hero-specific part (hero effect minus global effect) was less reliable.

| Adoption | Win, hero minus global | Growth, hero minus global |
| --- | --- | --- |
| Below 3% | 0.06 | 0.18 |
| 3% to 10% | 0.12 | 0.30 |
| 10% or more | 0.21 | 0.56 |

Growth effects did not agree with win effects. For global effects of items with an adoption of 3% or more, the correlation was −0.003 at 9 minutes, 0.335 at 20 minutes, and 0.204 at 30 minutes.
The largest growth effects belonged to economy items: Cultist Sacrifice, Monster Rounds, and Trophy Collector.
Cultist Sacrifice had a negative win effect at each phase, from −0.028 to −0.064.

The global win models gave these covariate coefficients. Two samples gave similar values.

| Phase | Relative net worth | Team lead | Rank |
| --- | --- | --- | --- |
| 9 minutes | −0.02 to −0.04 | 13.4 to 13.7 | about 0 |
| 20 minutes | −0.10 to −0.21 | 25.9 | about 0 |
| 30 minutes | −0.06 to +0.02 | 34.8 to 35.6 | about 0 |

**Analysis.** Growth measures soul income, not the match result.
After the team lead, the net worth of one player adds almost no information. An item affects the match result through the team lead.
One player has about one sixth of the team net worth. A growth of 3% adds about 0.0025 to the team lead, which is about 0.065 log-odds at 20 minutes.
Thus, the win model underrates economy items by a small amount. The data cannot separate this amount from the selection of players who buy these items.

Hero-specific win effects are mostly noise. This result agrees with the large hero penalty that E2 selected.

**Decision.** Do not use growth as the outcome. Do not change the win model for economy items.
