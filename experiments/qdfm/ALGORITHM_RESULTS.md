# Alternative algorithm results — September 5, 2026

**QQL is the most promising new candidate for further experiments in this
pilot.** It changes some recommendations while remaining much more stable
than the current QDFM implementation. This does not establish higher Deadlock
win rates. IQL is a useful restrained control; this CQL configuration needs
more investigation before we trust its recommendations.

The [research and predeclared protocol](ALGORITHMS.md) lists six methods,
primary papers, implementation choices, and limitations. Three alternatives
and a fresh behavior-cloning baseline were actually trained, each with seeds
42/43/44. All use the same 63,888 training transitions across the nine heroes.
There was no hyperparameter search after seeing these results.

## Observed purchase recommendations

All methods use the same 57 build/state previews, representing 19 build paths
and 27 distinct validation states. Original BC rarity and local match counts
use the same frozen reference for every method. These are debugging metrics,
not estimates of a policy's outcome advantage.

| Method | All three seeds agree | Top choice has <1% original BC probability | Top choice has <5 local matches | Different top choice from fresh BC |
| --- | ---: | ---: | ---: | ---: |
| Fresh BC | 42/57 | 0/57 | 26/57 | 0/57 |
| IQL adaptation | 39/57 | 0/57 | 25/57 | 11/57 |
| CQL adaptation | 8/57 | 1/57 | 36/57 | 40/57 |
| QQL adaptation | 41/57 | 0/57 | 25/57 | 13/57 |
| Previous QDFM implementation | 2/57 | 41/57 | 49/57 | Not recomputed |

New models use 6,000 iterations each. The previous QDFM run used different
training stages and stochastic flow evaluation, so this is not a controlled
paper-to-paper benchmark. Fresh BC, IQL, and QQL use exact categorical
probabilities; CQL uses greedy actions. Their probability distances therefore
have different interpretations. QQL's mean total variation from fresh BC is
0.129, versus 0.041 for IQL: much of IQL's behavior remains close to imitation.

The unchanged support gate admits only **21/57** previews. Requiring at least
50 neighboring training matches and five observations of an action makes
every method abstain on the remaining **36/57**. A rare model choice and a
poorly supported local choice are different problems: QQL improves the former
but does not remove the latter. No Kelvin, Ivy, or McGinnis preview clears
this gate. More usable training context is still needed.

| Hero | Group | Preview rows | Supported rows | QQL all-seed agreement |
| --- | --- | ---: | ---: | ---: |
| Kelvin | Easy | 3 | 0 | 3 |
| Infernus | Easy | 3 | 3 | 3 |
| Mina | Easy | 3 | 3 | 3 |
| Abrams | Medium | 6 | 4 | 6 |
| Billy | Medium | 3 | 2 | 3 |
| Grey Talon | Medium | 9 | 6 | 3 |
| Ivy | Hard | 15 | 0 | 9 |
| Viscous | Hard | 9 | 3 | 7 |
| McGinnis | Hard | 6 | 0 | 4 |

Multiple paths reuse a state. These tiny, unequally weighted samples cannot
establish an easy/medium/hard performance ranking.

## Concrete previews

- Kelvin Frost Grenade: QQL picks Improved Spirit in the low-wealth preview
  and Rapid Recharge in the middle/high previews, instead of the earlier
  flow model's Mystic Reverb. All remain below our local support threshold.
- Abrams Siphon Life: QQL picks Hunter's Aura in the low-wealth preview,
  Melee Charge in the middle, and Warp Stone in the high. The low/high
  choices clear the support gate; the middle preview abstains when gated.
- Abrams Weapon Core: QQL picks Bullet Resist Shredder, Melee Charge, and
  Bullet Resist Shredder respectively. Again, low/high clear the gate.

These are different observed states near 15 minutes, not a controlled
experiment varying only wealth. They demonstrate different model outputs,
not the tactical superiority of an item at that wealth level.

## Known-outcome sequence check

The synthetic task rewards context-sensitive first purchases and compatible
second purchases. Its true optimal success rate is 80%. These results are
exact expectations under the learned policies, not evaluator predictions.

| Method | Seed 42 | Seed 43 | Seed 44 |
| --- | ---: | ---: | ---: |
| Fresh BC | 37.0% | 37.4% | 37.1% |
| IQL | 70.0% | 70.2% | 70.8% |
| CQL | 80.0% | 78.8% | 78.8% |
| QQL | 73.6% | 73.8% | 73.6% |
| Previous QDFM, different budget | 79.3% | 78.9% | 79.1% |

The table uses each configured policy, including stochastic actors for IQL
and QQL but greedy actions for CQL. A supplementary check, added after seeing
the initial results, uses the top choice at both stages for every method:

| Greedy extraction | Seed 42 | Seed 43 | Seed 44 |
| --- | ---: | ---: | ---: |
| Fresh BC | 23.8% | 41.2% | 27.5% |
| IQL | 75.0% | 75.0% | 78.8% |
| CQL | 80.0% | 78.8% | 78.8% |
| QQL | 80.0% | 78.8% | 78.8% |

There was no retraining or parameter selection for this supplement. QQL
matches CQL when both use greedy extraction, so the initial difference was
partly a policy-extraction choice.

All three new RL adaptations learn useful continuations beyond imitation.
CQL's excellent toy result does not carry over to stable real-data choices;
QDFM's strong toy result likewise did not prevent its earlier rare-action
drift. QQL is not uniquely best on this toy. Its promise here comes from
the combination of sequence learning and observed-state plausibility.

## Remaining numerical and evaluation concerns

QQL's independently trained value heads cross their expected ordering on
17.1%, 19.6%, and 28.1% of validation transitions. Its temperature remains
finite because the author-style formula uses an absolute gap plus a floor.
Crossing is a diagnostic concern, not resolved by numerical finiteness; a
future ordering/regularization ablation should be kept separate from the
published adaptation. Critic values in all RL methods extend beyond [0,1].
CQL is explicitly penalized and QQL gap-corrected, but even ordinary IQL
values exceed the terminal reward bounds. None is a calibrated win model.

Whole-validation recorded-action accuracy is 28.59–28.73% for fresh BC,
28.47–28.55% for IQL, 12.50–13.45% for CQL, and 26.18–26.74% for QQL. This measures
imitation across 19,795 decisions, not which purchasing strategy wins more.
No new FQE or test-fold outcome analysis was run. Build evidence overlaps the
validation period, so these are exploratory comparisons.

## Next experiments justified by these results

1. Keep QQL and IQL with explicit support-based abstention. Expand the training
   pilot using the already downloaded cohort, before requesting new collection.
   Track action and context coverage rather than only total match count.
2. Investigate QQL value-head crossings and CQL penalty sensitivity with
   predeclared ablations. Neither problem justifies silently rewriting this
   comparison or promoting an unvalidated policy.
3. Evaluate build-constrained continuation learning. Current training remains
   hero-wide; restricting the next recommendation alone does not teach a
   coherent future path, affordability, slots, or buy-versus-wait.
4. Consider [Uni-RL's current implementation](https://github.com/huijinrl/uni-rl)
   (`8a6a061f865d51ba1294d7c6aee85bd3c930f828`) and
   [CDQAC](https://arxiv.org/abs/2509.10303) afterward. Uni-RL's learned
   actor-weight gradient matching needs a categorical adaptation; merely
   clipping IQL weights would not reproduce it. CDQAC directly addresses
   discrete choices, but its scheduling architecture and reward evidence
   need their own transfer experiment.

The [full report and all 57 previews](../../generated/qdfm/algorithm-comparison/REPORT.md)
and its JSON retain per-seed diagnostics, model hashes, source hashes, and
runtime. Real-data training took about 4 seconds per BC seed, 15–16 for IQL,
13 for CQL, and 33–34 for QQL on this machine. These are small pilot budgets,
not convergence claims. No production build or Steam file was changed.

## Verification

All 18 final fast-gate commands passed, including 1,125 repository tests and
28 experiment tests. The initial review orchestrator exceeded the experiment
cognitive-complexity limit; its preview summaries were extracted into a
separate function and the complete gate then passed. Numerical loss tests
cover quantile/expectile geometry, legal-action CQL gradients, QQL's terminal
gap correction, finite weight clipping, policy masks and abstention, and
exclusion of terminal placeholders from policy-action value regularization.
The synthetic evaluator is also checked against analytic policy expectations.
Logs: `generated/qdfm/algorithm-gates/`. The final documentation-only rounding
and verification update was checked for whitespace afterward.
