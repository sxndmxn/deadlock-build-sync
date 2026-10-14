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

**Method.** `compare_effect_models` fits the effect models on development matches for each penalty pair.
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

**Holdout.** The run `holdout-20260916` did not exist when the penalties were selected. It has 583,496 test states.
Compared with the penalties 5 and 100, no item effects gave +0.000515 ± 0.000086, and the penalties 200 and 300 gave −0.000133 ± 0.000023.
The penalties 1000 and 300 gave the same value. The selected penalties were best again.

**Decision.** Use the penalties 200 (global) and 300 (hero).

**Effect on the builds.** The run `20261012T233433Z` made builds with both penalty pairs.
For the main builds of 40 heroes, the mean Jaccard overlap of the CORE item sets was 0.78.
The key item changed for 12 heroes, and the confidence label changed for 7 heroes.
The catalog had 66 builds instead of 63. The labels were 10 `strong`, 32 `moderate`, and 24 `limited`, instead of 9, 36, and 18.
No item entered or left CORE for more than 5 heroes.

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

## E4: item effects that depend on the team lead

**Hypothesis.** Some items win more when the team is behind, and other items win more when the team is ahead.
This hypothesis would support an "IF BEHIND" panel.

**Method.** `compare_effect_models` with the design `200:300:lead=SCALE` adds one coefficient for each item on the team lead.
The design also adds a main term for the condition. The team lead already has a covariate, so this main term repeats it.
The standard deviation of the team lead is 0.056 to 0.072 at the phase landmarks. The scale multiplies the interaction value. A larger scale makes the penalty weaker.

**Result.** Each value is the log loss difference to the design `200:300` without interactions. The main term was not in this version of the test.

| Run | Scale 4 | Scale 16 | Scale 64 |
| --- | --- | --- | --- |
| `20261012T233433Z` | −0.000023 ± 0.000014 | +0.000061 ± 0.000058 | +0.001127 ± 0.000159 |
| `20261003T172322Z` | +0.000011 ± 0.000019 | +0.000290 ± 0.000093 | +0.002053 ± 0.000261 |
| `20260913T235155Z` | −0.000020 ± 0.000011 | +0.000058 ± 0.000030 | +0.000641 ± 0.000061 |

**Analysis.** With strong shrinkage, the interactions did not change the predictions significantly, and the sign was not stable. With weaker shrinkage, the predictions became worse.

**Decision.** Do not make an "IF BEHIND" panel. The data gives no evidence that item effects depend on the team lead.

## E5: item effects that depend on the enemy damage type

**Hypothesis.** Some items win more against enemy teams that deal more spirit damage.

**Method.** The landmark query now gives `enemy_spirit_share`: the mean spirit share of the five or six enemy heroes.
The spirit share of a hero is the share of its first item purchases, by cost, in the spirit slot. It uses all ranks and folds of the run.
Hero spirit shares were from 0.04 to 0.72. The enemy team mean was 0.436 with a standard deviation of 0.062.
`compare_effect_models` with the design `200:300:spirit=SCALE` adds a main term for the enemy spirit share and one interaction for each item.
The scale 0 keeps only the main term.

**Result.** Each value is the log loss difference to the design with only the main term.

| Run | No enemy term | Scale 2 | Scale 4 | Scale 8 |
| --- | --- | --- | --- | --- |
| `20261012T233433Z` | +0.000372 ± 0.000337 | −0.000009 ± 0.000009 | −0.000006 ± 0.000021 | +0.000042 ± 0.000043 |
| `20261003T172322Z` | +0.000477 ± 0.000097 | +0.000017 ± 0.000016 | +0.000072 ± 0.000042 | +0.000261 ± 0.000089 |
| `20260913T235155Z` | −0.000005 ± 0.000021 | −0.000002 ± 0.000007 | +0.000010 ± 0.000014 | +0.000055 ± 0.000024 |

**Analysis.** An earlier version of this test had no main term. It showed an improvement of 3.7 standard errors on one run.
The main term explains that improvement: the enemy composition predicts the match result on two runs.
The 156 item interactions add no information to the main term.

**Decision.** A test of all items at once cannot find counter items. Test a small group of items with a stated direction (E6).

## E6: defensive items against the matching damage type

**Hypothesis.** Spirit defense items win more against enemy teams with a high spirit share.
Weapon defense items win more against enemy teams with a low spirit share.

**Method.** `estimate_counter_interactions` fits one global model for each phase with all matches of the run.
The model adds a main term for the enemy spirit share and two interaction terms.
Each term is the number of owned items in one group multiplied by the standardized enemy spirit share.
The standard errors come from the model Hessian. They treat each state as independent, so they are too small.

The first groups were these items:

1. Spirit defense: Spirit Shielding, Enchanter's Emblem, Spirit Resilience, Counterspell, Witchmail, and Dispel Magic.
2. Weapon defense: Weapon Shielding, Battle Vest, Bullet Resilience, Metal Skin, Plated Armor, and Return Fire.

**Result for the groups.**

| Run | Phase | Spirit defense | Weapon defense |
| --- | --- | --- | --- |
| `20261012T233433Z` | 9, 20, 30 minutes | +0.002, +0.007, +0.020 | −0.051, −0.014, −0.034 |
| `20261003T172322Z` | 9, 20, 30 minutes | +0.022, +0.001, +0.015 | −0.038, −0.024, −0.025 |
| `20260913T235155Z` | 9, 20, 30 minutes | +0.006, +0.007, +0.008 | −0.031, −0.021, −0.038 |

All 18 signs agree with the hypothesis. On the largest run, the weapon defense values are 2.5 to 4.2 standard errors from zero.

**Result for each item.** The values pool three runs and three phases by inverse variance. The z values are too large, because the phases of one run share matches.

| Group | Item | Expected signs | Pooled value | z |
| --- | --- | --- | --- | --- |
| Weapon defense | Battle Vest | 9 of 9 | −0.020 | −3.8 |
| Weapon defense | Metal Skin | 6 of 9 | −0.058 | −3.6 |
| Weapon defense | Bullet Resilience | 7 of 9 | −0.057 | −3.0 |
| Weapon defense | Plated Armor | 5 of 9 | −0.057 | −2.7 |
| Weapon defense | Return Fire | 5 of 9 | −0.041 | −2.4 |
| Weapon defense | Weapon Shielding | 7 of 9 | −0.030 | −2.3 |
| Spirit defense | Spirit Resilience | 7 of 9 | +0.029 | +4.7 |
| Spirit defense | Spirit Shielding | 5 of 9 | +0.017 | +3.0 |
| Spirit defense | Enchanter's Emblem | 7 of 9 | +0.006 | +1.4 |
| Spirit defense | Witchmail | 4 of 9 | +0.006 | +0.4 |
| Spirit defense | Dispel Magic | 4 of 9 | −0.003 | −0.6 |
| Spirit defense | Counterspell | 4 of 9 | −0.013 | −1.8 |

**Analysis.** All six weapon defense items agree with the hypothesis.
Of the spirit defense items, only the two items that give spirit resist without another main function agree.
Counterspell blocks abilities, and Dispel Magic removes debuffs. They do not reduce spirit damage.
At the 10th and 90th percentiles of enemy teams, the difference is about 0.05 log-odds for each item.

The item assets cannot select these groups automatically.
The `IntrinsicallyProvidedInAbility` flag marks both own armor, such as Spirit Resilience, and enemy debuffs, such as Mystic Vulnerability.
Plated Armor has no resist property.

**Decision.** The spirit group was selected after the results were known. A run that did not take part in the selection must confirm it.

**Clustered errors.** The two teams of a match have opposite results, and the players of a team share one result.
`RidgeFit::clustered_standard_error` treats each match as one independent cluster.
For the final groups, the clustered errors were close to the earlier errors for weapon defense. They were up to two times larger for spirit defense at 9 minutes, because few players own these items in the lane phase.

The final groups were the six weapon defense items and two spirit defense items: Spirit Shielding and Spirit Resilience.

| Run | Phase | Spirit defense | Weapon defense |
| --- | --- | --- | --- |
| `20261012T233433Z` | 9, 20, 30 minutes | −0.014, +0.011, +0.021 | −0.051, −0.015, −0.036 |
| `20261003T172322Z` | 9, 20, 30 minutes | −0.016, +0.002, +0.022 | −0.039, −0.024, −0.027 |
| `20260913T235155Z` | 9, 20, 30 minutes | +0.035, +0.025, +0.033 | −0.031, −0.023, −0.042 |

**Holdout.** Before the test, these predictions were stated: weapon defense is negative at each phase, and spirit defense is positive at 20 and 30 minutes.
The holdout run `holdout-20260916` used the patch of 2026-09-16 to 2026-09-30 with 1,064,604 player matches. No selection run used these matches.

| Phase | Spirit defense | z | Weapon defense | z |
| --- | --- | --- | --- | --- |
| 9 minutes | +0.040 ± 0.019 | +2.2 | +0.012 ± 0.011 | +1.1 |
| 20 minutes | +0.031 ± 0.007 | +4.2 | −0.036 ± 0.008 | −4.8 |
| 30 minutes | +0.035 ± 0.008 | +4.7 | −0.052 ± 0.009 | −5.9 |

Four of five predictions passed by more than 4 standard errors. The weapon prediction at 9 minutes failed, without statistical significance.

**Decision.** Add counter panels for 20 and 30 minutes. Do not claim a counter effect in the lane phase.
Each run repeats the test with all of its matches. The first rule showed a panel only when its group had a positive coefficient, in the direction of its damage type, at both phases. E7 replaced this rule.
This rule removes a panel when a patch changes the items. A short run can give weak evidence, so the panel description states the z value of the run.

## E7: counter panel rule on short runs

**Hypothesis.** The first panel rule requires a positive counter coefficient at 20 and 30 minutes.
The counter effect is real, so this rule should keep the panels on short runs too.

**Method.** `measure_counter_windows` divides a run into windows with equal match counts, ordered by match identifier.
Match identifiers increase with time. The holdout run gave 5 windows of 17,744 matches, near the size of a three-day run.
Run `20260913T235155Z` gave 12 windows of 6,909 matches.

**Result.**

| Run | Matches for each window | Weapon rule passed | Spirit rule passed |
| --- | --- | --- | --- |
| `holdout-20260916` | 17,744 | 5 of 5 | 5 of 5 |
| `20260913T235155Z` | 6,909 | 6 of 12 | 10 of 12 |

The smallest z value of a group in a window was from −0.69 to 2.73.

**Analysis.** At the size of a three-day run, the rule kept all panels.
At about 7,000 matches, it removed a real panel in 8 of 24 cases. The default match range starts at the current patch, so a sync soon after a patch has few matches.
The four tested patches give strong prior evidence for the effect. Thus, a short run should need clear contrary evidence to remove a panel.

**Decision.** Remove a panel only when a phase has a z value below −2. In the 34 windows, this rule kept every panel.
A real reversal, for example after an item rework, still removes the panel when the run has enough matches.
The panel description now states the z value at each phase.

## E8: item effects that depend on rank

**Hypothesis.** Item effects differ between low and high ranks in the cohort, Ritualist I to Eternus V.
This hypothesis would support a separate build for each rank range.

**Method.** `compare_effect_models` with the design `200:300:rank=SCALE` adds one coefficient for each item on the standardized rank, minus its development mean.
The standardized rank is 0 at badge 80 and changes by 1 for each 20 badges. The scale 0 keeps only the main term, which repeats the rank covariate.

**Result.** Each value is the log loss difference to the design with only the main term.

| Run | Scale 0.25 | Scale 0.5 | Scale 1 |
| --- | --- | --- | --- |
| `20261012T233433Z` | +0.000005 ± 0.000014 | +0.000035 ± 0.000031 | +0.000125 ± 0.000056 |
| `20261003T172322Z` | −0.000001 ± 0.000012 | +0.000010 ± 0.000032 | +0.000082 ± 0.000070 |
| `20260913T235155Z` | +0.000013 ± 0.000006 | +0.000043 ± 0.000012 | +0.000120 ± 0.000023 |
| `holdout-20260916` | +0.000016 ± 0.000010 | +0.000056 ± 0.000018 | +0.000151 ± 0.000029 |

**Analysis.** The rank interactions did not improve the predictions on any run. Weaker shrinkage made the predictions worse.

**Decision.** Do not make separate builds for rank ranges inside the default cohort.

## E9: anti-heal items against enemy sustain

**Hypothesis.** Anti-heal items win more when the enemy team owns more healing and lifesteal items.

**Method.** The item assets defined both groups before the test.
Anti-heal items reduce the healing of enemies: Healbane, Toxic Bullets, Decay, Crippling Headshot, Inhibitor, and Spirit Burn.
Haunting Shot has the property, but it is not in the shop of any run. Cheat Death has the property as a cost to its own buyer.
Sustain items give healing or lifesteal: Bullet Lifesteal, Spirit Lifesteal, Leech, Siphon Bullets, Healing Rite, Healing Booster, Restorative Locket, Healing Nova, Healing Tempo, Rescue Beam, Melee Lifesteal, Lifestrike, Vampiric Burst, and Extra Regen.

`estimate_enemy_item_counters` uses the items that the enemy players own at the landmark, as players can see them in the game.
The condition is the summed cost of enemy sustain items, standardized within the phase.
The spirit defense group of E6 is a negative control. It has no stated relation to enemy sustain.

**First result.** The first model had only the sustain condition.
Anti-heal had a positive coefficient at 20 and 30 minutes on all four runs.
The control was negative on six of eight cells and reached z = −2.1 on the holdout run.
Many sustain items are weapon items, so a sustain-heavy team is often a weapon-heavy team.

**Adjusted result.** The final model also adds the enemy spirit share, with its own main term and group interactions.

| Run | Anti-heal z at 20 and 30 minutes | Control z at 20 and 30 minutes |
| --- | --- | --- |
| `20261012T233433Z` | 1.7, 0.7 | −0.4, 0.7 |
| `20261003T172322Z` | 0.9, 0.7 | −0.4, −0.3 |
| `20260913T235155Z` | 3.4, 2.9 | −0.4, −1.2 |
| `holdout-20260916` | 2.0, 2.0 | −1.0, −1.1 |

The anti-heal coefficients were from +0.008 to +0.016 log-odds for each item and each standard deviation of enemy sustain.

**Analysis.** After the adjustment, the control showed no effect. Anti-heal kept the predicted sign in all eight cells and was significant on the two large runs.
The effect is about one third of the armor effect of E6.

**Decision.** Add a VS SUSTAIN panel with the anti-heal items, from the mid game. Use the same contradiction rule as E7.

**Production.** The production test fits all three groups in one model for each phase, with both conditions.
On the holdout run, this joint model gave weapon defense z = 4.4 and 5.1, spirit defense z = 4.1 and 4.1, and anti-heal z = 2.2 and 2.0 at 20 and 30 minutes, with the share condition of E10.
On run `20261012T233433Z`, 57 builds had three panels and 9 builds had two panels.

## E10: debuff removal against enemy crowd control, and the enemy wealth check

**Hypothesis.** Debuff removal items win more when the enemy team owns more crowd control items.

**Method.** The groups were fixed before the test.
Debuff removal: Debuff Reducer, Dispel Magic, Unstoppable, and Indomitable.
Crowd control: the 17 shop items, present in all four runs, with a stun, silence, tether, or slow property in the item assets.
The spirit defense group of E6 was the negative control. The test used `estimate_enemy_item_counters`.

**First result.** With the summed cost of enemy crowd control items as the condition, debuff removal was negative at 20 and 30 minutes on all four runs, with z from −0.1 to −2.4.
The control showed no effect.

**Wealth check.** A richer enemy team owns more items of each kind. Thus, a summed cost also measures enemy wealth, and E9 used the same kind of condition.
The condition changed to the share of enemy item cost in the condition items. Both tests ran again.

| Test | z at 20 and 30 minutes: `20260913T235155Z`, `20261003T172322Z`, `20261012T233433Z`, holdout |
| --- | --- |
| Anti-heal against sustain share | 3.2, 2.7; 0.7, 0.6; 1.6, 0.9; 2.1, 1.7 |
| Control against sustain share | −0.5, −1.0; −0.0, −0.4; −0.4, 0.7; −1.0, −1.4 |
| Debuff removal against crowd control share | −0.7, −1.9; −1.2, −2.3; −0.2, −1.5; −1.6, −1.4 |
| Control against crowd control share | 0.5, −0.6; −1.2, −0.1; 0.3, −0.6; 0.6, 0.9 |

**Analysis.** The anti-heal result of E9 does not depend on enemy wealth.
Debuff removal won less, not more, against crowd control. Enemy wealth does not explain this result.
A possible cause is that players buy debuff removal after crowd control has already hurt them in the match. The data cannot separate this cause from others.
This result shows that the counter method measures associations, which can contain selection. The armor and anti-heal results passed stated predictions, negative controls, and a holdout, but they remain observational.

**Decision.** Use the share condition for VS SUSTAIN. Do not add a panel for debuff removal.
