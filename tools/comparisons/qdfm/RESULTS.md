# First QDFM trial

The three-seed reproduction learned context-dependent, two-step strategies in a known synthetic task, achieving 78.91–79.28% expected success against an 80% optimum. This is not Deadlock performance.

The nine-hero pilot trained on 5,930 complete trajectories and evaluated later matches. Its current recommendations are not ready for production: 23 of 27 preview states favored a target assigned under 1% probability by the behavior model, and only one state had unanimous top-choice agreement across seeds. Large fitted value gains remain unverified and may reflect extrapolation. Explicit build identity and the complete purchase-legality contract are still missing.

The user's difficulty groups were preserved. Full artifacts are local under `generated/qdfm/`, including `REPORT.md`, `examples.md`, frozen data, checkpoints, and all three outcome reports. Source and dependencies are isolated here; neither production recommendations nor Steam was changed. No additional trials were started after the user paused testing.

See [the method and limitations](README.md) and the [local detailed report](../../generated/qdfm/REPORT.md).

## Build-pool restriction preview

At the user's request, the frozen models now have a separate preview command
that limits generation to each selected build's core, optional items, and
required components. It preserves historical state and the original training
data. This is an inference change, not retraining or a new outcome evaluation.

The frozen generator artifact contains 19 paths across the nine pilot heroes.
Three observed states per path produced 57 previews, with no empty candidate
intersections. Thirty-three hero-wide first choices were outside their selected
pool and were replaced. Every generated action stayed inside its build mask.
The same 27 observed states are reused across paths; these are not 57 independent
observations or a new held-out performance sample.

Abrams's Siphon Life pool contains 43 items; Weapon Core contains 36. Neither
includes Ethereal Shift. At the low-wealth 14:42 state, the leading restricted
targets became Phantom Strike and Scourge respectively. Kelvin's Frost Grenade
pool contains 49 items; its leading target remained Mystic Reverb at all three
preview states.

Restriction has not resolved the ranking concern: 40 of 57 leading targets
still receive less than 1% probability under the original broad behavior model,
and only 3 of 57 receive unanimous first-place votes across training seeds.
Behavior probability is a model diagnostic, not a measured conditional purchase
frequency or a causal quality judgment. These counts cannot be compared directly
with the original 27-row review because builds repeat observed states.

All source changes remain isolated in the experiment. No tests or quality gates
were run for this change, per the user's instruction. The actual preview command
completed with all three frozen checkpoints. No training, FQE, or Steam access
was performed. See the [local build-restricted previews](../../generated/qdfm/build-constrained/examples.md)
and [pool/provenance manifest](../../generated/qdfm/build-constrained/manifest.json).

## Testing resumed: support, actor comparison, and pair interactions

The user resumed testing and asked specifically about bad combinations such as
Weighted Shots + Point Blank. The new screen reconstructed 1,282,833 usable
landmark observations across the nine heroes from the full frozen source's
training and validation folds. It screened 7,128 co-admitted hero/pair candidates
at 20 minutes; 3,206 had enough overlap for adjusted comparisons. One negative
training interaction survived multiple-comparison correction (Infernus Rapid
Recharge + Swift Striker), but it did not replicate in validation. This screen
therefore supplies no replicated adverse interaction to turn into an item ban.

Abrams Weighted Shots + Point Blank had positive but uncertain adjusted
interaction estimates in training at 20 and 25 minutes. The 25-minute validation
estimate was -4.8 percentage points with an approximate 95% interval from -12.3
to +2.7. Direction changed between folds and the interval includes zero. These
are current-state associations, not causal estimates of buying the second item.

The frozen actor comparison found 40/57 unanimous top choices for direct
categorical value weighting, versus 2/57 for QDFM with 512 sampling draws per
state/seed. None of the direct policy's leading choices had original behavior
probability below 1%; 41/57 QDFM choices did. These are plausibility/stability
diagnostics and do not establish better win rates. Sampling budget differs
from the earlier preview, so small count differences are expected.

Requiring local training support caused 36/57 previews to abstain. The same
coverage held with minimum action support of 3, 5, or 10 matches because the
50-neighbor requirement and available contexts were limiting here. Strict
matching is intentionally conservative but exposes how sparse the small pilot
is. More of the already available corpus, and better contextual generalization,
are preferable next experiments to relaxing all evidence restrictions.

See the [combination report](../../generated/qdfm/item-combos/REPORT.md) and
[actor comparison](../../generated/qdfm/actor-ablation/REPORT.md). The test fold
was not read by these follow-up diagnostics, no new FQE was fitted, and no Steam
files or production recommendation code were changed.

Verification after testing resumed: all 18 fast-gate commands passed, including
1,125 repository tests and 18 experiment tests. Ninety landmark inventories
matched an independent reconstruction with the existing catalog replay, with
zero mismatches; no duplicate hero/match/landmark rows were found. The final
report-only clarification was format- and lint-checked afterward. Logs are in
`generated/qdfm/followup-gates/` and `generated/qdfm/item-combos/inventory-audit.json`.
