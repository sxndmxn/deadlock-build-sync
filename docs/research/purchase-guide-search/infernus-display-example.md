# Infernus display example

This example uses a real result from the frozen diverse-beam comparison.
It shows the core panel, not a complete production guide.
The default does not meet the earlier requirement for a win rate above the hero baseline.
Its test sample is also too small to establish a small advantage.
The example demonstrates accurate display and the remaining model failure.

## Visible core panel

```text
INFERNUS — EXPERIMENTAL CORE
Observed ownership at 20:01 | Even relative wealth
Hero win rate: 47.26%

COMMON PURCHASE ORDER
1. Spirit Lifesteal
2. Enchanter's Emblem
3. Extra Charge
4. Healbane
5. Rapid Recharge

NEXT PURCHASE
Default    Extended Magazine    43.3% | 60 matches
Variant 2  Suppressor            45.1% | 82 matches
Variant 3  Rapid Rounds          49.3% | 69 matches

Queue uses Default. Buy another variant manually.
Each rate includes the four final shared items.
```

The five shared purchase steps leave four shared final items.
Rapid Recharge consumes Extra Charge.
The final shared core is Spirit Lifesteal, Enchanter's Emblem, Healbane, and Rapid Recharge.

Each branch adds one item to that final core.
The layout needs eight purchase cards, compared with 18 cards for three repeated full purchase rows.
A final-core reference alone needs seven card positions, compared with 15 repeated core positions.

The three branches have an identical planned purchase prefix.
That exact equality permits shared queue steps in this example.
The ownership statistics do not prove that players followed this purchase order.

A player can later own items from several branches.
The branch labels identify alternative next purchases, not permanent mutual exclusion.
No automatic branch selector is assumed.

## Complete branch evidence

| Branch | Final addition | Total path cost | Training owners | Test wins / owners | Observed rate | 95% interval |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Default | Extended Magazine | 8,800 | 209 | 26 / 60 | 43.33% | 31.57–55.90% |
| Variant 2 | Suppressor | 9,600 | 320 | 37 / 82 | 45.12% | 34.81–55.87% |
| Variant 3 | Rapid Rounds | 8,800 | 234 | 34 / 69 | 49.28% | 37.83–60.79% |

Extra items are permitted in the ownership groups.
The groups can overlap, so their counts cannot be added.
The matched checkpoint-state baseline is 46.34% across 4,428 hero appearances.
The overall Infernus test baseline is 47.26%.
All three intervals include both baseline rates.

The default path costs 8,800 souls: 1,600 + 1,600 + 800 + 1,600 + 2,400 + 800.
Its Rapid Recharge price includes credit for Extra Charge.
These prices use the saved catalog, not a claim about a later live patch.

## Tier rows and screen space

The complete layout places optional Tier 1, Tier 2, Tier 3, and Tier 4 rows below the core panel.
Those rows require separate supported continuation evidence.
The comparison did not validate a complete set of late-game continuation choices.
Therefore, this example does not invent item cards to fill those rows.

A further training-only check found no single Tier 2–4 addition or direct upgrade with 200 joint owners at 30:01.
That check preserves the rest of this particular default core.
It does not rule out a supported path that replaces several components over multiple steps.
This limitation is another reason to keep the output experimental.

The [full display design](display-design.md) shows the tier-row budgets and the earlier Swift/Titanic family.
The [evidence file](results/infernus-display-evidence.json) preserves complete item lists, orders, costs, and statistics.
