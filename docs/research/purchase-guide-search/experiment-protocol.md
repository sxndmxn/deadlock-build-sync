# Purchase-guide search experiment protocol

## Question

Determine whether additional search improves valid, supported purchase guides enough to justify its runtime and display cost.
Compare greedy state-aware ranking, constrained beam search, diverse beam search, ECLAT plus beam search, and Leiden plus beam search.
Keep the item scorer, purchase rules, data partitions, and query scenarios identical across methods.

The experiment uses an isolated tool package.
It does not change production guide selection, admission, or Steam installation.

## Data boundary

Use saved run `20260909T001949Z` with source snapshot version 64.
The cohort contains 89,979 matches and 38 heroes.
Use all available heroes, including lower-support heroes.
The latest recorded balance patch is the 2026-08-22 update.
The source item catalog has client version 6686.
Per-match client versions are unavailable in the extracted tables.
Treat the patch date and asset hashes as the study context, not as proof of each match's exact client version.
Do not pool another patch into this model.

| Partition | Matches | Purpose |
| --- | ---: | --- |
| Training | 53,987 | Item estimates, purchase windows, itemsets, and item graph |
| Validation | 17,996 | Algorithm development and parameter selection |
| Reserved test | 17,996 | Final evaluation after configuration freeze |

Keep every player and purchase from one match in its existing chronological partition.
Earlier Infernus analysis used validation data.
Therefore, validation results are development results throughout this experiment.
Do not inspect test outcomes before freezing methods and parameters.
Record the frozen configuration and code hashes before final test evaluation.
Report any later correction or repeated test evaluation explicitly.

## Observations

Use first purchases of an item within a match for item win-rate counts.
Exclude same-second purchase groups from the action prediction sample.
Use strictly earlier personal and team observations.
Require observed personal net worth and complete team snapshots within the declared freshness limit.
Do not replace missing relative wealth with an even state.
Count each match once within an item-state cell.
Use distinct matches for state baselines.

The state contains hero, patch context, current inventory, personal net worth, relative wealth, cash, and remaining purchase budget.
Relative wealth uses personal net worth divided by mean lobby net worth.
Use the existing below-0.90, 0.90-through-1.10, and above-1.10 state boundaries.
Use fixed net-worth bins before inspecting validation outcomes.

Recorded cash is unavailable.
Use explicit cash assumptions for hypothetical guide scenarios and action replay.
Report those assumptions with the results.
A purchase converts cash into an item; it does not increase net worth by its price.
Only simulated additional income increases projected net worth.
Do not use final net worth, future purchases, or match outcomes as search features.

## Common item estimate

Estimate each item's win rate within hero, patch, net-worth bin, and relative-wealth state.
Use an empirical-Bayes beta prior centered on the corresponding training state baseline.
For wins `w`, purchases `n`, prior mean `p`, and prior strength `k`, use:

```text
alpha = w + k * p
beta = n - w + k * (1 - p)
posterior_mean = alpha / (alpha + beta)
posterior_variance = alpha * beta / ((alpha + beta)^2 * (alpha + beta + 1))
```

The prior mean is an estimate from training data.
Conditional posterior intervals do not include all uncertainty in that estimated prior.
Report raw counts alongside smoothed estimates.
Prior strength is a weight, not an observed match count.
Do not add that weight to displayed support counts.
Evaluate prediction calibration on separate matches.

The common action utility uses the posterior difference from the state baseline, an uncertainty penalty, and incremental cash cost.
The path score adds discounted action utilities.
This score is a search heuristic, not a predicted build win rate.
The same match outcome can contribute to several item estimates.
Do not interpret their sum as a treatment effect or a probability.

Start with prior strength 100, net-worth bin width 4,000, minimum cell support 30, and uncertainty multiplier 0.5.
Start with cost exponent 0.5 and step discount 0.97.
Evaluate declared sensitivity settings on validation before freezing the final configuration.

## Common purchase rules

- Require a current, enabled catalog item.
- Reject repeated item actions within the generated path.
- Respect the ownership and active-item limits.
- Respect known inventory capacity and explicit flex capacity.
- Credit directly owned components once when calculating an upgrade price.
- Consume those components when applying the upgrade.
- Reject purchases that exceed the remaining explicit budget.
- Require the same statistical support floor for every search method.
- Keep unsupported state extrapolation visible as an abstention.
- Do not invent item sales, ability imbues, or objective-dependent capacity.

Use the production mechanics functions as an independent purchase-validation reference.
Test the optimized search transition against that reference.

## Search methods

Greedy retains one best continuation at each step.
Constrained beam retains the best `B` continuations under the common path score.
Test beam widths 4, 8, 16, 32, and 64 where runtime permits.
Test multiple search depths and budget scenarios.

Diverse beam changes frontier retention to reduce overlap among retained inventories.
It keeps the common item score and final path ranking unchanged.
This is an adaptation of diverse beam search, not a claim to reproduce its language-generation experiments.
Measure distinct final inventories separately from purchase-order differences.

ECLAT mines supported itemsets only from training inventory records.
Leiden uses a training item co-ownership graph with explicit weights, resolution, and seed.
Their structures guide frontier exploration.
They do not add a win-rate bonus or exempt a purchase from the common rules.
Keep an unrestricted portion of the frontier so a structural proposal cannot remove every alternative.
Report preparation time separately from search time.
Test structure support, graph resolution, and seed sensitivity.

## Evaluation independent of the search score

| Measure | Definition | Limitation |
| --- | --- | --- |
| Purchase validity | Independent replay checks every action and cost | Hypothetical cash and capacity remain explicit assumptions |
| Action agreement | Recommended next item matches a held-out observed next purchase | Agreement measures behavior prediction, not benefit |
| Alternative agreement | One returned alternative starts with the observed next purchase | Compare equal alternative counts where possible |
| Sequence coverage | Held-out ownership or ordered purchases support returned combinations | State the checkpoint and permit extra items explicitly |
| Observed outcomes | Wins and counts among supported held-out combinations | These groups are observational and can overlap |
| Calibration | Brier score and log loss on held-out observed actions | This evaluates the shared outcome model, not search alone |
| Statistical support | Counts, interval width, and unsupported query rate | A fixed count floor does not prove superiority |
| Diversity | Pairwise inventory distance and distinct first actions | Different order alone does not create a new build archetype |
| Runtime | Preparation time, per-query time, expansions, and cache use | Separate warm and cold measurements |
| Display cost | Cards, rows, duplicates, and complete branch reconstruction | A layout model does not certify the live client |

Use paired comparisons on the same query sample.
Use match-level resampling where observations share matches.
Report both overall and per-hero results.
Do not select a winner using only its optimized score.
Report a tradeoff when no method dominates validity, support, coverage, diversity, and runtime.

The records do not contain randomized action assignment or known behavior propensities.
Do not label matched-action win rates as unbiased off-policy values.
Do not claim that a generated guide improves the actual chance of winning.
Additional search can exploit model error, so compare support and held-out results as beam width grows.

## Development and stopping rules

### Complete-combination support addition

The initial validation run found almost no complete-combination support despite valid individual purchases.
Wider search increased the heuristic score while validation support decreased.
Therefore, the next experiment adds the same joint-support constraint to all methods.
This is an experimental constraint, not a production admission change.

Require 100 training owners of the returned item combination in the corresponding checkpoint and relative-wealth state.
Use 600, 1,201, and 1,801 seconds for the three guide-budget scenarios.
The later checkpoints follow a recorded state boundary by one second.
This retains the strictly earlier observation rule and the 120-second freshness limit.
Label these later checkpoints as just after 20 and 30 minutes.
Require at least three final items for a complete guide core.
For decision queries, require support for the newly generated item combination and permit a single next item.
The constraint does not claim conditional outcome support for every item already in the query inventory.

Intermediate search states use ancestor-expanded inventory support as a feasibility bound.
This permits a component to lead to a supported upgrade.
Final support uses exact reconstructed ownership, without ancestor expansion.
Keep supported prefixes as possible completed guide cores.
Do not report expanded support as an observed exact inventory count.

### Checkpoint correction before test use

The source records later states at 900, 1,200, 1,500, and 1,800 seconds.
The first checkpoint design combined a strict earlier join with a 120-second freshness limit.
Thus, its 1,200- and 1,800-second state cohorts were empty.
Those preliminary summaries do not support a comparison across all budget scenarios.
The corrected checkpoints use 1,201 and 1,801 seconds, with the same freshness rule.
Unknown cohorts now produce unavailable evidence instead of zero-owner evidence.
The initial result files remain available for audit but are superseded.
No test outcomes informed this correction.

First implement and test greedy, constrained beam, and diverse beam.
Then add ECLAT and Leiden structure proposals.
Use synthetic cases to test delayed value, upgrades, budget limits, duplication, missing support, and patch isolation.
Compare beam with exhaustive enumeration on a small catalog.
Require width-one beam to match greedy under identical settings.
Check deterministic repetition with fixed seeds.

Select a small set of efficient configurations from validation results.
Freeze those settings before reading reserved test outcomes.
Complete the comparison when every method has measured results and remaining data limits have explicit consequences.
A failure to establish a causal winner is a valid result when the records cannot identify that effect.

## Display study

Use the saved image references in [the context record](variant-display-context.md).
Preserve the visible relationship between a shared core and each variant's additions.
Never treat a frequent itemset as an observed purchase prefix without sequence evidence.
Keep required shared items separate from optional tier pools.
Use `PICK ONE` only for a supported decision, with clear upgrade and co-ownership semantics.
Keep one default queue and a recoverable complete recipe for each displayed variant.
Compare card counts against plausible native layouts at multiple viewport sizes.
Provide Markdown examples and state any unverified client behavior.

## References

- C. R. Dyer, University of Wisconsin. [Informed Search](https://pages.cs.wisc.edu/~dyer/cs540/notes/search2.html). Beam retention and search limitations.
- Vijayakumar et al. [Diverse Beam Search](https://arxiv.org/abs/1610.02424), 2016. Diversity during sequence search.
- Zaki et al. [New Algorithms for Fast Discovery of Association Rules](https://cdn.aaai.org/KDD/1997/KDD97-060.pdf), 1997. Frequent itemset discovery.
- Traag, Waltman, and van Eck. [From Louvain to Leiden](https://doi.org/10.1038/s41598-019-41695-z), 2019. Community detection and connectivity guarantees.
- Stan. [Hierarchical Partial Pooling for Repeated Binary Trials](https://mc-stan.org/learn-stan/case-studies/pool-binary-trials.html). Shrinkage and predictive uncertainty.
- Li et al. [Unbiased Offline Evaluation](https://arxiv.org/abs/1003.5956), 2011. Conditions for valid replay evaluation.
- Dudik, Langford, and Li. [Doubly Robust Policy Evaluation and Learning](https://icml.cc/2011/papers/554_icmlpaper.pdf), 2011. Outcome and behavior models in policy evaluation.
- Levine et al. [Offline Reinforcement Learning](https://arxiv.org/abs/2005.01643), 2020. Support and distribution-shift limitations.

## Final validation selection

The main sensitivity study used 28 configurations.
It covered widths 4 through 64, depths 4 through 12, smoothing, cost weighting, relative state, diversity, and combination support.
Each configuration used all 342 guide scenarios and 24 sampled decisions per hero.
A second study tested 16 combinations of smoothing, support, depth, and cost settings.
A third study tested nine itemset and graph configurations.
All studies used validation data only.

The final common settings use prior strength 1,000, minimum item-cell support 30, and minimum complete-combination support 200.
They use cost exponent 0.5, uncertainty multiplier 0.5, discount 0.97, depth six, and three output alternatives.
These parameters favor support and runtime over the largest heuristic score.
The scorer retains hero, patch context, net-worth bins, and relative wealth.

The final comparison includes greedy, beam widths 4/8/16/32, diverse beam width 16, ECLAT widths 8/16, and Leiden width 16.
Diverse retention uses strength 0.02.
ECLAT and Leiden retain their original training-only proposal settings.
Changing itemset size, support, graph resolution, or seed did not establish a consistent improvement.

The final validation comparison uses all 96 sampled decisions per hero.
Configuration selection considers guide coverage, held-out support, action agreement, diversity, and runtime together.
The reserved test comparison uses these same methods and settings.
The test evaluation will not select another hyperparameter configuration.

Final output selection removes duplicate inventories, path-prefix extensions, and strict subset cores.
Thus, a shorter version of the same core does not consume an alternative slot.
This rule applies to every method and preserves the highest-scoring returned path.
Earlier sensitivity files preserve their original measured fields.
Later reports identify the final comparison separately.

The returned guide can be a supported partial core.
The purchase budget is a ceiling, not a requirement to spend every available soul.
Report final item count and budget use with guide coverage.
The benchmark does not certify a complete late-game purchase guide or ability-imbue instructions.

## Test-data correction disclosure

The first test attempt stopped on one match with duplicate hero appearances.
The experiment now excludes complete matches that violate its one-hero-appearance-per-match assumption.
The rule applies to every partition and changes only the test cohort.
The final test contains 17,995 eligible matches.
The [correction record](test-data-correction.md) documents the failed attempt, regression tests, cache comparison, and corrected freeze.
No algorithm setting changed after initial test access.
