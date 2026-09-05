# QDFM offline pilot

This directory contains an independent, reduced-budget reproduction of
[QDFM, arXiv:2602.06138v2](https://arxiv.org/abs/2602.06138v2), followed by an
offline Deadlock experiment. It has its own locked environment and is never
imported by the production application. It reads public match telemetry and
writes research artifacts. It does not access Steam.

No public author implementation was located. Appendix C.8 mentions an anonymous
supplementary code archive; the published paper provides the algorithm in
Appendix E. Consequently this is an implementation of the described method with
the adaptations below, not a reproduction of the authors' reported benchmarks.

## What is implemented

`model.py` learns a behavior distribution, warms up a discrete flow, fits a
Bellman critic, and improves the flow using Q-weighted endpoints sampled from
its current policy. The flow models a time-dependent continuous-time Markov
chain over actions; its input includes the current action and flow time.
Generation executes the chain rather than returning a classifier's logits.

The paper's single-objective case is used. Reward is zero before the final
purchase decision and the team win indicator at termination. The episodic
discount is one, so the objective does not favor a particular number of buys.

Explicit adaptations:

- Endpoint probabilities parameterize outgoing rates divided by `1 - t`.
  The diagonal is minus the outgoing sum. This bounds rates so the Euler grid
  has valid jump probabilities; the final clamp handles roundoff only.
- Training samples one of 20 grid times, avoiding the singular endpoint at one.
- A sigmoid critic bounds estimates to the binary terminal reward range.
  A Polyak target network stabilizes its Bellman updates.
- Candidate masks enforce observed hero/action support and inventory ancestry.
- `build_review.py` additionally restricts frozen-model previews to one selected
  build's candidate pool throughout flow generation (see below).
- The pilot uses 128 hidden units, 128-row batches, 8 endpoint samples,
  beta 5, and substantially fewer updates than the paper's large benchmarks.

## Evaluation groups

These are the user's groups, not measured difficulty labels or model features.

| Group | Heroes |
| --- | --- |
| Easy | Kelvin, Infernus, Mina |
| Medium | Abrams, Billy, Grey Talon |
| Hard | Ivy, Viscous, McGinnis |

One shared model conditions on hero and match state; results are broken out by
hero. Seeds 42, 43, and 44 share an identical frozen dataset and training budget.

## Data contract

The trial samples 2,000 focal player trajectories per hero from the previously
frozen eligible match cohort, with 1,200/400/400 in chronological
train/validation/test folds. Entire matches stay in one fold, including when two
selected heroes occur in the same match. No account identifiers are exported.

The supplement recovers complete item arrays and all 12 players' wealth
snapshots. Recommendations start at logged purchase opportunities at or after
600 seconds. Starting purchases still contribute to inventory and history.
Purchases at the same second form one unordered basket, represented by one
discrete action. Component dependencies determine inventory effects without
inventing an order between independent purchases.

The vocabulary and per-hero minimum count of ten are learned from the training
fold only. This first pilot admits complete suffixes whose actions are all
supported. Every excluded trajectory is counted. That restriction introduces
selection bias and limits generalization; it is not a claim about all matches.

Features include inventory, prior purchase counts, enemy inventory, team
composition, time, rank, lane, relative lobby wealth, team wealth lead, and recent
personal wealth growth. Wealth is taken strictly before the decision, with
snapshot age exposed and capped at 300 seconds. No final wealth, final duration,
future build label, or match outcome appears in the feature matrix.

This does **not** yet implement explicit build-identity preservation, ability
allocation, exact affordability, slot unlocks, buy-versus-wait decisions, a live
state feed, or conversion into production build graphs. Its outputs are research
item targets rather than executable purchase instructions. Enemy inventory in
historical logs may contain information unavailable to a live player.

## Validation and interpretation

`toy.py` supplies a separate two-purchase environment with a known outcome
function. Wealth and threats alter the best first action; the correct second
action depends on the first. Evaluation uses the known outcome function, not
the learned critic. This checks the ability to learn contingent strategies.
Synthetic performance is never reported as a Deadlock win-rate gain.

For Deadlock, frozen behavior, unweighted-flow, and QDFM policies receive
separate fitted Q evaluation (FQE) models. Those models train on the training
fold and estimate value on initial states from later matches. Flow probabilities
use 32 samples during FQE fitting and 256 at evaluation. This is approximate,
model-based off-policy evaluation, not a randomized comparison or a game
simulator. The reported intervals cover held-out sampling variation only.
Model bias, selection bias, and unobserved confounding remain outside them.
Behavior-policy calibration against observed outcomes is reported as a check
on estimator reliability. No experiment result automatically promotes a policy.

Before adoption, compare against a simple Q-weighted categorical policy using
the same critic, improve support and state coverage, validate policy estimates,
and implement the missing build constraints. The present trial tests whether
the QDFM machinery works on this data; it cannot certify the best build.

## Reproduce

Run from the repository root with uv 0.12.x. If the host uv is older, prefix
commands with `uv tool run --from 'uv>=0.12,<0.13'`.

```bash
uv sync --project experiments/qdfm --frozen
uv run --project experiments/qdfm python -m pytest experiments/qdfm/test_core.py -W error
uv run --project experiments/qdfm python -m experiments.qdfm.toy --output generated/qdfm/toy --seed 42

uv run --project experiments/qdfm python -m experiments.qdfm.extract \
  --source /path/to/frozen/offline/run \
  --output generated/qdfm/data --per-hero 2000
uv run --project experiments/qdfm python -m experiments.qdfm.data \
  --source /path/to/frozen/offline/run --directory generated/qdfm/data
uv run --project experiments/qdfm python -m experiments.qdfm.run \
  --directory generated/qdfm/data --output generated/qdfm/seed-42 --seed 42
```

Repeat the toy and training command for seeds 43 and 44. Extraction uses a remote
snapshot that can change; exact reruns should reuse the frozen local parquet
files identified by `extraction.json` and `dataset.json`. Raw data, models, and
reports remain under ignored `generated/qdfm/`. The normal repository fast gate
and `uv run complexipy experiments/qdfm` also apply to the source changes.

## Preview choices within an existing build

```bash
uv run --project experiments/qdfm python -m experiments.qdfm.build_review \
  --directory generated/qdfm/data --runs generated/qdfm \
  --build-evidence /path/to/generated/build-evidence.json \
  --output generated/qdfm/build-constrained
```

This reads the frozen generator's selected core purchase path and optional tier
membership for every path belonging to the nine pilot heroes. It does not read
the broader observed-item table as an allowlist or combine multiple builds into
one hero pool. Required components are included. The evidence must match the
pilot's source snapshot; checkpoints must match the frozen dataset and reports.

The build mask intersects the existing hero support and inventory mask. Every
item in a simultaneous basket must be eligible. The intersection applies both
to initial sampling and each flow step; filtering a finished top-three list
would not provide that guarantee. Empty intersections produce an explicit
abstention. Original inventory and purchase-history features remain unchanged,
including off-pool purchases; no additional trajectories are discarded.

The current admitted situational items already belong to their build's optional
tiers. Pool membership does not assert that a counter's trigger is active. No
separate core-alternative cards were admitted in this snapshot; future cards
outside the optional tiers are rejected pending explicit applicability context.

The output includes each path's item pool, source/checkpoint fingerprints,
before/after eligible-action counts, and three observed states per path. The
behavior diagnostic keeps its original broad support so the smaller pool does
not disguise low historical model probability. The three states are repeated
for each hypothetical selected path, not classified using future purchases.

This is **inference-only restriction**, with the existing trained weights. It
does not train build-conditioned values, enforce core order or the complete
purchase contract, or establish better outcomes. The earlier hero-wide FQE
estimates do not evaluate this changed policy. The generator's pool-selection
artifact is existing release evidence, not a new training-only input suitable
for claiming untouched held-out outcome performance. Original previews and
models remain in their original directory. No tests, retraining, or outcome
evaluation are invoked by this preview command.

## Follow-up diagnostics: actor behavior and item combinations

The user subsequently resumed testing. Two independent diagnostics are available:

```bash
uv run --project experiments/qdfm python -m experiments.qdfm.actor_ablation \
  --directory generated/qdfm/data --runs generated/qdfm \
  --previews generated/qdfm/build-constrained --output generated/qdfm/actor-ablation

uv run --project experiments/qdfm python -m experiments.qdfm.combo_data \
  --source /path/to/frozen/offline/run \
  --build-evidence /path/to/generated/build-evidence.json \
  --output generated/qdfm/item-combos
uv run --project experiments/qdfm python -m experiments.qdfm.combo_review \
  --directory generated/qdfm/item-combos

uv run --project experiments/qdfm python -m pytest experiments/qdfm -W error
```

The actor comparison holds the 57 existing path/state previews and all three
checkpoints fixed. It compares behavior, unweighted flow, QDFM, and direct
categorical `softmax(behavior_logits + 5 * Q)` using the same critic. Local
support uses only training matches: the same hero, time within 180 seconds,
wealth within 35%, lobby wealth percentile within 0.25, and current inventory
Jaccard similarity at least 0.4. Supported variants require 50 distinct nearby
matches and five distinct matches containing the exact candidate action. These
are fixed exploratory thresholds, not fitted safety guarantees. An empty
supported pool abstains. No outcome evaluation or retraining is invoked.

The combination screen uses the much larger frozen source cohort for all nine
heroes, rather than the QDFM pilot's selected complete trajectories. It
reconstructs simultaneous ownership at 15, 20, and 25 minutes, applying sales and
component consumption. All observations precede the landmark, with at most
300 seconds of staleness. Only training and validation folds are read.

Candidate pairs must be co-admitted in at least one build and contain two items
costing at least 1,600 souls, excluding upgrade/component pairs. The primary
screen is at 20 minutes. Four ownership groups are compared within common
strata of current wealth, team wealth lead, and rank. All four rates use the
same combo-owner weights over overlapping strata. Five observations per group
per stratum and 50 combo observations in overlap are required. Negative
additive interactions are corrected with Benjamini-Hochberg across estimable
training comparisons, then checked in validation with a Bonferroni correction
across discoveries. Validation estimates use that fold's own overlap population.

These are contemporaneous associations. Current wealth can already be affected
by earlier item choices, other inventory and matchup differences remain, and
the additive probability scale matters. A negative interaction does not imply
the pair is worse than either item alone. Repeated landmarks are not independent
replications, and normal intervals are approximate conditional on the estimated
stratum weights. No result becomes a production item ban. A purchase-effect
study requires pre-purchase comparisons of the second item with legal,
similarly priced alternatives while the first is already owned.

The fixed build pools themselves already used release evidence with later-fold
checks. Chronological validation in the combination screen is therefore an
exploratory diagnostic, not a fresh untouched holdout. The follow-up tools do
not load test-fold match rows.
