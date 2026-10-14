# Build method

## Overview

The analysis makes the builds in these steps:

1. Extract the ranked matches of the current patch and record each player's state at fixed landmark times. See [Data](#data).
2. Estimate how much each item adds to the win probability in similar game states, with strong shrinkage of rare and hero-specific values. See [Item effects](#item-effects).
3. Assemble MAIN CORE phase by phase from items that players use, tilted toward items that win more. See [Build assembly](#build-assembly).
4. Add situational TIER items and, for heroes with distinct item combinations, additional builds. See [Additional builds](#additional-builds).
5. Test the counter item groups on the run and add the VS panels that the run does not contradict. See [Counter panels](#counter-panels).
6. Test each build on held-out matches and set its confidence label with the evidence of all heroes. See [Evaluation](#evaluation).

The [Research log](research-log.md) records the tests behind each value and each rejected idea.

## Decision

Make a build for every active hero. Hero coverage does not limit each hero to one build.
Choose each CORE item from two values: how many players at this rank own the item, and how much the item adds to the win probability in similar game states.
Test each build on held-out matches and show the result as a confidence label.
Do not skip a hero because its evidence is weak. Show weak evidence as `limited` confidence.

The method replaces the earlier admission method.
The earlier method tested exact sets of 6 to 8 core items.
Two days after a patch, it gave builds for 2 to 8 of 40 heroes.
Exact sets divide the data into small groups, and one failed test removed the complete hero.

## Build identity

Catalog schema 8 permits multiple builds for the same hero and requires item purchase counts.
It adds counter evidence to the catalog and counter panels to each build.
Each additional build has a stable `variant_id` with lowercase letters, digits, or hyphens.
The identifier has 1 to 80 characters. It does not depend on the title or catalog order.
Steam uses the hero ID and variant identifier to update each build separately.
Validation rejects duplicate hero and build path pairs.
The hero's Markdown file contains all its catalog builds.

A missing `variant_id` means `main`, which preserves existing Steam build identities.
Schema 5 remains readable when builds omit `variant_id`. Schema 6 remains readable with its variant identifiers.
Legacy catalogs without purchase counts show unavailable item rates.
Schema 7 with method `item-effect-variants-v2` remains readable without counter panels.
Schema 8 uses method `item-effect-counters-v1`.
The main build keeps its existing identity. Additional builds use `item-ITEM_ID` as their variant identifier.

## Data

The analysis extracts ranked matches from the public Deadlock data lake.
The default rank range is Ritualist I to Eternus V.
The default time range starts at the current patch.

For each player, the analysis records the game state at eight landmark times: 6, 9, 12, 15, 20, 25, 30, and 35 minutes.
The snapshots at these times are exact, so the analysis does not interpolate.
Each state contains these values:

1. The items that the player owns at that time. An item that the player sold before that time is not owned.
2. The player's net worth.
3. The team lead: own team net worth minus enemy team net worth, divided by their sum.
4. The average match rank.
5. The match result.

The analysis divides matches by start time.
The last 20% of matches is the test fold.

## Item effects

For each assembly phase, a logistic regression predicts the match result from the state.
The covariates are relative net worth, team lead, and rank.
Each item has one coefficient: its effect.

An effect compares players who own the item with players at the same time, wealth, team lead, and rank who spent the same souls on other items.
A positive effect means that the item wins more than the typical other use of those souls.

The analysis fits two levels of models:

1. A global model uses all heroes. Its item coefficients have a ridge penalty of 200.
2. A hero model uses one hero. Its ridge penalty of 300 pulls each item coefficient toward the global value.

Thus, a hero with few matches inherits the global estimate, and a hero with many matches uses its own data.
This is a simple form of hierarchical shrinkage.

Held-out log loss selected these penalties on three patches. The earlier penalties of 5 and 100 left rare items with large, unreliable effects.
After net worth, team lead, and rank, item ownership adds little information about the match result.
See [Research log](research-log.md) entries E1 and E2.

## Build assembly

The build grows in three phases: lane at 9 minutes, mid game at 20 minutes, and late game at 30 minutes.
At each phase, the build keeps earlier items that still have a positive score, and then adds items in order of score.
An item enters only when the total cost stays within the median item spend of hero players at that phase, and the build owns at most 12 items.
When an item upgrades a component, the component leaves the owned set.

The item score is:

`ln(adoption / 0.03) + effect / 0.05`

Adoption is the share of hero players who own the item at that phase.
The first term keeps the build close to items that players at this rank use.
An item needs an adoption of 3% before the first term becomes positive. It also needs this adoption to enter CORE at all, whatever its effect (E30).
The second term moves the choice toward items that win more in similar states.
A paired held-out test on four patches selected the effect scale 0.05 over the earlier 0.1. See [Research log](research-log.md), entry E14.

MAIN CORE orders items by median net worth at first purchase, then median first purchase time.
The player buys MAIN CORE from left to right.

TIER 1 to TIER 4 list situational items: items outside MAIN CORE with an effect above 0.02 and an adoption of at least 1.5% at their most common phase.
Each tier shows at most six items.

The main build selects its key item from Tier 3 or Tier 4 CORE items.
The selection combines effect with the hero's adoption divided by adoption across all heroes.
The power spike is the median net worth when players buy the key item.
The ability order identifies the first ability upgraded to the maximum.
The inferred ability focus can differ from that ability.

## Additional builds

Each hero keeps its main build. The selector can add up to two builds from distinct observed item combinations.
This limit controls the number of installed entries. It does not establish the number of viable strategies for a hero.
The selector uses development matches and excludes the test fold.

A candidate key item must be Tier 3 or Tier 4 and have a positive hero effect.
Its hero adoption must be 5% to 70% at 20 or 30 minutes.
The item must have at least 100 distinct player matches with ownership at either time.
Repeated landmark snapshots do not increase this owner count.

The candidate uses those players' earlier and later item states.
At each phase, the selector recalculates item adoption, owner win rates, and median item spend for those players.
It retains the hero effect estimates and the existing assembly score.
Each phase needs at least 100 owner states. The candidate must include its key item in CORE.
Purchase net worth windows and imbue selections still use the complete hero cohort for each item.

The selector compares Tier 3 and Tier 4 CORE items to reject similar builds.
Each build must have at least two items that the other build does not contain.
Different items must account for at least 30% of the combined unique item cost.
Selection maximizes that cost difference multiplied by the square root of the distinct owner count.
The selector repeats this comparison against the main build and each selected additional build.

Production rebuilds the selected item strategies with all source folds and checks separation again.
Each additional build gets its own held-out evaluation from its development purchase sets.
Ability order selection uses matches that include the variant's key item.
Insufficient ability evidence leaves the order unset.

## Counter panels

Each build can show three panels between MAIN CORE and TIER 1, from the mid game:

1. **VS WEAPON**: defensive items for an enemy team that deals mostly weapon damage.
2. **VS SPIRIT**: defensive items for an enemy team that deals mostly spirit damage.
3. **VS SUSTAIN**: anti-heal items for an enemy team that buys healing and lifesteal items.

The spirit share of a hero is the share of its first item purchases, by cost, in the spirit slot.
The enemy spirit share is the mean spirit share of the enemy heroes. A low enemy spirit share means more weapon damage.
The enemy sustain is the share of enemy item cost in healing and lifesteal items at the landmark. A share describes the enemy build without its wealth.
Players can see these enemy items in the game.

Fixed item groups define the panels:

1. Weapon defense: Battle Vest, Weapon Shielding, Bullet Resilience, Metal Skin, Plated Armor, and Return Fire.
2. Spirit defense: Spirit Shielding and Spirit Resilience.
3. Anti-heal: Healbane, Toxic Bullets, Decay, Crippling Headshot, Inhibitor, and Spirit Burn.

The sustain condition uses Bullet Lifesteal, Spirit Lifesteal, Leech, Siphon Bullets, Healing Rite, Healing Booster, Restorative Locket, Healing Nova, Healing Tempo, Rescue Beam, Melee Lifesteal, Lifestrike, Vampiric Burst, and Extra Regen.
The analysis finds the items by their class names. Items that a patch removes leave their group.
Item asset properties cannot select the defensive groups. One flag marks both own armor and debuffs on enemies.

Each run tests all groups at 20 and 30 minutes with all of its matches, in one global logistic model for each phase.
The model has a main term for the standardized enemy spirit share and a main term for the standardized enemy sustain.
The model also has hero terms, so the group terms compare players of the same hero (E31 in the research log).
For each group and each condition, it adds the number of owned group items multiplied by the condition.
The weapon and spirit groups use the spirit share terms. The anti-heal group uses the sustain terms.
The standard errors treat each match as one independent cluster.
A panel appears unless the run contradicts its group: a z value below −2 at a phase removes the panel.
Four patches confirmed the effects, so a short run with weak evidence keeps the panel.

A panel holds at most four group items outside MAIN CORE. Each item needs a hero adoption of at least 1% at 20 or 30 minutes.
The panel orders the items by adoption. The panel description states the z value of the run test at each phase.

See [Research log](research-log.md), entries E6, E7, and E9.
For defensive items, the difference between the 10th and 90th percentiles of enemy teams is about 0.05 log-odds for each item.
The anti-heal effect is about one third of this size.
The tests did not confirm a counter effect at 9 minutes.
The data is observational. Players can buy these items because of the enemy team, so the tests cannot prove that an item causes a win.

## Displayed item rates

Displayed item rates use all selected ranked player matches for that hero, including all source folds.
The query excludes calibration matches and applies the selected rank range.
Each player's first purchase of an item counts once per match. Later purchases of the same item do not count again.
Item win rate is buyer wins divided by buyer matches.
Pick rate is buyer matches divided by all eligible matches for that hero, including players who never bought the item.
Both rates show their numerator and denominator.

These counts include purchases at any time. They do not require ownership at a landmark or ownership of a variant's key item.
The same hero and item have identical display rates across all variants and phases.
Phase adoption and phase owner win rates remain assembly data. The presentation never substitutes them for missing purchase counts.
Validation requires positive buyer counts, wins no greater than buyers, and buyers no greater than hero matches.
It also rejects inconsistent counts across builds for the same hero and item.

These are observed item purchase statistics, not the complete build's win rate.
Purchase timing and the game state can affect which players buy an item. The rates do not prove that an item causes wins.

## Item imbue selection

MAIN CORE and situational items can include a native imbue target.
The analysis counts recorded targets on each player's first purchase of an item.
It uses the selected rank range and all source folds, and excludes calibration matches and empty targets.
The target needs at least 20 observations and more than half of the recorded targets for that hero and item.
Ties and weaker evidence leave the selection empty.

The current item asset must declare a recognized imbue type.
The target must belong to the hero and appear in the selected ability order.
Items that exclude ultimate abilities cannot select an ultimate ability.
These checks use current assets and observed selections. They do not model every ability compatibility rule.
The catalog stores the target identifier, its observation count, and the total recorded target count.
Steam receives the target through its native item field.
The build confidence label does not evaluate the imbue choice.

## Ability focus and titles

The focus selector uses supported imbue targets from MAIN CORE.
Current asset properties must identify a direct ability improvement, such as extra charges, spirit power, range, duration, damage, or reduced cooldown.
Items with reload effects or weapon damage triggers do not count as focus evidence.
Missing or unrecognized properties do not count. Situational items do not count.

All qualifying CORE targets must name the same ability.
That ability must belong to the hero and appear in the selected ability order.
The key item must support it, at least two CORE items must support it, or the first fully upgraded ability must match it.
Conflicting targets leave the focus unset. Ability upgrade order alone does not establish a focus.

The catalog stores the focus identifier, name, and supporting CORE item identifiers.
The title uses `ability + key item` when a focus exists.
Without a focus, the title names the first fully upgraded ability from the selected complete ability order.
This title fallback does not establish an inferred focus or change the description.
The title uses only the key item when no supported ability name is available.
The first icon shows the focus when available. Otherwise, it shows the first fully upgraded ability when the ability order exists.
The description states the focus and ability upgrade order separately.
The focus is an inference from observed choices and item properties. The build confidence label does not evaluate this inference.

Steam titles add the player name with `player name | title` and never add the hero name.
The title uses only the key item if the ability and item exceed 50 characters.
The formatter omits the player name if the complete title exceeds that limit.

## Evaluation

The analysis assembles each evaluated build from matches outside the test fold.
In the test fold, agreement is the cost share of the build's phase set that the player owns.
A logistic regression predicts the match result from agreement, relative net worth, team lead, rank, and landmark.
The agreement coefficient is the change in log-odds from no agreement to full agreement.

| Confidence | Rule |
| --- | --- |
| `strong` | The coefficient minus two standard errors is above zero. |
| `moderate` | The coefficient is above zero. |
| `limited` | The coefficient is zero or less, or the test has fewer than 200 observations. |

The test of one build is noisy. In split-half tests, the coefficients of different heroes did not correlate on the large runs.
The standard error treats each match as one cluster, because the landmarks of one player share one result.
Thus, the label uses a hierarchical estimate. Each coefficient moves toward the precision-weighted mean of comparable builds: main builds or additional builds.
The size of the move depends on the variance between builds beyond their noise. A build keeps more of its own result when that variance is large or its own error is small.
The catalog keeps the result of the build alone, and the Markdown file shows both values. See [Research log](research-log.md), entry E17.

The installed build uses all folds.

## Comparison with simpler choices

A prototype compared item choice by effect only, by adoption only, and by the score above.
The test used the patch of 2026-10-09 with data to 2026-10-11, Ritualist I to Eternus V, and 41 heroes.
The pooled agreement coefficient was 0.168 ± 0.028 for adoption only and 0.191 ± 0.028 for the score above.
The difference is small and within the uncertainty of two days of data.
This comparison does not establish that the score gives every hero a better build than item popularity alone.

The `compare_item_scoring` example repeats this comparison for any extracted run:

```bash
cargo run --release -p deadlock-analysis --example compare_item_scoring -- RUN_DIRECTORY [EFFECT_SCALE ...]
```

It estimates item effects once from development matches.
Each effect scale then assembles every hero's build, and one pooled model tests all builds on the test fold.
The effect scale `inf` selects by adoption only. The output is tab-separated text.

The run of 2026-10-12 used the patch of 2026-10-09, Ritualist I to Eternus V, 41 heroes, and 246,495 test states.

| Effect scale | Agreement coefficient | Strong | Moderate | Limited |
| --- | --- | --- | --- | --- |
| `inf` (adoption only) | 0.078 ± 0.021 | 12 | 15 | 14 |
| 0.4 | 0.115 ± 0.020 | 12 | 13 | 16 |
| 0.2 | 0.098 ± 0.020 | 10 | 18 | 13 |
| 0.1 (installed) | 0.089 ± 0.020 | 9 | 21 | 11 |
| 0.05 | 0.100 ± 0.020 | 9 | 20 | 12 |
| 0.025 | 0.281 ± 0.021 | 9 | 28 | 4 |

The scales from `inf` to 0.05 are within the uncertainty of each other.
The scale 0.025 gives a much larger coefficient. This result does not alone justify a change of the installed scale.
The test and the item effects use the same adjustment for net worth, team lead, and rank.
Thus, an item that players buy because they win can increase both values. The test can repeat the bias of the effect estimate.
A test that does not share this bias is necessary before a change of the installed scale.
This table uses the earlier ridge penalties of 5 and 100 and the earlier effect scale 0.1. See [Research log](research-log.md) for the results with the current values.

## Limits

The data is observational. Effects describe outcomes in similar observed states.
They do not prove that an item causes a win.
Players buy some items because of the game state, for example defensive items against a strong enemy.
The covariates do not capture all of the game state.
Net worth at the landmark is also partly a result of earlier items.
Variant owners must survive long enough and acquire enough souls to own the key item.
Their item combinations can reflect match conditions as well as different strategies.
The selection thresholds are engineering rules. They do not prove an optimal number of builds.
A held-out test with hero and landmark indicators found that variant agreement adds a small positive signal beyond main build agreement on seven runs.
The signal is weak on each run. See [Research log](research-log.md), entries E11 and E30.
