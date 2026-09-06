# Identity and purchase-path comparison — September 5, 2026

The accepted plan was implemented and run for all nine heroes. **Grouping
improved the nomination set; PrefixSpan added no complete passing path beyond
the pairwise baseline in this trial.** One unique Abrams core and purchase
order passed all current research gates. This is not a finished match guide
or evidence that following the path causally improves wins.

## Actual comparison

The search examined 31,305 frequent itemsets across sizes 3–6. After the fixed
contract and per-size caps, it retained 450 triples as seeds and **1,318
size-4–6 candidates**. Leiden consensus plus complete-link checks produced
428 groups. Three configurations nominated 23 cores each: **69 arm nominations,
30 unique hero/core hypotheses**. Nominations and orders were frozen before
later validation, with no replacement of failed nominees.

| Configuration | Nominees | Later core gate | Supported full orders | Legal component paths | Complete research previews |
| --- | ---: | ---: | ---: | ---: | ---: |
| A: Eclat + pairwise order | 23 | 1 | 20 | 23 | 0 |
| B: Eclat + Leiden + pairwise order | 23 | 2 | 21 | 23 | 1 |
| C: Eclat + Leiden + PrefixSpan | 23 | 2 | 21 | 23 | 1 |

Order support is assessed separately from core outcomes, so most supported
orders belong to cores that did not pass the outcome gate. B and C produced
the same complete Abrams preview. Core coverage was 1.9% of later hero-match
observations for A and 6.9% for B/C; these populations are different and their
raw win rates cannot establish a better policy.

Discovery-only mean owner Jaccard among each arm's nominated within-hero pairs
fell from **0.555 to 0.371** after grouping. Pairs at or above 0.70 fell from
11/21 to 4/21. Grouping reduces redundancy; it does not eliminate every similar
pair, because consensus and complete-link group constraints also apply.
The additional descriptive calculation is saved in
[nominee-overlap.json](../../generated/identity-paths/trial-v1/nominee-overlap.json).

Summed Eclat mining time was 0.37s; grouping across all heroes and seeds took
11.39s. Order construction/timing attachment summed to 0.23s, 0.25s and 0.58s
for A/B/C. These are stage timings on this machine, excluding source hashing,
database loading and validation, not a production performance benchmark.

## Abrams: a supported exact core and order

**Stalker → Melee Charge → Bullet Resist Shredder → Hunter's Aura**

The exact four-item core costs 8,000 catalog souls and had **5,682 later owners,
3,131 wins, 55.1% observed win rate**. Its standardized association was +2.94
percentage points with corrected lower bound +0.52 points. The full order had
3,486/7,468 discovery owners (46.7%), 1,268/3,232 selection owners (39.2%), and
2,475/5,682 validation owners (43.6%). Both order algorithms chose this order.

| Purchase | Incremental souls | Discovery purchase-time IQR | Discovery net-worth IQR |
| --- | ---: | --- | --- |
| Stalker | 1,600 | 6.0–9.3 min | 2,591–5,264 |
| Melee Charge | 1,600 | 7.2–9.9 min | 3,480–5,861 |
| Bullet Resist Shredder | 1,600 | 10.9–14.3 min | 6,402–9,915 |
| Hunter's Aura | 3,200 | 14.6–18.1 min | 10,106–12,683 |

Those ranges describe purchases by discovery core owners; they are not optimal
buy times or cash-balance thresholds. This core has no required components in
the frozen catalog. Standalone opening items and late purchases are omitted.

The source descriptions supply a concrete tactical connection: Stalker's wound
deals spirit damage, and Bullet Resist Shredder triggers on spirit damage;
Siphon Life and Seismic Impact also explicitly deal spirit damage. This is
source-backed mechanical rationale, not measured synergy or a verified stacking
claim. Every reference is included in the JSON.

The Eclat-only arm spent its three Abrams slots on overlapping 5–6-item
combinations around Restorative Locket/Spirit Snatch/Dispel Magic. Their
discovery owner Jaccard averaged 0.999. Despite raw validation wins near 66%,
they failed comparable-state overlap and adjusted-evidence requirements.
Grouping created space for the four-item core above, which independently passed.
It was validated as an exact four-item hypothesis, not admitted as the union
of the previous experiment's triples.

## Kelvin and Billy: informative abstentions

Kelvin's **Improved Spirit + Torment Pulse + Enduring Speed + Healbane** had
316/512 later wins (**61.7%**) and a supported core order. Its adjusted estimate
was +5.10 points, but the corrected lower bound was **−1.91 points**; the
adjusted p-value 0.0111 did not meet the frozen 0.025/30 threshold. It remains
a candidate, even though the original three-item experiment retained a related
triple. Adding an item creates a new hypothesis and a different owner cohort.
No Kelvin nominee passed the new core screen.

Billy's **Spirit Shielding + Battle Vest + Bullet Resist Shredder + Spirit
Snatch** passed the core gate with 1,163/2,152 later wins (**54.0%**). Its order
did not hold up. The PrefixSpan order's support fell from 16.0% of discovery
owners to 1.54% in selection and 0.74% in validation. The pairwise order had
0.37% validation support. Thus this is a supported unordered core, not a
completed purchase path. PrefixSpan changed only this one order among B/C's
23 nominees and did not rescue its admission.

Infernus, Mina, Grey Talon, Ivy, Viscous and McGinnis had nominees but none
passed the full core screen. The bounded search and strict multiplicity gate
do not establish that those heroes lack good builds.

## Synthetic and independent verification

The three-arm planted experiment used seed 123 and 9,000 observations across
discovery/selection/validation. All arms rejected the losing core. A spent all
three slots on variants of one winning identity; B/C represented both planted
winning identities. Each arm produced three passing synthetic previews.
This checks recovery and redundancy behavior, not actual Deadlock performance.

Independent SQL matched owner counts, wins and standardized differences for
all **30** unique nominees. A separate calculation matched **31** distinct
frozen validation-order counts. Independent component arithmetic validated
**53** unique method/path records. Original purchase-log replay matched **135**
sampled inventories/latest-acquisition records. All had zero mismatches;
there were zero matches crossing partitions.

All **28 verification commands passed**, including 1,125 repository tests,
28 prior policy-experiment tests, 10 prior discovery tests, and **13 new tests**
(1,176 total). The new tests cover grouping, source identity, losing cores,
full-order support, ties, sales/rebuys and component legality. The initial fit
attempt stopped before fitting because the new asset check compared byte hashes
with the source's canonical-JSON hashes; the comparison was corrected and a
regression test added. Data, thresholds and outcome nominations were not changed.

## What this establishes and what remains

Eclat plus conservative grouping is the useful foundation from this comparison.
Keep PrefixSpan as an order diagnostic; this trial does not justify claiming an
incremental recommendation benefit. Future work should address temporal ordering
instability and tactical identity quality before adding contextual interventions.

The explanation gate is a controlled-vocabulary text screen. It can miss
stat-based connections and can match broad language such as healing; it does
not certify a playstyle or optimal synergy. Component actions are mechanically
scheduled rather than jointly learned with timing, so some candidate component
positions conflict with their historical timing ranges. Such ranges remain
diagnostic, and these previews must not be treated as polished full guides.

This is the same 446,423-observation frozen cohort as the preceding discovery
study, with 113,133 later validation observations. Validation was previously
examined, patch mechanics are not historically certified per match, and current
wealth may reflect prior purchases. No causal policy or timing effect is claimed.
The test fold remains unread. No production interface or Steam file was changed.

Artifacts: [comparison](../../generated/identity-paths/trial-v1/REPORT.md),
[Abrams](../../generated/identity-paths/trial-v1/ABRAMS.md),
[Kelvin](../../generated/identity-paths/trial-v1/KELVIN.md),
[evaluation](../../generated/identity-paths/trial-v1/evaluation.json),
[audit](../../generated/identity-paths/trial-v1/audit.json),
[synthetic check](../../generated/identity-paths/synthetic-v1/report.json).
