# Algorithm research and comparison protocol

Research checked September 4–5, 2026. Protocol written before these new runs.
This is offline sequential decision learning from observational match logs,
with partially observed state and discrete, state-dependent purchase actions.
Supervised prediction alone does not establish which intervention wins more.

## Candidates and primary sources

| Method | Date | Fit and decision |
| --- | --- | --- |
| [Quantile Q-Learning (QQL)](https://arxiv.org/abs/2511.11973) | November 2025 preprint; April 2026 revision, TMLR 2026 | Try a categorical adaptation. Dual quantile values provide adaptive guidance; it still depends on critic accuracy. |
| [IQL](https://arxiv.org/abs/2110.06169) | 2021 preprint / ICLR 2022 | Established control: value learning at logged actions and advantage-weighted imitation. |
| [CQL](https://arxiv.org/abs/2006.04779) | 2020 | Established discrete control: penalize high values assigned beyond recorded actions. |
| [Uni-RL](https://proceedings.neurips.cc/paper_files/paper/2025/file/c0f721d329c1a10546869c783e866fb7-Paper-Conference.pdf) | NeurIPS 2025 | Follow-up candidate: in-sample value regularization and bounded actor weights may help with policy drift. [Current author repository](https://github.com/huijinrl/uni-rl) found through the author's homepage; the paper's older repository link was unavailable. Not trained in this comparison. |
| [CDQAC](https://arxiv.org/abs/2509.10303) | September 2025 preprint | Follow-up candidate: discrete quantile critic, conservative regularization, delayed policy updates, and variable action availability. Scheduling results do not establish transfer to Deadlock. Not trained here. |
| [Flow Q-Learning (FQL)](https://proceedings.mlr.press/v267/park25f.html) | ICML 2025 | Flow behavior model with a one-step actor. The published continuous-action gradient is not directly applicable to categorical item IDs; defer that adaptation. |

CDQAC's return-distribution quantiles and QQL's value-regression quantiles
serve different purposes. Neither automatically provides uncertainty about
a recommendation caused by missing matchup examples. Our binary terminal
reward also supplies less return-distribution structure than scheduling costs.

## Implementations and adaptations

These are independent small-network implementations, not published benchmark
replications. Author training scripts and third-party dependencies are not run.

- Shared raw, unbounded critics and categorical actors; two 128-unit hidden
  layers, minibatch 128, Adam 0.0003, Polyak 0.005, terminal win reward,
  undiscounted episodic return. No reward normalization or state restandardization;
  preserve the pilot feature encoding. Actor learning rate decays with cosine.
- IQL: expectile 0.7, minimum of twin target critics, actor weight
  `exp(5 * (Q - V))`, capped at 100. Categorical likelihood replaces the
  original continuous policy. Follow the [author update ordering](https://github.com/ikostrikov/implicit_q_learning): value, actor, critic, target.
- CQL: twin raw critics, mean squared Bellman loss plus 0.1 times
  `logsumexp(legal Q) - Q(recorded action)` per critic. Greedy action from
  the minimum online critic selects the minimum target-critic bootstrap.
  Exact legal-action enumeration; greedy categorical policy at inference.
  This is a CQL(H) penalty on a clipped double-critic Double-DQN adaptation,
  not an Atari benchmark replication. Fixed alpha is not a tuned optimum.
- QQL: follow the [author Python implementation](https://github.com/yunqianevergarden/Quantile-Q-Learning)
  at `e5eb8c781db58d850a9274e2892160c50c0b32ce`: logged soft/high quantile
  value updates, gap-corrected twin critic, adaptive weighted actor, then
  separately sampled policy-action value regularization. Use the analytic
  quantile levels from the paper/Python defaults, not inconsistent YAML
  approximations. Euler's constant determines levels and temperature;
  floor 0.1, zeta 1, regularization coefficient 1. Replace Gaussian actions
  with masked categorical samples; omit terminal placeholder states from
  policy-action regularization. No ordering constraint between value heads
  is added; record crossing rates as a diagnostic. Cap log weights before
  exponentiation for numerical safety. Raw Q has a gap correction and
  must not be read as a calibrated win probability.

## Frozen comparison

Before observing results, fix seeds 42/43/44 and 6,000 minibatch iterations
per new method on the existing 63,888 training transitions. Train a fresh
behavior-cloning (BC) control at the same actor budget. QQL has additional
value updates, CQL has no actor updates; equal iterations do not mean equal
compute. Report runtime. Do not overwrite QDFM's existing checkpoints.

Run all four methods on the same known-outcome two-purchase task, with
3,000 iterations and 64-unit networks per seed. The environment has a true
80% optimum. Calculate expected outcome exactly under each learned policy,
without fitting an evaluator or sampling evaluation outcomes. Each method
gets the same toy dataset within a seed; different seeds also vary that data.

For Deadlock, reuse the same 57 build/state previews (19 paths, 27 unique
validation states) across all nine heroes. Report top-choice agreement across
three seeds, original frozen BC probability below 1%, distinct local training
matches below five, and distance from the original build-restricted BC.
Also show the unchanged support gate (50 neighbor matches, five for an action),
including abstentions. Support neighborhoods use only training matches.
Report whole-validation recorded-action accuracy and probabilistic imitation
loss where meaningful; these measure imitation, not policy value. CQL is
deterministic, so do not disguise a clipped infinite log loss as a probability
metric. Report Q ranges/head crossings as numerical diagnostics only.

No new test-fold evaluation, hyperparameter selection by validation win rate,
retrospective assignment of build paths from future purchases, or deployment.
Training remains hero-wide; chosen build pools restrict inference only.
Build evidence was not generated independently of the validation period;
this is exploratory model debugging, not an untouched holdout experiment.
The original pilot selection bias, absent cash/slot/wait actions, partial
observability, sparse local overlap, and missing causal identification remain.
Seed agreement and plausible purchases cannot prove outcome improvement.
