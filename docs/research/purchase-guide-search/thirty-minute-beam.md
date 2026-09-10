# Pure beam search: 20-minute and 30-minute checkpoints

The 30-minute checkpoint increases supported guide coverage and median core cost.
The results do not establish better win outcomes.

Both runs use state-aware beam search at width 16.
Neither run uses ECLAT candidates, Leiden communities, group anchors, or baseline build fallbacks.
The scoring model stays fixed between checkpoints for each hero.
The source contains 38 heroes from the same patch and rank range.

| Measure | Before 20 minutes | Before 30 minutes |
| --- | ---: | ---: |
| Heroes with an even-state default | 36 | 37 |
| Hero/state combinations with guides | 90 | 93 |
| Selected routes across three states | 232 | 251 |
| Distinct selected cores | 224 | 248 |
| Defaults with at least 100 validation owners | 28 | 30 |
| Median default cost | 9,600 | 12,800 |
| Median default core size | 4 | 4 |
| Search time, seconds | 1.45 | 2.49 |
| Mean overlap between selected cores | 0.561 | 0.557 |
| Validation ownership coverage | 14.1% | 17.8% |

Search time excludes data loading and guide admission.
Combined nomination for both checkpoints took 287.29 seconds.
The mechanics replay checked all 14,440 terminal routes and found no validity errors.

At 30 minutes, 18 defaults contain Tier 4 items. At 20 minutes, three defaults contain Tier 4 items.
However, 24 of the 37 defaults at 30 minutes still contain only four core items.
A longer ownership window does not create a separate Late Core stage.
That stage needs a continuation from the selected inventory, with separate support checks.

Pure beam produces no even-state default for McGinnis at 30 minutes.
At 20 minutes, it produces no even-state default for Bebop or Yamato.
The fixed support checks cause these exclusions. The experiment does not reduce those checks.
Full Viscous purchase sequences and all tier pools appear in [the build examples](thirty-minute-viscous-builds.md).

## Method and limits

Core ownership means that the player owns every specified core item before the checkpoint.
A core can contain four to six items and cost at most 19,200 souls.
The search requires 200 discovery owners in the requested wealth state.
Purchase scoring requires 30 observations in the matching item and wealth cell.
Bayesian smoothing uses a prior strength of 1,000. The uncertainty multiplier is 0.5.
Cost scaling is 0.5. The sequence discount is 0.97.
Guide admission requires 100 core owners in each discovery and selection partition.
The complete core order requires at least 20 followers and a 10% share in each partition.
Each required purchase needs at least 20 discovery buyers.
The display sample keeps the first three supported distinct cores per state, in search-score order.
This display limit does not change beam width or remove search candidates from the saved results.
Core overlap uses intersection size divided by union size. A value of one means identical cores.
Coverage counts validation players who own at least one selected core, within the requested state.
The nomination file was written before this experiment evaluated validation outcomes.
These captured matches supported earlier research. This comparison is exploratory, not a new untouched test set.
The 30-minute cohort excludes matches that ended earlier. Wealth states can also change between checkpoints.
Observed win-rate differences therefore do not establish an algorithm benefit or an item effect.
The win rates describe core ownership. They do not describe every optional item or the exact displayed purchase sequence.
No win-rate threshold filters these results.
The experiment preserves all supported Tier 1–4 pools in its Markdown output.
The production default and Steam display remain unchanged by this experiment.

## Even-state defaults

Even state means player net worth is between 90% and 110% of the match average.
Purchase costs are cumulative item costs. They are not measured player net worth.

| Hero | Before 20 minutes | Before 30 minutes |
| --- | --- | --- |
| Infernus | Rapid Recharge · Spirit Lifesteal · Suppressor · Enchanter's Emblem<br>8000 souls<br>51.9% (56/108); 95% interval 42.5%–61.0%; hero 46.7% (4154 matches) | Rapid Recharge · Spiritual Overflow · Titanic Magazine · Healbane · Enchanter's Emblem<br>14400 souls<br>51.9% (40/77); 95% interval 41.0%–62.7%; hero 45.5% (3407 matches) |
| Seven | Spirit Shielding · Arcane Surge · Mystic Vulnerability · Superior Duration<br>8000 souls<br>51.4% (71/138); 95% interval 43.2%–59.6%; hero 50.5% (2691 matches) | Spirit Shielding · Arcane Surge · Healbane · Superior Duration · Escalating Exposure<br>14400 souls<br>52.1% (125/240); 95% interval 45.8%–58.3%; hero 46.6% (2142 matches) |
| Vindicta | Quicksilver Reload · Rapid Recharge · Long Range · Swift Striker<br>8000 souls<br>58.0% (582/1004); 95% interval 54.9%–61.0%; hero 56.1% (3853 matches) | Quicksilver Reload · Sharpshooter · Enchanter's Emblem · Swift Striker<br>8000 souls<br>53.0% (53/100); 95% interval 43.3%–62.5%; hero 60.0% (3055 matches) |
| Lady Geist | Berserker · Healbane · Radiant Regeneration · Bullet Resist Shredder<br>9600 souls<br>35.8% (24/67); 95% interval 25.4%–47.8%; hero 44.5% (1509 matches) | Berserker · Healbane · Radiant Regeneration · Bullet Resist Shredder<br>9600 souls<br>36.7% (44/120); 95% interval 28.6%–45.6%; hero 45.4% (1258 matches) |
| Abrams | Melee Charge · Hunter's Aura · Bullet Resist Shredder · Enchanter's Emblem<br>8000 souls<br>63.4% (45/71); 95% interval 51.8%–73.6%; hero 51.3% (4249 matches) | Arcane Surge · Restorative Locket · Healing Booster · Spirit Snatch<br>8000 souls<br>56.3% (148/263); 95% interval 50.2%–62.1%; hero 56.9% (3388 matches) |
| Wraith | Quicksilver Reload · Tesla Bullets · Dispel Magic · Enchanter's Emblem<br>9600 souls<br>50.9% (170/334); 95% interval 45.6%–56.2%; hero 48.4% (4023 matches) | Ricochet · Dispel Magic · Mercurial Magnum · Enchanter's Emblem · Swift Striker<br>19200 souls<br>49.0% (171/349); 95% interval 43.8%–54.2%; hero 44.5% (2865 matches) |
| McGinnis | Heroic Aura · Intensifying Magazine · Healbane · Enchanter's Emblem<br>8000 souls<br>59.2% (100/169); 95% interval 51.6%–66.3%; hero 53.6% (1762 matches) | No supported default |
| Paradox | Compress Cooldown · Express Shot · Veil Walker · Trophy Collector<br>9600 souls<br>69.9% (72/103); 95% interval 60.5%–77.9%; hero 51.5% (4794 matches) | Compress Cooldown · Veil Walker · Hollow Point · Trophy Collector<br>9600 souls<br>57.0% (200/351); 95% interval 51.8%–62.1%; hero 55.1% (3896 matches) |
| Dynamo | Rapid Recharge · Trophy Collector · Warp Stone · Headhunter<br>11200 souls<br>58.0% (69/119); 95% interval 49.0%–66.5%; hero 54.4% (2850 matches) | Superior Duration · Trophy Collector · Warp Stone · Headhunter<br>11200 souls<br>61.5% (59/96); 95% interval 51.5%–70.6%; hero 57.9% (2401 matches) |
| Kelvin | Improved Spirit · Healing Booster · Healbane · Trophy Collector<br>6400 souls<br>65.9% (110/167); 95% interval 58.4%–72.6%; hero 59.4% (2140 matches) | Enduring Speed · Escalating Exposure · Trophy Collector · Superior Cooldown<br>12800 souls<br>61.5% (75/122); 95% interval 52.6%–69.6%; hero 59.7% (1858 matches) |
| Haze | Veil Walker · Surge of Power · Bullet Resist Shredder · Enchanter's Emblem<br>9600 souls<br>61.2% (139/227); 95% interval 54.8%–67.3%; hero 49.6% (4208 matches) | Active Reload · Capacitor · Surge of Power · Fury Trance · Burst Fire<br>17600 souls<br>48.7% (94/193); 95% interval 41.7%–55.7%; hero 48.1% (3198 matches) |
| Holliday | Rapid Recharge · Veil Walker · Recharging Rush · Trophy Collector<br>9600 souls<br>53.7% (180/335); 95% interval 48.4%–59.0%; hero 50.1% (2281 matches) | Rapid Recharge · Veil Walker · Recharging Rush · Tankbuster · Superior Duration · Trophy Collector<br>16000 souls<br>51.9% (134/258); 95% interval 45.9%–58.0%; hero 49.9% (2016 matches) |
| Bebop | No supported default | Counterspell · Slowing Hex · Spirit Snatch · Fleetfoot<br>9600 souls<br>55.6% (55/99); 95% interval 45.7%–65.0%; hero 52.7% (4464 matches) |
| Calico | Torment Pulse · Cold Front · Trophy Collector · Spirit Snatch<br>9600 souls<br>58.7% (364/620); 95% interval 54.8%–62.5%; hero 52.5% (4436 matches) | Torment Pulse · Mystic Vulnerability · Trophy Collector · Spirit Snatch · Arctic Blast<br>16000 souls<br>53.0% (175/330); 95% interval 47.6%–58.3%; hero 52.3% (3610 matches) |
| Grey Talon | Improved Spirit · Compress Cooldown · Enchanter's Emblem · Swift Striker<br>6400 souls<br>51.2% (43/84); 95% interval 40.7%–61.6%; hero 47.2% (1758 matches) | Battle Vest · Tankbuster · Superior Cooldown · Swift Striker<br>9600 souls<br>50.0% (31/62); 95% interval 37.9%–62.1%; hero 52.1% (1468 matches) |
| Mo & Krill | Compress Cooldown · Torment Pulse · Cold Front · Warp Stone<br>9600 souls<br>56.8% (63/111); 95% interval 47.5%–65.6%; hero 54.7% (4483 matches) | Torment Pulse · Cold Front · Spirit Resilience · Warp Stone<br>11200 souls<br>55.1% (200/363); 95% interval 50.0%–60.1%; hero 54.5% (3739 matches) |
| Shiv | Torment Pulse · Suppressor · Restorative Locket · Healbane · Radiant Regeneration<br>11200 souls<br>54.2% (186/343); 95% interval 48.9%–59.4%; hero 51.2% (3384 matches) | Torment Pulse · Suppressor · Restorative Locket · Healbane · Radiant Regeneration<br>11200 souls<br>61.3% (252/411); 95% interval 56.5%–65.9%; hero 53.8% (2928 matches) |
| Ivy | Quicksilver Reload · Capacitor · Healbane · Fleetfoot<br>11200 souls<br>56.2% (72/128); 95% interval 47.6%–64.5%; hero 55.5% (3990 matches) | Capacitor · Healbane · Fleetfoot · Mercurial Magnum<br>16000 souls<br>58.7% (105/179); 95% interval 51.3%–65.6%; hero 56.1% (3272 matches) |
| Warden | Battle Vest · Intensifying Magazine · Bullet Resist Shredder · Mercurial Magnum · Kinetic Dash<br>12800 souls<br>61.3% (19/31); 95% interval 43.8%–76.3%; hero 49.5% (5047 matches) | Battle Vest · Spirit Resilience · Intensifying Magazine · Bullet Resist Shredder · Mercurial Magnum · Kinetic Dash<br>16000 souls<br>46.2% (24/52); 95% interval 33.3%–59.5%; hero 46.5% (4012 matches) |
| Yamato | No supported default | Recharging Rush · Healbane · Spirit Snatch · Mystic Reverb<br>12800 souls<br>62.2% (56/90); 95% interval 51.9%–71.5%; hero 54.8% (2354 matches) |
| Lash | Quicksilver Reload · Siphon Bullets · Recharging Rush · Restorative Locket · Bullet Resist Shredder<br>12800 souls<br>57.4% (54/94); 95% interval 47.4%–67.0%; hero 54.9% (6061 matches) | Quicksilver Reload · Siphon Bullets · Recharging Rush · Restorative Locket · Bullet Resist Shredder<br>12800 souls<br>60.2% (631/1048); 95% interval 57.2%–63.1%; hero 57.0% (5172 matches) |
| Viscous | Improved Spirit · Veil Walker · Tankbuster · Trophy Collector<br>9600 souls<br>53.0% (134/253); 95% interval 46.8%–59.0%; hero 52.0% (2688 matches) | Crushing Fists · Lifestrike · Trophy Collector · Spirit Snatch<br>14400 souls<br>53.9% (103/191); 95% interval 46.8%–60.8%; hero 54.3% (2322 matches) |
| Pocket | Majestic Leap · Cultist Sacrifice · Enchanter's Emblem · Swift Striker<br>9600 souls<br>46.6% (102/219); 95% interval 40.1%–53.2%; hero 43.2% (3468 matches) | Majestic Leap · Cold Front · Mystic Vulnerability · Swift Striker<br>8000 souls<br>46.3% (144/311); 95% interval 40.8%–51.9%; hero 44.2% (3134 matches) |
| Mirage | Suppressor · Healbane · Dispel Magic · Headhunter<br>9600 souls<br>50.5% (49/97); 95% interval 40.7%–60.3%; hero 44.2% (1667 matches) | Compress Cooldown · Suppressor · Kinetic Dash · Headhunter<br>8000 souls<br>43.9% (47/107); 95% interval 34.9%–53.4%; hero 43.8% (1349 matches) |
| Vyper | Tesla Bullets · Burst Fire · Bullet Resist Shredder · Split Shot<br>9600 souls<br>60.2% (56/93); 95% interval 50.1%–69.6%; hero 51.6% (1990 matches) | Tesla Bullets · Bullet Resist Shredder · Split Shot · Mercurial Magnum<br>12800 souls<br>48.2% (67/139); 95% interval 40.1%–56.4%; hero 49.6% (1590 matches) |
| Sinclair | Improved Spirit · Rapid Recharge · Trophy Collector · Enchanter's Emblem<br>8000 souls<br>57.9% (106/183); 95% interval 50.7%–64.8%; hero 52.3% (1567 matches) | Veil Walker · Boundless Spirit · Superior Duration · Enchanter's Emblem<br>14400 souls<br>61.3% (92/150); 95% interval 53.3%–68.8%; hero 55.6% (1368 matches) |
| Mina | Stamina Mastery · Spirit Sap · Reactive Barrier · Dispel Magic<br>9600 souls<br>44.7% (92/206); 95% interval 38.0%–51.5%; hero 45.7% (4057 matches) | Stamina Mastery · Spirit Burn · Spirit Sap · Reactive Barrier · Dispel Magic<br>16000 souls<br>58.7% (81/138); 95% interval 50.4%–66.6%; hero 47.2% (3647 matches) |
| Drifter | Melee Charge · Veil Walker · Trophy Collector · Spirit Snatch<br>9600 souls<br>58.4% (241/413); 95% interval 53.5%–63.0%; hero 51.9% (5323 matches) | Melee Charge · Veil Walker · Trophy Collector · Spirit Snatch<br>9600 souls<br>58.7% (237/404); 95% interval 53.8%–63.4%; hero 53.9% (4493 matches) |
| Venator | Bullet Lifesteal · Weakening Headshot · Restorative Locket · Fleetfoot<br>6400 souls<br>40.7% (125/307); 95% interval 35.4%–46.3%; hero 43.0% (2726 matches) | Battle Vest · Weakening Headshot · Restorative Locket · Fleetfoot<br>6400 souls<br>41.7% (118/283); 95% interval 36.1%–47.5%; hero 43.0% (2424 matches) |
| Victor | Improved Spirit · Torment Pulse · Spirit Lifesteal · Mystic Vulnerability · Enduring Speed<br>9600 souls<br>53.0% (222/419); 95% interval 48.2%–57.7%; hero 51.1% (2815 matches) | Improved Spirit · Torment Pulse · Greater Expansion · Infuser · Enduring Speed<br>16000 souls<br>55.7% (312/560); 95% interval 51.6%–59.8%; hero 49.3% (2160 matches) |
| Paige | Guardian Ward · Knockdown · Rescue Beam · Trophy Collector<br>9600 souls<br>57.3% (82/143); 95% interval 49.1%–65.2%; hero 56.0% (2957 matches) | Guardian Ward · Knockdown · Rescue Beam · Trophy Collector<br>9600 souls<br>60.7% (74/122); 95% interval 51.8%–68.9%; hero 58.3% (2590 matches) |
| The Doorman | Improved Spirit · Rapid Recharge · Tankbuster · Trophy Collector<br>9600 souls<br>49.2% (65/132); 95% interval 40.9%–57.7%; hero 49.7% (1714 matches) | Compress Cooldown · Rapid Recharge · Tankbuster · Trophy Collector<br>9600 souls<br>46.5% (47/101); 95% interval 37.1%–56.2%; hero 52.3% (1592 matches) |
| Billy | Stalker · Spirit Shielding · Battle Vest · Point Blank<br>8000 souls<br>54.1% (86/159); 95% interval 46.3%–61.6%; hero 51.1% (3450 matches) | Stalker · Spirit Shielding · Battle Vest · Dispel Magic<br>8000 souls<br>59.6% (62/104); 95% interval 50.0%–68.5%; hero 53.2% (2920 matches) |
| Graves | Mystic Shot · Arcane Surge · Heroic Aura · Enchanter's Emblem<br>8000 souls<br>63.8% (113/177); 95% interval 56.5%–70.6%; hero 56.0% (2453 matches) | Mystic Shot · Arcane Surge · Heroic Aura · Enchanter's Emblem<br>8000 souls<br>59.8% (110/184); 95% interval 52.6%–66.6%; hero 54.8% (2026 matches) |
| Apollo | Cold Front · Restorative Locket · Healbane · Spirit Snatch<br>8000 souls<br>55.2% (154/279); 95% interval 49.3%–60.9%; hero 52.3% (2158 matches) | Cold Front · Restorative Locket · Boundless Spirit · Healbane · Superior Cooldown<br>14400 souls<br>63.3% (88/139); 95% interval 55.0%–70.9%; hero 56.7% (1812 matches) |
| Rem | Guardian Ward · Slowing Hex · Healing Booster · Trophy Collector<br>6400 souls<br>54.7% (82/150); 95% interval 46.7%–62.4%; hero 53.5% (2524 matches) | Divine Barrier · Healing Booster · Cursed Relic · Trophy Collector<br>16000 souls<br>61.4% (102/166); 95% interval 53.9%–68.5%; hero 55.6% (2000 matches) |
| Silver | Stalker · Slowing Hex · Restorative Locket · Hunter's Aura<br>8000 souls<br>51.4% (36/70); 95% interval 40.0%–62.8%; hero 46.2% (1525 matches) | Stalker · Slowing Hex · Restorative Locket · Hunter's Aura<br>8000 souls<br>53.8% (43/80); 95% interval 42.9%–64.3%; hero 50.6% (1222 matches) |
| Celeste | Spirit Shielding · Torment Pulse · Restorative Locket · Radiant Regeneration<br>9600 souls<br>57.8% (616/1066); 95% interval 54.8%–60.7%; hero 55.2% (2524 matches) | Spirit Shielding · Torment Pulse · Radiant Regeneration · Witchmail · Dispel Magic<br>17600 souls<br>59.3% (67/113); 95% interval 50.1%–67.9%; hero 55.5% (2156 matches) |

## Artifacts and reproduction

The captured source is `generated/beam-integration/source/results/master-0ecad50`.
The experiment files are in `generated/beam-checkpoints/all-heroes`.
The files contain frozen routes, guide pools, validation results, and mechanics replay counts.
The [summary JSON](results/thirty-minute-beam-summary.json) records source hashes, settings, and implementation hashes.

Run both phases with a new output directory:

```bash
uv run python -m tools.beam_comparison.checkpoints \
  --source generated/beam-integration/source/results/master-0ecad50 \
  --output generated/beam-checkpoints/repeated \
  --phase nominate
uv run python -m tools.beam_comparison.checkpoints \
  --source generated/beam-integration/source/results/master-0ecad50 \
  --output generated/beam-checkpoints/repeated \
  --phase evaluate
```

After the experiment started, six administration SQL files lost comments about a removed custom SQL checker.
The experiment does not use those administration queries.
The saved summary identifies these comment changes.
The earlier frozen hashes remain unchanged.

## Verification

The complete fast local gate passed after removal of the custom SQL checker.
SQLFluff passed with the DuckDB configuration and standard exceptions.
All 1,535 tests passed with warnings treated as errors.
Statement coverage was 97.08%. Branch coverage was 91.87%.
The wheel contained all 53 product SQL resources.
Both CLI help commands passed outside the source checkout.
The wheel check also verified all installed SQL resources against the source files.
No live Steam sync ran. No commit was created.
The Tier 3–4 Steam display change remains on hold at the user's request.
