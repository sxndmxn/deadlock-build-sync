# Five new algorithms for automatic core discovery

Fixed September 5, 2026, before fitting these methods or reading their results.
Build identity is an output of the system. The experiment discovers item cores,
then requires independent outcome and support evidence before admitting any.
Current build identities, pools, and labels are not discovery inputs.

## Five algorithms, new to this repository

1. **Eclat:** vertical transaction-ID intersections discover frequent triples.
   [Original paper, Zaki (2000)](https://sci2s.ugr.es/keel/pdf/algorithm/articulo/2000%20-%20IEEETKDE%20-%20Zaki%20-%20%28Eclat%29%20ScalableAlgorithms%20for%20Association%20Mining%20.pdf).
2. **PrefixSpan:** projected purchase sequences discover ordered triples.
   This independent bounded adaptation searches distinct singleton steps;
   same-second purchases remain unordered and cannot supply consecutive steps.
   [Maintainer documentation and original paper link](https://www.philippe-fournier-viger.com/spmf/PrefixSpan.php).
3. **KL-NMF:** nonnegative factors propose overlapping item cores, with six
   factors, random initialization, multiplicative updates, maximum 500 iterations,
   tolerance 0.0001. [Pinned scikit-learn API](https://scikit-learn.org/1.7/modules/generated/sklearn.decomposition.NMF.html).
4. **Bernoulli mixture:** six latent binary-inventory profiles, fitted with
   expectation-maximization and small symmetric priors. This uses Bernoulli
   item probabilities, not Gaussian distances or recursive K-means splits.
   [Mixture-model reference](https://pomegranate.readthedocs.io/en/latest/tutorials/B_Model_Tutorial_2_General_Mixture_Models.html).
5. **Leiden:** communities in an item graph, with positive co-ownership lift
   edges weighted by joint frequency times log lift, configuration-model
   modularity resolution 1, ten iterations.
   [Original paper](https://www.nature.com/articles/s41598-019-41695-z),
   [author implementation](https://leidenalg.readthedocs.io/en/stable/reference.html).

These are five different methods, not claims of five recent inventions. The
existing pipeline uses recursive K-means; previous purchase-policy trials used
BC, QDFM, IQL, CQL, and QQL. Those are not counted toward this comparison.
Recent mining research often changes computational efficiency rather than the
meaning of a good core. For example, the [July 2026 Newton KL-NMF preprint](https://arxiv.org/abs/2607.13919)
changes the optimizer; the present NMF run uses the documented library solver,
not an unimplemented claim to reproduce that preprint.

## Data and chronology

Use all available nine-hero observations from the frozen full-corpus inventory
replay at **20 minutes**, not the small QDFM training sample. Replay applies
sales and upgrade consumption and uses only events strictly before 20 minutes.
Fresh wealth/team snapshots are at most 300 seconds old. Match outcomes are
labels only. The replay itself did not restrict inventory to existing builds.
Join enemy hero compositions and the most recent acquisition time of each
currently owned item. A rebought item uses its current acquisition, not its
earlier consumed/sold instance. No final inventory or final wealth is a feature.

Divide the existing chronological training matches: earliest 75% for discovery,
latest 25% for selection, with whole matches kept together. Freeze nominees
before evaluating the existing later validation fold. Do not read test-fold
match rows. The frozen cohort crosses balance changes; catalog mechanics are
from the frozen snapshot, not certified historical per-match patches.
Previous experiments already examined this validation period: this comparison
is exploratory, even though its own candidates never train on validation.

## Common candidate contract

- A candidate is three distinct concurrently owned items, each costing at least
  1,600 souls, total cost at most 12,800. Exclude ancestor/upgrade pairs.
  This is a bounded midgame core experiment, not a complete six-item build.
- Admit item features with discovery support at least max(100, 1% of rows).
  Candidate triples need at least 100 discovery matches and joint lift >=1.1.
- Eclat enumerates triples; PrefixSpan nominates triples with at least 100
  ordered occurrences. Latent profiles and graph communities propose triples
  among their eight strongest items. Require actual joint ownership even if
  marginal profile weights look strong. Latent item strength is divided by
  square-root marginal prevalence; graph strength is internal weighted degree.
- Rank each method's proposals by joint prevalence times log joint lift;
  PrefixSpan uses ordered prevalence instead. Keep at most 20 per hero/seed.
  Run seeds 42/43/44. Exact mining is deterministic; repeated identical results
  are not independent uncertainty evidence. Require a nominee to appear in at
  least two seeds. Core identity is the unordered triple; retain order evidence.

## Selection and evaluation

The discovery algorithms do not inspect wins. A shared selection gate then
requires: 100 owners, observed win rate >=52%, ordinary 95% Wilson lower bound
above 50%, joint lift >=1.1, and a positive state-standardized association with
its ordinary 95% lower bound above zero. Standardize core and noncore owners
to the core-owner distribution of common strata: 5,000-soul wealth bins,
team-lead-share bins [-.10,-.03,.03,.10], and 20-badge bins. Each arm needs ten
observations per stratum, at least 100 core owners in overlap, and 80% overlap.
Select at most three nominees per hero/method by adjusted lower bound.

On later validation, evaluate every frozen nominee. Require the same support,
52% observed win rate, and lift/overlap thresholds. In addition, use Bonferroni
correction across the union of nominated hero/core hypotheses for both the
one-sided exact binomial win-above-50% test and the positive standardized
association test. Allocate 0.025 family error to each family, total <=0.05
under the respective assumptions; the association test is a normal approximation.
No threshold changes or replacement nominees after seeing validation results.

Report discovery yield, selection/rejection reasons, validation replication,
coverage without double-counting overlapping cores, seed stability, runtimes,
and concrete item cores for all nine heroes. Show descriptive validation
performance by ahead/even/behind (own wealth relative to lobby mean, +/-10%)
and each enemy hero for sufficiently supported cells. These are tuning clues,
not automatic counter rules or causal purchase effects. Wealth at 20 minutes
can already be affected by core purchases, and other confounders remain.

## Checks and scope

Exercise all five methods on synthetic inventories with three planted cores,
including a losing core, and evaluate their recovery and the common outcome
gate on separate generated observations. Unit checks cover exact itemset
support, sequence timing/ties, mixture likelihood, graph structure, invalid
cores, quality abstention, and chronology. Run the full repository fast gate
and both experiment environments' checks before handoff. Report failures as
results; success does not require any method to pass the admission gate.

All artifacts remain local. A replicated statistical core is eligible for
further tactical review, not automatically a production build. Complete
purchase paths, opponent-specific interventions, buy/wait decisions, and
live-game outcome improvement are outside this five-algorithm evaluation.
