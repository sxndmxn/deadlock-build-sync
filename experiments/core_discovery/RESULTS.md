# Five-algorithm evaluation — September 5, 2026

**All five new discovery methods were implemented and evaluated.** The new
comparison starts from match inventories and discovers cores automatically,
instead of inheriting a player-selected or existing build identity.

Eclat, PrefixSpan, KL-NMF, Bernoulli mixtures, and Leiden each completed
27 real-data runs: nine heroes, seeds 42/43/44. Exact Eclat/PrefixSpan runs
are deterministic; identical repeats are not independent evidence of robustness.
The frozen [protocol](PROTOCOL.md) explains the five algorithms, primary
sources, adaptations, and shared admission rules.

## What the comparison found

The five methods produced 101 method/core nominations, representing **34
unique hero/core combinations**. Only **8 unique combinations** passed later
validation. All five methods retained six combinations each, largely the same
ones; this is not evidence that any method increases real match win rates.

| Algorithm | Candidate triples across heroes/seeds | Selection nominees | Later replicas | Covered validation observations | Discovery runtime |
| --- | ---: | ---: | ---: | ---: | ---: |
| Eclat | 180 | 20 | 6 | 11.3% | 3.7s |
| PrefixSpan | 180 | 19 | 6 | 12.9% | 12.3s |
| KL-NMF | 246 | 20 | 6 | 11.3% | 27.0s |
| Bernoulli mixture | 180 | 20 | 6 | 11.3% | 14.2s |
| Leiden | 180 | 22 | 6 | 12.4% | 0.6s |

Candidate counts are unions within each hero across the seeds. Coverage
counts each hero-match once within a method; different methods cover different
populations. Runtime is the sum of the small discovery runs, not a production
benchmark. No NMF convergence warnings occurred; all Bernoulli fits converged.

Eclat, NMF, and Bernoulli retained exactly the same six combinations. PrefixSpan
and Leiden each substituted a different Billy combination. Five combinations
were shared by every method. NMF's candidate stability was lower: 117 of its
246 candidates appeared in all three seeds.

## Concrete cores with replicated statistical evidence

These are three-item midgame candidates for tactical review, not finished
build guides or causal purchase-effect estimates. Observed rates concern
players already owning the core at 20 minutes.

| Hero | Core items | Later matches owning all three | Observed win rate | Methods nominating it |
| --- | --- | ---: | ---: | --- |
| Kelvin | Torment Pulse + Enduring Speed + Healbane | 983 | 60.0% | All five |
| Abrams | Melee Charge + Hunter's Aura + Bullet Resist Shredder | 6,318 | 54.6% | All five |
| Abrams | Stalker + Hunter's Aura + Bullet Resist Shredder | 5,753 | 55.2% | All five |
| Abrams | Melee Charge + Stalker + Hunter's Aura | 6,989 | 54.6% | All five |
| Billy | Spirit Shielding + Bullet Resist Shredder + Spirit Snatch | 3,513 | 53.6% | Eclat, NMF, Bernoulli |
| Billy | Stalker + Battle Vest + Spirit Snatch | 5,246 | 52.7% | PrefixSpan |
| Billy | Stalker + Bullet Resist Shredder + Spirit Snatch | 4,757 | 53.5% | Leiden |
| Viscous | Melee Charge + Rapid Recharge + Lifestrike | 644 | 61.2% | All five |

The three Abrams triples share two items pairwise and have mean owner-set
Jaccard similarity **0.813**. They look like variants of a common item family,
not three established independent build identities. Their union suggests an
additional four-item hypothesis; that hypothesis was not part of the frozen
three-item validation and is not automatically admitted.

None of the nominees for Infernus, Mina, Grey Talon, Ivy, or McGinnis cleared
this screen. This does not show that those heroes lack good builds: the search
was bounded to frequent, three-item cores owned at 20 minutes. For example,
several Ivy nominees had raw validation win rates around 58% but insufficient
state-adjusted evidence after multiple-comparison correction.

## Alignment with the build vision

This separates discovery from quality admission. It finds plausible item
families and rejects unsupported winners instead of forcing an identity for
every hero. However, cheap utility combinations can pass a statistical gate
without defining the hero's main damage or ability-scaling plan. Tactical
core criteria and consolidation of overlapping families still matter.

The opponent/wealth view is present for every nominated core. For Kelvin's
retained core, observed win rates were 51.2% behind (324 owners), 63.7% even
(564), and 68.4% ahead (95). Against enemy Abrams the same core had 216 owners
and a 59.7% observed win rate. Those are context descriptions; they do not
show that the core caused the lead or that an item counters Abrams. Full
enemy-hero cells, context baselines, and ordered-purchase support are in the
[evaluation JSON](../../generated/core-discovery/trial-v1/evaluation.json).

My next implementation choice is **Eclat as the direct combination baseline,
Leiden as a complementary source of item families, and PrefixSpan for purchase
order evidence**. NMF and Bernoulli did not add replicated combinations beyond
Eclat in this configuration. This selects useful components of a pipeline;
it does not declare a best policy based on incomparable observed win rates.

## Independent synthetic check

All five methods recovered all three planted cores, including the losing one.
The common gate prevented every method from nominating the planted losing
core. Leiden retained both planted winning cores. Eclat, NMF, and Bernoulli
retained one exact winning core plus related triples; PrefixSpan allocated its
three slots to related variants rather than the exact planted winning triples.
All methods' nominated synthetic variants passed the separate validation gate.

This exposes an identity-diversity issue: selecting the strongest three
triples can spend all slots on closely related variants. It is useful evidence
for a future consolidation rule, not a reason to change this trial's nominees
after observing results. The [synthetic report](../../generated/core-discovery/synthetic-v2/report.json)
records generator/source hashes and seed 91, with 9,000 observations per fold.
It is not a simulator of Deadlock or a test of causal item effects.

## Data and limits

446,423 full-corpus hero-match observations: 252,343 for outcome-blind discovery,
80,947 for selection, and 113,133 for later validation. Whole-match partitions
do not overlap. Validation starts after the selection period. The test fold
was not read by the new pipeline. Existing build labels/pools were not inputs.

Only currently owned items appear, with sales and upgrade consumption applied.
Latest acquisition times are strictly before 20 minutes; ties do not imply
order. Each core contains three tier-2+ items, at most 12,800 souls total, with
no ancestor/upgrade pair. At least 100 owners, >=52% observed wins, ownership
lift, and comparable-state overlap are required. Later replication also
requires corrected win-above-50% and positive adjusted-association evidence.

The two test families use Bonferroni alpha 0.025 each across 34 hypotheses.
The adjusted contrast's test is approximate, and some surviving lower bounds
are close to zero. Current wealth can already reflect earlier purchases;
other inventory, player skill, opponent differences, and repeated players
remain possible confounders. The cohort spans balance changes, and its
validation period was examined during earlier research. This remains an
exploratory screen, not certification of current-patch build quality.

## Audit artifacts

Independent SQL recomputation matched ownership counts, wins, and adjusted
differences for all 34 nominees. A separate replay of 135 sampled inventories
matched the frozen inventory and latest acquisition times, with zero
mismatches. There were zero cross-partition matches. See
[audit.json](../../generated/core-discovery/trial-v1/audit.json) and the
[full comparison](../../generated/core-discovery/trial-v1/REPORT.md).

All 23 final verification commands passed, including formatting, lint, types,
complexity, dependency checks, package build, and repository quality gates.
The test runs passed 1,125 repository tests, 28 earlier experiment tests, and
10 new core-discovery tests. Frozen source, data, models, and nomination hashes
were verified again after evaluation.

All changes are local experiment code and documentation. No production build
or Steam file was changed.
