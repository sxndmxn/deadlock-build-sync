# Build method

## Decision

Make one build for every active hero.
Choose each CORE item from two values: how many players at this rank own the item, and how much the item adds to the win probability in similar game states.
Test each build on held-out matches and show the result as a confidence label.
Do not skip a hero because its evidence is weak. Show weak evidence as `limited` confidence.

The method replaces the earlier admission method.
The earlier method tested exact sets of 6 to 8 core items.
Two days after a patch, it gave builds for 2 to 8 of 40 heroes.
Exact sets divide the data into small groups, and one failed test removed the complete hero.

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

For each landmark, a logistic regression predicts the match result from the state.
The covariates are relative net worth, team lead, and rank.
Each item has one coefficient: its effect.

An effect compares players who own the item with players at the same time, wealth, team lead, and rank who spent the same souls on other items.
A positive effect means that the item wins more than the typical other use of those souls.

The analysis fits two levels of models:

1. A global model uses all heroes. Its item coefficients have a ridge penalty of 5.
2. A hero model uses one hero. Its ridge penalty of 100 pulls each item coefficient toward the global value.

Thus, a hero with few matches inherits the global estimate, and a hero with many matches uses its own data.
This is a simple form of hierarchical shrinkage.

## Build assembly

The build grows in three phases: lane at 9 minutes, mid game at 20 minutes, and late game at 30 minutes.
At each phase, the build keeps earlier items that still have a positive score, and then adds items in order of score.
An item enters only when the total cost stays within the median item spend of hero players at that phase, and the build owns at most 12 items.
When an item upgrades a component, the component leaves the owned set.

The item score is:

`ln(adoption / 0.03) + effect / 0.1`

Adoption is the share of hero players who own the item at that phase.
The first term keeps the build close to items that players at this rank use.
An item needs an adoption of 3% before the first term becomes positive.
The second term moves the choice toward items that win more in similar states.

MAIN CORE lists the added items by phase, and then by the median first purchase time.
The player buys MAIN CORE from left to right.

TIER 1 to TIER 4 list situational items: items outside MAIN CORE with an effect above 0.02 and an adoption of at least 1.5% at their most common phase.
Each tier shows at most six items.

The key item is the MAIN CORE item in Tier 3 or Tier 4 with the largest effect.
The power spike is the median net worth when players buy the key item.
The key ability is the first ability that the most common complete ability order upgrades to the maximum.

## Evaluation

The analysis assembles a second build from the matches outside the test fold.
In the test fold, agreement is the cost share of the build's phase set that the player owns.
A logistic regression predicts the match result from agreement, relative net worth, team lead, rank, and landmark.
The agreement coefficient is the change in log-odds from no agreement to full agreement.

| Confidence | Rule |
| --- | --- |
| `strong` | The coefficient minus two standard errors is above zero. |
| `moderate` | The coefficient is above zero. |
| `limited` | The coefficient is zero or less, or the test has fewer than 200 observations. |

The installed build uses all folds.

## Comparison with simpler choices

A prototype compared item choice by effect only, by adoption only, and by the score above.
The test used the patch of 2026-10-09 with data to 2026-10-11, Ritualist I to Eternus V, and 41 heroes.
The pooled agreement coefficient was 0.168 ± 0.028 for adoption only and 0.191 ± 0.028 for the score above.
The difference is small and within the uncertainty of two days of data.
The score above gives every hero a build that is at least as good as the most popular items.

## Limits

The data is observational. Effects describe outcomes in similar observed states.
They do not prove that an item causes a win.
Players buy some items because of the game state, for example defensive items against a strong enemy.
The covariates do not capture all of the game state.
Net worth at the landmark is also partly a result of earlier items.
