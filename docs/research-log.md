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
Of the buyers of Healing Rite, 36% sell it and 51% use it as a component of an upgrade.
Entry E13 corrects an earlier value of 83% sold, which counted upgrades as sales.
Thus, ownership of Healing Rite at a late landmark identifies the rare players who neither sold nor upgraded it.

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

## E11: the evidence of additional builds

**Hypothesis.** An additional build (variant) describes a distinct winning path.
Thus, agreement with a variant predicts the match result beyond agreement with the main build.

**Method.** `compare_variant_agreement` assembles the main build and the variants of each hero from development matches, as production does.
For each test state of a hero with variants, one pooled model uses the main agreement and the largest variant agreement.
The covariates are relative net worth, team lead, rank, and landmark. The standard errors treat each match as one cluster.

**Result.**

| Run | Heroes with variants | Main agreement | z | Variant agreement | z |
| --- | --- | --- | --- | --- | --- |
| `20261012T233433Z` | 31 | −0.094 ± 0.051 | −1.8 | +0.100 ± 0.050 | +2.0 |
| `20261003T172322Z` | 30 | +0.156 ± 0.063 | +2.5 | −0.132 ± 0.066 | −2.0 |
| `20260913T235155Z` | 30 | +0.090 ± 0.020 | +4.6 | −0.012 ± 0.021 | −0.6 |
| `holdout-20260916` | 30 | +0.197 ± 0.021 | +9.3 | −0.092 ± 0.023 | −4.1 |

**Analysis.** On the two large runs, main agreement predicts winning, and variant agreement adds nothing or has a negative coefficient.
On the holdout run, players who move from the main build toward a variant win less in similar states.
On the small runs, the sign of the variant coefficient changes between runs.
The variants select players who own a key item. Their item combinations can reflect match conditions as well as strategies.

**Decision.** The data does not support the variants as better winning paths. They can remain as play style options with their own confidence labels.
The owner decides whether to keep them. No code change.

## E12: armor choices of players against the enemy team

**Hypothesis.** Players do not adapt their armor to the enemy damage type. If true, the counter panels give new information.

**Method.** A query of the holdout run divided players in matches longer than 30 minutes into fifths by the enemy spirit share.
It measured the share of players who own at least one item of each defense group of E6 at 30 minutes.

**Result.**

| Enemy spirit fifth | Mean enemy spirit share | Own weapon defense | Own spirit defense |
| --- | --- | --- | --- |
| 1 | 0.369 | 21.9% | 19.8% |
| 2 | 0.417 | 18.7% | 23.5% |
| 3 | 0.447 | 16.8% | 25.2% |
| 4 | 0.476 | 15.4% | 27.5% |
| 5 | 0.522 | 12.9% | 31.0% |

**Analysis.** Players adapt. They own weapon defense 1.7 times as often against the most weapon-heavy fifth, and spirit defense 1.6 times as often against the most spirit-heavy fifth.
E6 shows that matched armor still wins more at this level of adaptation.

**Decision.** Keep the counter panels. They support a correct habit and name the tested items.

## E13: item sales

**Hypothesis.** Players sell many early items, so the items could show when to sell them.

**Method.** A query of the holdout run classified the first purchase of each item.
A sale at the same second as the purchase of an upgrade that uses the item as a component is an upgrade, not a sale.
For upgraded Healing Booster, 98.6% of the recorded sales had the same time as the Healing Tempo purchase.

**Result.** Only two items with at least 2,000 buyers were sold by most buyers: Golden Goose Egg (94%) and Restorative Shot (66%).
Most other early items were upgraded, for example Headshot Booster (80%) and Extra Health (60%), or kept.
Healing Rite was sold by 36% of buyers and upgraded by 51%.

**Analysis.** The landmark ownership of the build method treats an upgraded component as not owned, which is correct.
A sell instruction would apply to very few items.

**Decision.** Do not add sell instructions. Do not set the Steam `sell_priority` field, because its display in the game client is not verified.

## E14: a paired test of the effect scale

**Hypothesis.** Builds with the effect scale 0.05 add held-out signal beyond builds with the scale 0.1.

**Method.** On the two large runs, the E0 comparison with the penalties of E2 gave these agreement coefficients:

| Scale | `20260913T235155Z` | `holdout-20260916` | Rare CORE share |
| --- | --- | --- | --- |
| `inf` | 0.002 ± 0.010 | 0.040 ± 0.010 | 0% |
| 0.1 | 0.085 ± 0.010 | 0.113 ± 0.010 | 0% to 1.3% |
| 0.05 | 0.117 ± 0.010 | 0.124 ± 0.010 | 1.0% to 7.1% |
| 0.025 | 0.195 ± 0.010 | 0.200 ± 0.011 | 20.0% to 20.3% |

These coefficients use the same states, so separate standard errors cannot test a difference.
`compare_scoring_pair` assembles both builds of each hero from development matches and fits one model with both agreements on the test states.
The coefficient of the second agreement measures its signal beyond the first. The standard errors treat each match as one cluster.

**Result.**

| Run | 0.05 beyond 0.1 | 0.1 beyond `inf` |
| --- | --- | --- |
| `20261012T233433Z` | +0.212 ± 0.045 (z = 4.7) | +0.066 ± 0.035 (z = 1.9) |
| `20261003T172322Z` | +0.045 ± 0.065 (z = 0.7) | +0.047 ± 0.050 (z = 0.9) |
| `20260913T235155Z` | +0.120 ± 0.020 (z = 6.0) | +0.209 ± 0.021 (z = 10.1) |
| `holdout-20260916` | +0.088 ± 0.025 (z = 3.6) | +0.174 ± 0.019 (z = 9.0) |

**Analysis.** The 0.05 builds added signal beyond the 0.1 builds on all four runs, and significantly on three.
The 0.1 builds added clear signal beyond adoption alone on the two large runs.
The limit of E0 remains: the test measures associations that repeat in later matches, not proven causes.
The scale 0.025 again put many rare items in CORE. A further search on these four runs could fit their specific matches, so the search stopped at 0.05.

**Decision.** Use the effect scale 0.05 for CORE items. Keep the scale 0.1 for the key item value, which this test did not cover.

## E15: confirmation on new matches

**Purpose.** E2, E14, and the counter groups were tuned or selected on the same four runs. A confirmation needs matches that no earlier run used.

**Method.** The run `confirm-20261003` used the patch of 2026-09-30 from 2026-10-03 17:23, the end of run `20261003T172322Z`, to 2026-10-09 21:00, the start of the next patch.
It had 46,211 matches and 554,532 player matches. These predictions were stated before the extraction:

1. P1: the penalties 200 and 300 give a lower held-out log loss than the penalties 5 and 100.
2. P2: builds with the effect scale 0.05 add a positive coefficient beyond builds with the scale 0.1.
3. P3: the weapon defense, spirit defense, and anti-heal groups have positive production coefficients at 20 and 30 minutes.

**Result.**

| Prediction | Result | Status |
| --- | --- | --- |
| P1 | −0.000147 ± 0.000043 against the penalties 5 and 100. No item effects gave +0.000404 ± 0.000132. | Confirmed |
| P2 | +0.180 ± 0.031, z = 5.9 | Confirmed |
| P3, weapon defense | z = 2.8 and 2.1 | Confirmed |
| P3, anti-heal | z = 1.9 and 2.5 | Confirmed |
| P3, spirit defense | z = −0.2 and −0.2 | Not confirmed |

**Analysis.** The penalties, the effect scale, the weapon defense panel, and the anti-heal panel held on new matches.
The spirit defense effect was positive on four earlier runs but zero on these matches. It is less stable than the weapon defense effect.

**Decision.** Keep all three panels. The E7 rule removes a panel only for a z value below −2.
The VS SPIRIT description states the z value of each run, so a player can see weak evidence on a patch.
Repeat this confirmation after each method change, with a match window that no earlier test used.

## E16: an adoption floor for CORE items

**Hypothesis.** At the effect scale 0.05, 1% to 7% of CORE items have an adoption below 3%.
A hard adoption floor of 3% removes these items without a loss of held-out signal.

**Method.** `ItemScoring` has an optional adoption floor. The rule `0.05:0.03` blocks items with an adoption below 3%.
`compare_scoring_pair` compared the rule `0.05` (base) and `0.05:0.03` (alternative) on five runs.
The prediction was that the alternative coefficient is not significantly negative on any run.

**Result.**

| Run | Base coefficient | Alternative coefficient |
| --- | --- | --- |
| `20261012T233433Z` | −0.783 ± 0.240 | +0.930 ± 0.237 (z = 3.9) |
| `20261003T172322Z` | −1.038 ± 0.284 | +1.079 ± 0.280 (z = 3.8) |
| `20260913T235155Z` | +0.082 ± 0.070 | +0.036 ± 0.069 (z = 0.5) |
| `holdout-20260916` | −0.380 ± 0.086 | +0.513 ± 0.087 (z = 5.9) |
| `confirm-20261003` | +0.718 ± 0.139 | −0.586 ± 0.138 (z = −4.3) |

**Analysis.** The two builds differ in one or two items. Thus, the two agreements are almost the same variable, and the model divides their common effect in an unstable direction.
The large coefficients with opposite signs show this problem. The prediction failed on the confirmation run.
The paired test of E14 is valid only when the two builds differ clearly. At the scales 0.1 and 0.05, the CORE overlap was 0.70.

**Decision.** Keep the floor at 0 in production. The floor remains an option of the experiment examples.

## E17: reliability of the confidence label

**Hypothesis.** The confidence label of a build measures that hero's build. Thus, a hero gets similar results on two halves of the same test matches.

**Method.** `measure_label_halves` assembles each main build from development matches.
It tests the build separately on test matches with even and odd identifiers and correlates the coefficients across heroes.

**Result.**

| Run | Heroes | Correlation of halves | Same label | Builds with a positive mean coefficient |
| --- | --- | --- | --- | --- |
| `20261012T233433Z` | 41 | 0.405 | 25 | 76% |
| `confirm-20261003` | 40 | 0.021 | 14 | 80% |
| `holdout-20260916` | 38 | 0.019 | 15 | 92% |

**Analysis.** On the two large runs, the halves did not correlate. The differences between heroes are mostly noise, and the per-hero labels are not reliable.

**Second hypothesis.** A hierarchical estimate predicts the other half better than the build's own result.
The estimate moves each even-half coefficient toward the precision-weighted mean of all heroes.
The size of the move comes from the variance between heroes beyond the noise, estimated from the even half only. The prediction was fixed before the calculation.

| Run | Mean squared error, own result | Hierarchical estimate | Mean of all heroes |
| --- | --- | --- | --- |
| `20261012T233433Z` | 0.104 | 0.076 | 0.085 |
| `confirm-20261003` | 0.123 | 0.075 | 0.049 |
| `holdout-20260916` | 0.044 | 0.031 | 0.031 |

The hierarchical estimate was better than the own result on all three runs. The mean of all heroes was better on two runs, which agrees with small real differences between heroes.

**Decision.** Set the label from the hierarchical estimate, with separate pools for main builds and additional builds.
Keep the own result in the catalog field `hero_estimate`.
On the holdout run, 34 of 38 main builds became `strong`. On the short run `20261012T233433Z`, the estimated variance between heroes was larger, and 10 main builds stayed `limited`.

## E18: the effect term in each game phase

**Hypothesis.** Item choices matter less in the lane phase, so adoption alone is as good as the installed score rule at 9 minutes.

**Method.** `compare_scoring_by_landmark` assembles each hero's build from development matches with the rules `inf` and `0.05`.
It tests the builds of each rule, pooled over heroes, separately at each test landmark.

**Result.** Each cell gives the agreement coefficient for the rules `inf` and `0.05`.

| Landmark | `holdout-20260916` | `confirm-20261003` | `20260913T235155Z` |
| --- | --- | --- | --- |
| 9 minutes | 0.069, 0.133 | 0.060, 0.167 | 0.010, 0.092 |
| 15 minutes | 0.033, 0.089 | 0.025, 0.069 | 0.004, 0.089 |
| 20 minutes | 0.054, 0.179 | 0.092, 0.227 | 0.039, 0.191 |
| 25 minutes | −0.027, 0.194 | 0.000, 0.265 | −0.009, 0.186 |
| 30 minutes | 0.069, 0.316 | 0.030, 0.264 | 0.024, 0.259 |

The standard errors were from 0.016 to 0.059.

**Analysis.** The installed rule was better at each landmark on each run, also at 9 minutes. Its advantage grew in later phases.
Adoption alone had almost no held-out signal after 15 minutes.

**Decision.** Keep one effect scale for all phases.

## E19: the amount of match data

**Hypothesis.** More development matches give better builds. Thus, a sync soon after a patch gives weaker builds.

**Method.** `compare_training_fractions` keeps the earliest fraction of the development matches, by match identifier.
It estimates the item effects and assembles the builds from that fraction. All fractions use the same test matches and the installed score rule.

**Result.** Each cell gives the pooled agreement coefficient. The standard errors were from 0.0097 to 0.0104.

| Run | 10% | 25% | 50% | 100% |
| --- | --- | --- | --- | --- |
| `holdout-20260916` | 0.164 (7,098 matches) | 0.117 | 0.104 | 0.124 (70,973 matches) |
| `20260913T235155Z` | 0.114 (6,633 matches) | 0.109 | 0.110 | 0.117 (66,323 matches) |

**Analysis.** Builds from about 7,000 matches tested as well as builds from ten times more matches. At this rank range, that is one to two days after a patch.
The ridge penalties of E2 keep the estimates stable with few matches. This test cannot show small differences.
The counter tests need more matches: E7 found stable results at about 18,000 matches.

**Decision.** No change. A sync one or two days after a patch gives builds of full test quality.

## E20: armor penetration against enemy armor

**Hypothesis.** Armor penetration items win more when the enemy team owns more armor of the matching type.

**Method.** `estimate_enemy_item_counters` ran two tests on five runs, with anti-heal as the negative control. The predictions were fixed before the test.

1. Weapon penetration (Bullet Resist Shredder, Armor Piercer, and Hunter's Aura) against the enemy share of the six weapon defense items of E6.
2. Spirit penetration (Mystic Vulnerability and Escalating Exposure) against the enemy share of Spirit Shielding, Spirit Resilience, Enchanter's Emblem, Witchmail, and Diviner's Kevlar.

**Result.** The table gives the z values at 20 and 30 minutes on the runs `20261003T172322Z`, `20261012T233433Z`, `20260913T235155Z`, `confirm-20261003`, and `holdout-20260916`.

| Test | z values | Positive |
| --- | --- | --- |
| Weapon penetration | −0.3, −2.4, −0.0, 0.9, −1.9, −1.1, 0.7, −1.1, −0.0, −0.3 | 2 of 10 |
| Control | 0.9, 1.2, −0.7, 0.3, 1.6, −0.7, −0.0, 0.4, 1.4, 1.2 | 7 of 10 |
| Spirit penetration | 0.5, −0.3, −1.4, −1.3, −2.1, −1.0, 1.3, 0.6, −0.6, −1.9 | 3 of 10 |
| Control | −0.5, 0.4, 0.8, −1.0, 0.3, −0.4, −0.9, 1.2, 1.2, 1.3 | 6 of 10 |

**Analysis.** Neither penetration group won more against armored enemies. The tendency was slightly negative. The controls showed no effect.
A possible cause is that players buy armor when they are behind, so armor-heavy enemy teams are often weaker than their net worth shows. The data cannot separate this cause from others.

**Decision.** Do not add a penetration panel.
