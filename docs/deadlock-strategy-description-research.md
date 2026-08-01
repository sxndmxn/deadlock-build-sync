# Research specification: generating tactical Deadlock build descriptions

**Status:** research and implementation specification

**As of:** 2026-07-26

**Primary data source:** [Deadlock API](https://api.deadlock-api.com/docs) and the
[deadlock-api repository](https://github.com/deadlock-api/deadlock-api)

**Current reference cohort:** normal-mode matches from the patch beginning
2026-07-09, Ascendant VI and above (`min_average_badge=106`)

## 1. Purpose

This document defines the data and reasoning needed to generate useful build
descriptions with four headings:

- **I** — how to play around the Tier I purchases in this build;
- **II** — how the Tier II purchases change the job;
- **III** — how to exploit the Tier III power spike;
- **IV** — how to convert or stabilize with Tier IV purchases.

The desired output is tactical. It should tell a player where to stand, what
pressure to create, whom to target, how to sequence abilities and active items,
when to farm or rotate, and when to commit, reset, or disengage. Item and
ability descriptions are evidence supplied to the model, not text to copy into
the published summary.

This is a research specification, not a code change. It does not prescribe one
universal build or claim that observed win rates prove causation.

## 2. Executive conclusions

1. **An item tier is a price class, not a game phase.** The current shop prices
   are 800, 1,600, 3,200, and 6,400 souls for Tiers I–IV. A player can buy an
   800-soul item at 40 minutes before a decisive fight. Therefore, a heading
   named `I` must not automatically say “early game.”
2. **Use each item's purchase distribution to infer its role in this build.**
   A Tier I item bought by most players near the opening is foundational. A
   Tier I item whose meaningful purchase window is late is a cheap tactical
   fill, countermeasure, or last-minute active—not evidence that the game is
   still in “quarter one.”
3. **A power spike is a state change, not merely a high win-rate point.** It can
   come from an item, an investment threshold, an ability unlock or upgrade,
   an inventory slot, a cooldown combination, a matchup, or a temporary map
   objective. It is useful only if the description names the action it enables.
4. **Win rate must be contextualized.** Compare an item/path to the same hero,
   patch, rank, mode, and duration cohort. Use volume and uncertainty. Do not
   compare every observed item win rate to 50%.
5. **The public website's “pick rate” is a relative popularity index.** In the
   current item table and purchase guide, the most-used item is shown as 100%
   and other items are scaled against its match count. That is useful for
   sorting but is not the percentage of hero games in which an item was bought.
6. **Current high-rank matches are concentrated around 30–40 minutes.** In the
   reference snapshot, roughly 58.6% ended in that interval, while only about
   1.4% reached 50 minutes. Tier IV prose should optimize for the common
   30–45-minute state while still including a short contingency for exceptional
   50-minute games.
7. **The first three minutes need a net-worth data guardrail.** Raw matches can
   lack a timeline sample before 180 seconds. In at least one validated match,
   purchases before that first sample inherited final net worth. For purchases
   before 180 seconds, game time is trustworthy for timing but
   `net_worth_at_buy` must be treated as missing unless independently derived.
8. **The best generator is evidence-first and patch-bound.** Fetch current
   assets, the build, ability path, hero baselines and duration curve, item
   timing/flow, match-duration distribution, and objective rules; assemble a
   compact structured evidence packet; then ask Codex for four tactical
   paragraphs under strict output and evidence rules.

## 3. The central model: price tiers are not chronological quarters

The interface should use the visual order `I`, `II`, `III`, `IV`, because those
are the actual item-price tiers. The prose underneath each heading may often
progress from setup to completion, but chronology must be inferred rather than
hard-coded.

For every item, classify its observed purchase behavior:

| Timing class | Evidence | How the prose should treat it |
|---|---|---|
| Opening foundation | Most supported buys cluster in the opening; item is normally retained | Establish lane/trade/farm pattern |
| Bridge purchase | Bought while saving for a larger threshold or solving a temporary weakness | Explain what it lets the player do until the next spike |
| Core completion | High-volume purchase window aligns with an ability or investment breakpoint | Name the new engage, damage, control, or sustain pattern |
| Situational counter | Timing and pick frequency vary strongly with enemy lineup or game state | Use conditional language: “against…,” “when…,” “if…” |
| Late cheap fill | Low-tier item is bought at high game time or high *valid* net worth | Treat as efficient pre-fight utility, not an early-game item |
| Replacement/respec | Appears after sell events or a saturated inventory | Explain the tradeoff and what is being replaced |

This prevents two opposite errors:

- forcing every Tier I item into an “early game” paragraph; and
- discarding legitimate late Tier I purchases merely because their price is
  low.

The actual anomaly to filter is narrower: **an early timestamp combined with
final-game net worth because no early economy snapshot existed.** A genuine
late timestamp plus high net worth is valid evidence.

## 4. Evidence hierarchy and freshness

Deadlock changes quickly. Every generated description should carry a patch
identifier and an `as_of` timestamp. When sources conflict, use this order:

1. current API assets and generic data;
2. current official patch data or Valve-published notes;
3. raw match metadata/timelines from the same patch;
4. aggregated Deadlock API analytics from the same cohort;
5. the current website implementation, for understanding displayed metrics;
6. reputable community mechanics pages, clearly marked as secondary;
7. older guides, wikis, and prose only as hypotheses to verify.

For example, community pages can lag changes to neutral spawn times or the
Rejuvenator duration. Current generic data and recent patch notes take
precedence. The [2026-06-30 update](https://steamcommunity.com/games/1422450/announcements/detail/688635449342692004)
changed several relevant values, including Guardian and Walker bounties and
Rejuvenator duration. The [2026-05-22 update](https://steamcommunity.com/games/1422450/announcements/detail/670617878982034053)
changed neutral/breakable timing and structure rules. A generator must not
silently blend observations from before and after those changes.

### 4.1 Cohort contract

Every analytic input should repeat the same explicit cohort:

```text
patch_id / patch_title
patch_start
patch_end (or now)
game_mode
rank_min / rank_max
hero_id
region, if intentionally restricted
match_duration bounds
final_net_worth bounds, if used
account filters, if used
minimum sample threshold
retrieved_at
```

`min_average_badge=106` means **Ascendant VI and above** under the API's
`tier × 10 + subrank` encoding. It should not be labeled “Phantom+.”

When comparing two metrics, reject the comparison if mode, patch, rank, hero,
or duration selection differs without an explicit reason.

## 5. What the Deadlock API makes available

The public surface is broader than the fields needed for build prose. This
section maps the whole API by domain, then identifies the strategically useful
parts.

### 5.1 Assets: what heroes, abilities, items, ranks, and the map are

| Endpoint/domain | Available information | Use in description generation |
|---|---|---|
| `/v1/assets/heroes` | Hero names, role/playstyle text, abilities, scaling, statistics, ability/item references, level information, purchase and investment bonuses | Ground the hero job, ability sequencing, range, scaling, and breakpoints |
| `/v1/assets/items` | Item/upgrade identity, tier, cost, category/slot, active/passive status, description, properties, component/upgrades | Understand what a purchase enables and identify actives that demand explicit instructions |
| `/v1/assets/generic-data` | Global prices, progression rules, objective values, Rejuvenator parameters, and other tuning constants | Resolve shop tiers, objective incentives, shared progression, and patch-sensitive mechanics |
| `/v1/assets/map` | Objective positions/types, lane/zipline geometry, images and map metadata | Translate a spike into lane pressure, rotations, and objective conversion |
| `/v1/assets/npc-units` | Troopers, neutral units, structures, boss-like units and their properties | Explain farming, wave pressure, structure damage, and neutral priorities |
| `/v1/assets/misc-entities` | Powerups, breakables, objective/helper entities and timers | Add map-economy actions without relying on stale guide text |
| `/v1/assets/ranks` | Rank IDs, subranks, names, colors/images | Correctly label a cohort |
| Other asset routes | Accolades, build tags, client versions, colors, loot tables, Steam information, and the asset index | Useful for presentation, versioning, discovery, and build metadata; usually not tactical evidence |

The assets response may include disabled or development heroes/items. Filter on
current selectability/shop availability rather than assuming every asset is
playable. At the reference date, the asset list is larger than the current
selectable hero roster.

### 5.2 Analytics: what happened in matches

| Endpoint | Unit and major fields | Strategic question it can answer | Important limitation |
|---|---|---|---|
| `/v1/analytics/item-stats` | Item × requested bucket; wins, losses, matches, players, average buy/sell times | How often and when was this item bought, and what outcomes co-occurred? | Observational; purchase rows can differ from distinct hero-match adoption |
| `/v1/analytics/item-flow-stats` | Stage nodes/edges, stage baseline, reached population, adjusted/raw outcomes | Which item transitions are common, and how does a path evolve across stages? | Fixed stages, survivorship, and wealth/choice confounding; not causal |
| `/v1/analytics/item-permutation-stats` | Unordered item combinations/sets | Which completed groups coexist successfully? | No purchase order |
| `/v1/analytics/ability-order-stats` | Ordered ability/upgrade ID vector, matches, players, wins/losses, K/D/A | Which ability paths have enough evidence and how do outcomes differ? | The chosen path is still correlated with matchup, player skill, and game state |
| `/v1/analytics/hero-stats` | Hero wins/losses/matches plus K/D/A, net worth, last hits/denies, player/objective/neutral damage, healing and other aggregates | What is the hero baseline for the exact cohort? | Aggregate endpoints do not explain why |
| `/v1/analytics/game-stats` | Match count, duration, economy/combat averages, ending level, first Mid Boss/objective timing, boss rates | What game states and durations are common enough to optimize for? | Cohort averages can hide multimodal games |
| `/v1/analytics/player-performance-curve` | Absolute or normalized time series for net worth, combat, and economy sources | When does a typical hero accumulate resources or change pace? | Absolute samples begin at 180 seconds in the current implementation |
| `/v1/analytics/hero-build-stats/{hero_id}` | First database build selected at match start and outcome aggregates | Which published build was initially selected? | Does not capture later build switching; coverage starts in 2026-03 |
| `/v1/analytics/build-item-stats` | How often items appear in public builds | What guide authors recommend | This is publication frequency, not match performance or purchase order |
| Hero counters/synergies/combinations | Matchup and team-composition outcomes | Does the tactical job change with allies/enemies? | Composition correlations are not item effects |
| Scoreboards, kill/death, bans, badge distribution, player metrics | Population, combat, draft, rank, and player summaries | Supplementary cohort and playstyle checks | Often the wrong unit for an item-path claim |

`item-stats` supports unusually rich filtering: hero(s), enemy hero(s), any/all
enemy matching, enemy final net worth, same-lane matchups, patch timestamps,
duration, final net worth, rank/badge, included/excluded items, accounts,
purchase time bounds, and item-order constraints. Its buckets include absolute
game time, normalized game time, multiple net-worth increments, and calendar
time. This makes it the main aggregate source for per-item purchase windows.

The item-order filters are constraints, not a complete sequence model. If both
specified items are present, the requested order is enforced; a match missing
one of them can still satisfy the broader query. Use raw match data when an
exact, complete ordered path is required.

### 5.3 Matches and demos: the raw evidence layer

The match domain exposes:

- match metadata and bulk metadata;
- active matches, recently fetched matches, salts, and fetch queues;
- demo download, submission, processing status, schemas, formatting, live
  queries, and event/table extraction;
- live URLs and custom-match lifecycle routes.

For this project, bulk metadata is the crucial validation source. It includes
match information, player/hero records, purchases and sell events, statistics
timelines, final statistics, deaths, objectives, and Mid Boss events. It can be
used to:

- count distinct hero appearances;
- count distinct buyers rather than purchase rows;
- reconstruct exact order, rebuy, sell, and replacement behavior;
- validate whether a net-worth-at-buy value is plausible;
- condition a recommendation on the state immediately before a purchase.

The bulk endpoint is rate-limited more tightly than ordinary analytics and
returns at most a bounded batch, so it should validate or enrich aggregates,
not replace every aggregate query. The current documentation should be checked
for live limits before running a production collector.

### 5.4 Builds, players, leaderboards, patches, GraphQL, SQL, and service data

| Domain | What is exposed | Relevance |
|---|---|---|
| Builds | Search/query, details, item sections, tags and related build data | Retrieve the exact guide being summarized and its tier membership |
| Players | Match history, account/hero/enemy/mate statistics, cards, MMR history/distribution, rank prediction and Steam lookup | Personalization and mastery analysis, subject to privacy and consent |
| Leaderboards | Ranked population and leaderboard records | Cohort context, not a direct tactical signal |
| Patches | Patch feed and major-patch days (including v2 feed) | Bind every result to the correct ruleset and detect invalidation |
| GraphQL | Projected asset/analytic querying and filters | Efficient custom data selection when REST overfetches |
| SQL | Controlled query surface | Advanced research only; keep queries bounded and audited |
| Info/servers | Health, API information, server lists/status/metrics | Operational monitoring, not build prose |
| Auth/patron/privacy | Patreon and account association, privacy controls | Access and user rights; never treat private identity as free analytic data |
| Commands/variables | Game/server command metadata | Research and tooling support; generally outside build prose |

The public docs advertise shared analytic rate limits and endpoint-specific
caching. A production pipeline should record response timestamps, respect
`Retry-After`, cache immutable asset versions locally, and never assume a fresh
HTTP response means fresh underlying match data.

## 6. How the current Item Stats and Purchase Analysis work

The implementation inspected for this document is the website at commit
`e7bd075b558548745fdf9700cee425572264963f`.

### 6.1 Item Stats table

The table fetches aggregated item statistics for the selected filters and lets
the user inspect wins, losses, match volume, buy timing, and related values.
The displayed **Pick rate** is currently:

```text
item.matches / maximum_item_matches_in_the_current_table
```

Consequently, one item is always 100% within the current result set. This is a
relative popularity index. It is suitable for ordering icons by observed
frequency, but it must not be described as “bought in 73% of hero games.”

An exact hero-game adoption rate should instead use:

```text
distinct (match_id, account_id) hero players who bought the item
----------------------------------------------------------------
distinct (match_id, account_id) hero players in the same cohort
```

The numerator must deduplicate rebuys. The denominator can come from hero
appearances in raw metadata or an exactly aligned hero-stat cohort.

### 6.2 Per-item Purchase Analysis

The chart supports three views:

- net worth at purchase, bucketed by souls;
- absolute game time in minutes;
- normalized game time as a percentage of total match duration.

The default visual score is a Wilson lower confidence bound, called a
conservative estimate in the interface. Raw win rate remains available in the
tooltip. The chart adaptively combines sparse buckets, applies a moving average
for visual readability, and uses a minimum sample requirement that rises with
the number of observations.

Each view answers a different question:

- **Net worth:** at what economy state did buyers tend to succeed?
- **Absolute time:** when on the clock was the purchase made?
- **Normalized time:** how far through that particular match was it made?

None is a causal treatment effect. Net worth is especially confounded: players
who are ahead can buy expensive items earlier, and winners may survive long
enough to make purchases that losers never reach. Normalized time is useful for
comparing games of different length but leaks final duration into the bucket
definition, so it is unsuitable for a live in-game predictor unless duration is
estimated rather than known.

### 6.3 Tiered Purchase Guide

The purchase-guide helper:

1. groups shop items into Tiers I–IV;
2. computes adaptive net-worth buckets using candidate increments of 1k, 2k,
   3k, 5k, 7k, and 10k;
3. requires a window to have at least 20 purchase observations and at least 5%
   of that item's purchase observations across the relevant buckets;
4. finds local peaks by Wilson lower bound;
5. expands contiguous buckets whose scores stay within 0.07 of the peak;
6. keeps up to two non-overlapping windows;
7. computes a tier horizon as twice the weighted median purchase net worth for
   items in that tier, rounded up to 1k;
8. presents up to eight items per tier.

The UI can sort by:

- relative popularity (`item.matches / max item.matches`); or
- the strongest detected purchase window, then volume.

That is an excellent *discovery view*, but it is not yet a sufficient tactical
description. A generator must add hero abilities, path order, item function,
map state, duration exposure, and the difference between a core and a
situational purchase.

### 6.4 Pre-180-second net-worth caveat

A raw validation of match `95781377` found:

- a Kelvin purchase at 68 seconds;
- `net_worth_at_buy=33469`, equal to the player's final net worth;
- the first timeline economy sample at 180 seconds, with net worth 2017;
- later purchases mapping sensibly to the most recent timeline sample.

The player-performance-curve implementation also starts absolute samples at
180 seconds. The practical rule is:

```text
if purchase_time < first_available_economy_sample:
    keep purchase_time
    set net_worth_at_buy to unknown
    do not place it in a net-worth purchase bucket
```

If raw stats make independent reconstruction possible, derive an early economy
value and mark it `derived`; otherwise do not guess. This caveat can distort
the first fixed stage of item-flow analytics and Tier I net-worth windows. It
does **not** invalidate genuine low-tier purchases late in a match.

### 6.5 Item Flow stages and adjusted win rate

Normal-mode Item Flow currently uses four fixed purchase columns:

```text
0–9 minutes | 9–20 minutes | 20–30 minutes | 30+ minutes
```

Its response exposes item nodes, transitions between nodes, a stage baseline,
and how many players reached each column. `reached_per_column` is essential:
the population able to make a 30+ minute purchase is a selected subset of the
opening population.

The endpoint also reports an adjusted win rate. For normal mode, it
standardizes each item's result to the stage-wide distribution of net worth at
purchase in 5k buckets. This is more useful than raw win rate for reducing
simple wealth imbalance inside a stage, but it remains observational. It does
not control every pre-purchase difference, player skill, composition, reason
for buying, or later exposure.

Use Item Flow to describe a *common transition*, such as “utility bridge into
damage completion,” not to claim that following an edge causes a win. The
pre-180-second attribution caveat is especially relevant to column zero:
exclude or flag impossible opening net-worth values before trusting its
wealth-adjusted result.

## 7. Match duration: optimize for the games that actually occur

The following live snapshot used non-overlapping duration buckets for normal
mode, the current reference patch, and Ascendant VI+:

| Ending duration | Matches | Share |
|---:|---:|---:|
| Under 25 min | 1,325 | 6.66% |
| 25–30 min | 3,345 | 16.81% |
| 30–35 min | 6,475 | 32.53% |
| 35–40 min | 5,186 | 26.06% |
| 40–45 min | 2,465 | 12.38% |
| 45–50 min | 821 | 4.13% |
| 50+ min | 287 | 1.44% |
| **Total** | **19,904** | **100%** |

Small differences in totals can occur as cached endpoints refresh; a second
bulk snapshot contained 19,869 matches with essentially the same shares. The
important shape is stable:

- about 58.6% ended from 30–40 minutes;
- about 5.6% reached 45 minutes;
- about 1.4% reached 50 minutes.

The 50+ subset averaged roughly 53:21 duration, 67.7k final net worth, level
35.99, 65.0k player damage, and 58.7 neutral kills. It is a nearly max-level,
slot-saturated tail, not the default Tier IV state. It still matters as a
contingency: replace obsolete efficiency items, preserve buyable utility,
protect the highest-value player, control lanes before committing, and avoid
coin-flip fights without a conversion plan.

### 7.1 Hero curves are not interchangeable

Observed win rate by *ending-duration bucket* differed materially by hero in
the same reference cohort:

| Hero | Under 25 min | 30–35 min | 45–50 min | 50+ min |
|---|---:|---:|---:|---:|
| Lady Geist | 56.45% (372) | — | 42.59% (216) | 36.36% (77) |
| Abrams | 42.69% (424) | — | 55.79% (285) | 53.93% (89) |
| Wraith | 43.41% (668) | — | 53.44% (320) | 49.49% (99) |
| Kelvin | 49.07% (216) | 55.05% (1,090) | 57.38% (122) | 56.00% (50) |
| Haze | 46.38% (787) | — | 52.40% (479) | 51.88% (160) |
| Warden | 55.59% (331) | — | 46.33% (177) | 40.98% (61) |

These values are descriptive snapshots, not permanent hero identities. The
50+ samples are small. Most importantly, “win rate among games that ended at
minute 50+” is **not** “the hero's chance to win once the clock reaches minute
50.” Ending buckets include closeout ability, stomps, composition, player
mastery, and survivor selection.

Use the curve to form a tactical hypothesis:

- a hero declining in long-ending games may need to force objectives while a
  Tier III spike is live or use Tier IV durability/utility to remain relevant;
- a hero improving in longer games may need to farm safely, avoid low-value
  deaths, and fight only around completed thresholds;
- a build may deliberately compensate for the hero's natural curve.

Then verify that hypothesis against item function, actual purchase timing,
ability path, and sufficient volume.

## 8. Statistical guardrails

### 8.1 Compare against the correct baseline

For item \(i\), hero \(h\), and cohort \(c\):

```text
observed lift = WR(item i | hero h, cohort c) - WR(hero h | cohort c)
```

The hero baseline should be exposure-aligned when possible. An item available
only after a late stage should not be compared naively with all hero games,
including matches that ended before anyone could buy it. Useful alternatives
include:

- the population that reached the same flow column;
- hero games lasting at least the item's typical purchase time;
- matched wealth/time bands;
- a model controlling for pre-purchase state.

### 8.2 Use uncertainty, volume, and shrinkage

Wilson lower bounds are appropriate for conservative ranking because they
penalize tiny samples. They do not remove confounding. Store at least:

```text
wins, losses, matches, distinct_players, distinct_matches,
raw_win_rate, Wilson_interval, hero_baseline, observed_lift
```

Recommended publication gates:

- reject a window below both an absolute volume floor and a cohort-share floor;
- flag a path dominated by very few distinct players;
- shrink small-sample estimates toward the hero/cohort baseline;
- display or log the sample behind every generated claim;
- prefer a stable conclusion across adjacent buckets over a one-bucket spike.

### 8.3 Keep analytic units separate

There are at least four possible units:

1. match;
2. hero-player in a match;
3. purchase event;
4. published build.

“2,000 matches,” “2,000 buyers,” “2,000 purchases,” and “2,000 public builds”
are different facts. Every feature must name its unit. Rebuys and duplicate
purchase rows must not inflate adoption rate.

### 8.4 Confounders to carry into interpretation

- **Wealth:** winning players buy earlier/more.
- **Survivorship/exposure:** only long games can contain late purchases.
- **Choice:** better players may choose an item in the right situation.
- **Reverse causation:** the player bought defense because they were already
  being focused; the item's raw outcome can look worse despite being correct.
- **Composition and matchup:** damage type, control, range, and lane opponent
  change item value.
- **Mastery:** hero experience changes performance independently of the build.
- **Patch drift:** costs, abilities, objectives, and player adaptation change.
- **Duration selection:** buckets based on ending duration select different
  kinds of games.
- **Multiple comparisons:** searching hundreds of items/buckets will create
  impressive-looking peaks by chance.
- **Guide selection:** a selected public build is not necessarily followed.

The API has `min_hero_matches` support in some hero/player contexts, but not
every item/ability aggregate exposes the same mastery control. Record that gap
instead of pretending it is solved.

### 8.5 Language rules for observational data

Use:

- “is associated with”;
- “appears most often”;
- “the supported purchase window is”;
- “this suggests using the spike to…”;
- “conditional on reaching this state.”

Avoid:

- “causes a 7% win-rate increase”;
- “always buy at 18k”;
- “the best item” based on raw win rate alone;
- “late-game win probability” when the metric is an ending-duration bucket.

## 9. Deadlock systems that change how a build should be played

### 9.1 Shop prices and investment breakpoints

Current generic data gives the shop prices:

| Item tier | Price |
|---:|---:|
| I | 800 souls |
| II | 1,600 souls |
| III | 3,200 souls |
| IV | 6,400 souls |

Each purchase also supplies a category bonus whose size depends on item tier.
The current shared hero assets encode these Tier I–IV bonuses:

| Category | I | II | III | IV |
|---|---:|---:|---:|---:|
| Weapon damage | 4% | 8% | 13% | 18% |
| Base health | 7% | 8% | 9% | 10% |
| Spirit Power | 4 | 7 | 10 | 13 |

Items additionally contribute to cumulative category investment. Current hero
assets share investment thresholds at 800, 1,600, 2,400, 3,200, 4,800, 6,400,
8,000, 11,200, 16,000, 22,400, and 28,800 category spend. The jump at 4,800 is
especially important: a purchase can be valuable for its own mechanics, its
tier/category purchase bonus, and the investment threshold it crosses.

For the current shared curves, representative cumulative bonuses are:

| Category | Bonuses across the thresholds |
|---|---|
| Weapon | 9, 12, 15, 18, 46, 54, 62, 74, 86, 100, 115% |
| Vitality | 9, 12, 15, 20, 38, 42, 46, 50, 54, 60, 66% |
| Spirit | 7, 11, 15, 19, 38, 45, 52, 59, 66, 75, 100 Spirit Power |

The generator should calculate:

```text
category_spend_before
category_spend_after
thresholds_crossed
incremental_shared_bonus
```

That enables useful prose such as “take the next fight after this purchase
because it crosses the 4.8k Spirit investment threshold,” rather than merely
restating the item passive. These values are patch-sensitive and must be read
from assets, not embedded forever.

### 9.2 Ability and level breakpoints

Hero assets expose ability unlock/progression data and scaling. Current shared
level information places ability unlock currency at levels 1, 3, 5, and 8,
with ability points at other milestones. Standard level progression also adds
health and damage-related boons. Souls required rise through the level curve,
reaching level 36 at roughly 48.6k total souls in the reference assets.

For every ability path, derive:

- first access to each ability;
- ability-point upgrade milestones;
- a meaningful cooldown, duration, charge, radius, damage, or scaling change;
- synergy between that upgrade and the next item purchase;
- whether the build delays a defensive or mobility tool;
- whether an ultimate/active combination is ready for the next objective.

The ability path's aggregate win rate and match count are supporting evidence,
not a substitute for reading the ability properties.

### 9.3 Inventory pressure and slot unlocks

The current UI/localization indicates an initial extra slot and additional
slots unlocked after the team destroys one, two, and three enemy Walkers.
Therefore, structure pressure has build value beyond the direct bounty:

- a slot unlock can complete a combination without selling an efficient item;
- a team behind on Walkers may have a theoretically strong list that cannot
  fit cleanly;
- a late cheap item may be a correct fill when a slot has just opened;
- a saturated inventory changes the value of an 800-soul purchase and sell
  loss.

The description should mention structure pressure when the next meaningful
power spike is slot-constrained.

### 9.4 Lanes and structure chain

The current map has three lane/zipline paths. The strategic structure chain is:

```text
Guardian → Walker → Base Guardians → Shrines → Patron
```

Current objective tuning includes:

| Objective | Configured kill bounty in current generic data |
|---|---:|
| Guardian | 1,250 |
| Walker | 3,500 |
| Base Guardian | 1,000 each |
| Shrine | 2,000 |

A nearby-player share is also part of the bounty logic. Guardian resistance
scales from stronger to weaker over the opening 12 minutes, so “can hit a
Guardian” and “should force a Guardian now” are not identical.

Translate item spikes into concrete lane actions:

- shove one lane before grouping so the enemy must answer;
- pressure a weakened Guardian/Walker when the purchase adds safe structure
  damage or sustain;
- attack the opposite side only if the team can cross-map without surrendering
  a more valuable objective;
- do not chase kills past the conversion window;
- after winning a fight, name the structure, urn/rift action, boss, or reset
  that spends the advantage.

### 9.5 Troopers, neutrals, breakables, and powerups

Lane troopers are both income and map pressure. Neutral camps let a hero convert
safe time into the next item/level threshold, but farming them can concede lane
priority or an objective window. Breakables and timed powerups add smaller,
repeatable economy opportunities.

The May 22 patch moved medium neutral spawn earlier and changed breakable timing
while also changing shrine vulnerability rules. Community timer summaries can
therefore be stale. The generator should obtain current timers and values from
assets/patch data and use community mechanics references only to explain
concepts. Helpful secondary references include
[neutral camps](https://deadlock.io/en/articles/mechanics/neutral-camps) and
[lanes/troopers](https://deadlock.io/articles/mechanics/lanes-and-troopers).

Tactical prose should distinguish:

- **farm to a named threshold:** clear the closest safe wave/camp and avoid a
  premature fight;
- **farm while preserving priority:** take a camp only after the wave is
  pushed and return before the objective;
- **stop farming and convert:** the item/ability spike is complete and a
  temporary window is open;
- **deny enemy recovery:** invade or take contested neutrals with lane vision
  and an escape route, not as an isolated coin flip.

### 9.6 Urn, Unstable Rift, and comeback economy

The June 30 rules made Unstable Rift timing variable around a seven-minute
interval, with advance visual/global warning. Rift creates a wave-pressure
event rather than direct souls; comeback effects scale with team net-worth
deficit. The Urn begins later, respawns on a schedule, loses pickup value if
left too long, pays the carrier plus released soul orbs, grants permanent
carrier bonuses, and can be dropped through combat events.

This matters for build prose:

- mobility, escort, displacement, and area control can create an Urn window;
- a hero carrying should not use an engage pattern that predictably drops it;
- the team should push lanes before committing to the route;
- a trailing team may use comeback-scaled events to recover rather than force a
  low-probability base fight;
- a fresh active/control spike should be held for the announced contest when
  its cooldown allows.

Exact values belong in the structured evidence packet, not in evergreen prose,
unless the published description is regenerated every patch.

### 9.7 Mid Boss and Rejuvenator

Current generic data gives the Rejuvenator buff a three-minute duration and
includes stronger troopers plus reduced respawn time. In the reference
high-rank cohort, the average first Mid Boss event was around 21:41, but an
average is not a spawn rule.

A Mid Boss call needs:

- lane priority or enough enemy deaths to prevent a collapse;
- damage and sustain to finish before the contest arrives;
- control/vision on entrances;
- a plan for securing the Rejuvenator;
- lanes prepared to exploit the temporary buff afterward.

The item description should not say “take boss” merely because the build deals
damage. It should say what must be true first and how the hero contributes:
zone an entrance, burst the boss, hold a disable for the steal attempt, protect
the securing teammate, or push the lane that converts the buff. See the
secondary [Mid Boss and Rejuvenator overview](https://deadlock.io/en/articles/mechanics/mid-boss-and-rejuvenator),
then verify all live values against assets.

## 10. Detecting power spikes

A useful spike detector combines deterministic game rules with observed match
behavior.

### 10.1 Deterministic spikes

These are mechanically verifiable:

- completing an item or active;
- crossing a category-investment threshold;
- unlocking or upgrading an ability;
- gaining a charge/cooldown/range/duration breakpoint;
- opening an inventory slot;
- completing a two-item or item-plus-ability interaction;
- reaching enough survivability to channel, dive, or hold an area;
- obtaining a mobility/dispel/anti-heal/control answer to a specific opponent.

### 10.2 Observed spikes

These are hypotheses supported by data:

- a high-volume item purchase window with a stable conservative outcome;
- a common item-flow transition;
- a build/ability path that performs above the aligned hero baseline;
- a change in hero economy, damage, or kill participation along a performance
  curve;
- a duration range in which the hero/build closes games more or less often;
- a composition-specific item advantage;
- a raw-match pattern where purchases are quickly followed by objectives,
  fights, or economy acceleration.

### 10.3 A practical spike score

Do not reduce the final prose to a single opaque score, but a ranking score can
prioritize evidence:

```text
spike_score =
    evidence_reliability
  × sample_confidence
  × adoption_weight
  × mechanical_synergy
  × timing_stability
  × actionable_map_window
```

Where:

- `evidence_reliability` penalizes stale/misaligned sources and invalid early
  net-worth samples;
- `sample_confidence` can use Wilson or empirical-Bayes shrinkage;
- `adoption_weight` distinguishes core purchases from rare counters;
- `mechanical_synergy` comes from item/ability properties and investment
  crossings;
- `timing_stability` rewards adjacent-bucket and patch stability;
- `actionable_map_window` is high when a purchase coincides with an objective,
  slot unlock, or enemy vulnerability the hero can exploit.

The model should see the components, not only the aggregate score.

### 10.4 Reinforcement versus compensation

A build can do either:

- **reinforce** a natural strength—more burst on an assassin during its best
  closeout window; or
- **compensate** for a weakness—durability, mobility, control, or cleansing
  after damage is already sufficient.

The common pattern “Tier III damage, Tier IV defense” may mean:

1. Tier III creates the actual kill/pressure breakpoint;
2. later opponents have enough damage/control to punish the same engage;
3. Tier IV protects the hero's bounty, channel, uptime, or escape;
4. the goal changes from finding solo kills to surviving coordinated
   objective fights.

That interpretation is valid only when the Tier IV item properties, purchase
timing, and hero curve support it. A defensive item's raw win rate may be
depressed because it is often purchased from behind. Conversely, a luxury
damage item can look strong because only already-winning players reach it.

## 11. Transferable lessons from League of Legends and Dota

Cross-game research is useful for reasoning patterns, not for importing exact
timers or item names.

### 11.1 Dota: recommendations must update with state

[Dota Plus](https://www.dota2.com/plus) describes real-time item and ability
suggestions based on millions of recent matches, skill bracket, lane, lineup,
and current inventory. Recommendations recalculate when the player deviates.
The transferable lesson is decisive: a build description should not be one
unconditional script.

Deadlock equivalents include:

- rank and patch;
- lane opponent and enemy composition;
- current inventory and category investment;
- whether the team is ahead/even/behind;
- open slots and destroyed Walkers;
- current ability path;
- objective availability and lane pressure.

The four tier paragraphs can describe the default line, but each should include
the one conditional branch most likely to change the hero's job.

### 11.2 Dota: level/talent milestones are real spikes

Dota's official [7.00 gameplay overview](https://www.dota2.com/700/gameplay?l=english)
illustrates the general idea that level/talent milestones create deterministic
power changes and adaptation choices. Deadlock ability unlocks, upgrades, and
shared level/investment bonuses deserve the same weight as item completion.
A description that reads item text but ignores the selected ability order will
miss the reason a build is played differently.

### 11.3 League: a spike matters when it can be converted

Riot's [2026 Season 1 patch notes](https://www.leagueoflegends.com/en-us/news/game-updates/patch-26-1-notes/)
show the broader MOBA pattern: objective rewards can create temporary map
power, lane priority changes the value of those rewards, and some objectives
exist primarily to help end a game. The Deadlock translation is:

```text
purchase/ability spike
→ establish lane priority
→ force or secure a fight/objective
→ convert before the temporary advantage expires
→ reset before the opponent's response
```

“You are strong now” is incomplete. The prose must name the conversion.

### 11.4 League: access timing changes item meaning

Patch examples such as [14.3](https://www.leagueoflegends.com/en-us/news/game-updates/patch-14-3-notes/)
demonstrate that cost, build access, and whether an item supports or replaces a
kit all change its power spike. In Deadlock, price alone is even less complete
because category investment and inventory-slot pressure add additional
breakpoints.

### 11.5 League: mastery is a confounder

Riot's discussion of [balancing new champions](https://www.leagueoflegends.com/en-us/news/dev/dev-balancing-new-champions/)
shows why early observed win rate can differ from learned strength: performance
changes across many games of experience. Deadlock descriptions built from all
players should not assume a difficult hero/path is weak merely because novice
results are low. When mastery controls are unavailable, state that limitation
and prefer high-volume, stable mechanical conclusions.

## 12. Data extraction and reasoning pipeline

### Step 1: Freeze a patch and cohort

Resolve the patch ID/title and boundaries from the patch feed, then select mode,
rank, hero, and minimum volume. Save the exact query and retrieval time. The
same patch title/version can be placed in generated guide metadata so a player
can see which ruleset the description represents.

### Step 2: Fetch current assets

Fetch heroes, items, ranks, generic data, map, NPC units, and relevant misc
entities. Filter disabled/test assets. Retain the full ability and item
properties for reasoning, plus a compact normalized feature set.

### Step 3: Retrieve the exact build

Preserve:

- guide/build ID and revision;
- author/account only where authorized;
- hero and patch;
- item groups in intended display order;
- Tier I–IV membership;
- situational/optional labels;
- ability path and any annotations.

Do not infer purchase order solely from the visual order of a public build
unless the build format guarantees it.

### Step 4: Build the hero baseline

For the exact cohort, fetch hero stats, game stats, player performance curves,
ending-duration buckets, counters/synergies when relevant, and ability-order
statistics. Calculate volume and confidence.

### Step 5: Build per-item evidence

For every build item:

1. fetch item stats by absolute time;
2. fetch by normalized time for retrospective comparison;
3. fetch by net worth, excluding or marking invalid pre-sample purchases;
4. retrieve item-flow nodes/edges;
5. compare outcome to an exposure-aligned hero baseline;
6. calculate exact adoption from raw metadata when practical;
7. detect rebuy/sell/replacement patterns;
8. split core versus situational behavior.

Allow multiple supported purchase windows. A counter item can have a different
window from a core item in the same tier.

### Step 6: Derive mechanical breakpoints

Walk the intended item list and ability path:

- cumulative spend by category;
- crossed investment thresholds;
- active-item availability and cooldown role;
- ability/item interactions;
- inventory pressure and likely sell decisions;
- next resource requirement;
- likely map objectives when the spike occurs.

### Step 7: Build a compact evidence packet

The model needs rich context without an unfiltered dump. A suitable conceptual
contract is:

```json
{
  "schema_version": "deadlock-tactical-build-context/v1",
  "as_of": "2026-07-26T00:00:00Z",
  "cohort": {
    "patch_id": "…",
    "patch_title": "…",
    "patch_start": 1783625258,
    "mode": "normal",
    "min_average_badge": 106,
    "hero_id": 12
  },
  "hero": {
    "name": "…",
    "role_hints": ["…"],
    "abilities": [
      {
        "id": 0,
        "name": "…",
        "mechanics_for_reasoning": "full current asset description",
        "selected_upgrade_steps": [1, 2, 3],
        "breakpoints": ["…"]
      }
    ],
    "baseline": {
      "matches": 0,
      "win_rate": 0.0,
      "duration_curve": []
    }
  },
  "build": {
    "id": "…",
    "ability_order": [],
    "ability_path_evidence": {
      "matches": 0,
      "players": 0,
      "win_rate": 0.0
    },
    "tiers": [
      {
        "tier": 1,
        "items": [
          {
            "item_id": 0,
            "name": "…",
            "category": "weapon|vitality|spirit",
            "cost": 800,
            "is_active": false,
            "mechanics_for_reasoning": "full current item description",
            "purchase_windows": [],
            "adoption": {},
            "outcome": {},
            "investment_thresholds_crossed": [],
            "timing_class": "opening_foundation",
            "confidence": "high|medium|low",
            "source_refs": []
          }
        ]
      }
    ]
  },
  "game_context": {
    "duration_distribution": [],
    "objective_rules": {},
    "likely_objectives_by_window": [],
    "inventory_slot_state": []
  },
  "data_quality": {
    "warnings": [],
    "unknowns": [],
    "forbidden_inferences": []
  }
}
```

The full descriptions remain inside `mechanics_for_reasoning`. They are not
published verbatim.

### Step 8: Generate with Codex

Ask Codex to reason only from the packet and current general mechanics. Require
it to distinguish facts, supported inferences, and unknowns. Reject invented
cooldowns, exact timings, enemy items, or ability behavior.

### Step 9: Validate

Programmatic validation should check:

- exactly four headings, in order: `I`, `II`, `III`, `IV`;
- no `EARLY GAME`, `MIDGAME`, or `LATE GAME` headings;
- every named item/ability exists in the packet;
- no unsupported exact number;
- sufficient match/player volume behind data-backed claims;
- no causal wording for observational outcomes;
- active items receive an actionable use instruction where relevant;
- low-tier late purchases are not mislabeled as opening purchases;
- each paragraph contains an action and a commit/disengage or conversion rule;
- output fits the target build-description length limit.

Human review should ask whether a player can alt-tab, read the four sections,
and immediately know what to do differently.

## 13. Prompt specification for Codex

```text
You are writing the tactical description for one current-patch Deadlock build.
Use only the supplied evidence packet. The item and ability descriptions are
private reasoning context; do not paraphrase them as a catalog.

Return exactly four sections titled:
I
II
III
IV

Treat these as item-price tiers, not fixed clock phases. Infer the usual game
state from the items' observed purchase windows. A low-tier item may be a late
cheap pickup. If evidence shows both opening and late uses, distinguish them in
one concise conditional sentence.

For each section, give concrete instructions:
- positioning and lane/map location;
- pressure, farming, rotation, or gank priority;
- engage pattern and ability/active sequencing;
- preferred targets and teamfight role;
- the power spike or threshold being played around;
- what objective or structure to convert after success;
- when to commit, disengage, reset, or wait for the next completion.

Item names are allowed when they explain WHY the plan changes. Name active
items when the player needs to know when or on whom to use them. Do not list
generic item descriptions, stats, or every purchase.

Account for the selected ability order. Account for whether the build
reinforces the hero's natural timing or compensates for a weakness. Optimize
for the observed common match durations; give only a compact contingency for
rare very-long games.

Use decisive tactical verbs: shove, freeze, rotate, flank, escort, isolate,
peel, zone, invade, burst, channel, reset, disengage, convert. Do not use vague
advice such as "play safe," "be aggressive," or "use abilities wisely" unless
you state the triggering condition and action.

Never claim observational win rate is causal. Do not print win-rate numbers or
sample sizes in the player-facing prose. If evidence is weak or contradictory,
prefer a conditional instruction or omit the claim.

Output only the four sections. Keep each section compact enough to scan during
a match.
```

## 14. Tactical content rubric for each tier

Each paragraph should answer these questions in this order:

1. **Current job:** carry/farm, initiate, roam/gank, peel, split pressure,
   objective damage, area denial, or hybrid.
2. **Position:** with the wave, on a flank, behind the initiator, on high
   ground, at an entrance, or near an ally who enables the combo.
3. **Setup:** which wave/camp/angle/cooldown/target must be prepared?
4. **Sequence:** which ability or active starts, layers, confirms, or ends the
   action?
5. **Target:** isolated carry, clustered backline, diver, structure, boss,
   carrier, or whoever enters the controlled area.
6. **Commit rule:** what facts make the full engage worthwhile?
7. **Disengage/reset rule:** which missing cooldown, enemy response, or failed
   condition means leave?
8. **Conversion:** objective, lane, invade, Urn/Rift, Mid Boss, structure, or
   shop reset.
9. **Next threshold:** what should be farmed or preserved before the next tier?

Not every sentence must explicitly answer all nine, but a section that lacks
job, sequence, commit rule, and conversion is too generic.

### 14.1 Item-name policy

The earlier blanket prohibition on item names is too strict. Use this rule:

- mention a **core item** when its completion changes the tactical pattern;
- mention an **active item** when its timing/target is part of the sequence;
- mention a **counter item** in a conditional branch;
- omit names when several items merely reinforce the same already-explained
  job;
- never turn the summary into a list of descriptions.

Good:

> Use **[active item]** on the first diver, then hold Shelter until the enemy
> commits enough damage that the dome can reset the fight.

Bad:

> [Item] gives Spirit, health, cooldown reduction, and a passive that…

### 14.2 Ahead, even, and behind

The evidence packet should derive one branch per tier:

| State | Default tactical adjustment |
|---|---|
| Ahead | Convert quickly, invade with lane priority, deny recovery, avoid giving a large isolated death |
| Even | Fight on completed thresholds and objective timing; do not force while saving |
| Behind | Clear safely, trade cross-map, use comeback objectives, buy efficient counters, and avoid luxury completion without exposure |

The published paragraph need not repeat all three. Include the branch that
materially changes the build's plan.

## 15. Archetype tests: the prompt must produce different heroes

These are acceptance tests, not permanent hero guides. Always load current
assets because abilities can change.

### 15.1 Kelvin: roaming control and fight stabilization

A good Kelvin result should discuss:

- moving with allies or using mobility to create a numbers advantage;
- layering slows/control instead of dumping every cooldown at once;
- targeting an isolated or retreating enemy for a gank;
- holding Frozen Shelter for a commit, save, objective secure, or fight reset;
- using lane pressure before disappearing for a rotation;
- converting control into an objective rather than chasing.

Representative tone:

> Keep pace with allies, layer repeated control, and reserve Shelter for the
> moment its dome, regeneration, and objective protection can stabilize the
> fight.

If the output tells Kelvin only to “farm and scale,” the prompt or evidence
packet has lost the hero's roaming/control identity.

### 15.2 Abrams: angle-based initiator and sustained brawler

A good Abrams result should differ sharply:

- prepare a wall or terrain angle for the charge;
- force attention and sustain through close range;
- choose whether the ultimate starts the fight or punishes an enemy already
  committed;
- avoid charging beyond allied follow-up;
- pressure structures/areas where the enemy must enter his range;
- use defensive purchases to preserve a second rotation, not to become a
  passive backliner.

### 15.3 Haze: economy, isolation, and execution timing

A good Haze result should:

- name when to take safe waves/camps to reach a real completion;
- move from farming to pick pressure once the completion exists;
- use concealment/angle and control to isolate a high-value target;
- avoid telegraphing or channeling into ready interrupts;
- recognize when grouped enemies or defensive responses make disengagement
  better than a low-value ultimate;
- convert picks before returning to the next farm cycle.

### 15.4 Wraith: ranged pressure and pick conversion

A good Wraith result should resemble Haze only where both seek target access.
It should still reflect Wraith's current asset-defined range, burst/control,
mobility, and ability order rather than copying Haze's farm/channel pattern.
This pair is a useful test for whether the generator recognizes related
archetypes without collapsing them into identical prose.

### 15.5 Curve-compensation tests

Use heroes such as Warden and Lady Geist to test duration reasoning:

- a hero whose ending-duration results fall should receive an earlier closeout
  plan when the build supports it;
- a late defensive/utility tier may compensate for lost relative damage or
  increased enemy coordination;
- the generator must not say the hero “automatically loses late” from a small
  conditional sample;
- the 50+ contingency should be short because very few matches reach it.

## 16. Query cookbook

Use the [interactive API documentation](https://api.deadlock-api.com/docs) to
confirm live parameter names and schemas before execution. The patterns below
describe the required queries; production code should serialize parameters
rather than assemble URLs by hand.

### 16.1 Static context

```text
GET /v1/assets/heroes
GET /v1/assets/items
GET /v1/assets/generic-data
GET /v1/assets/map
GET /v1/assets/npc-units
GET /v1/assets/misc-entities
GET /v1/assets/ranks
GET /v1/patches
```

### 16.2 Hero and game baselines

```text
GET /v1/analytics/hero-stats
  ?hero_ids={hero}
  &game_mode=normal
  &min_average_badge=106
  &min_unix_timestamp={patch_start}

GET /v1/analytics/game-stats
  ?game_mode=normal
  &min_average_badge=106
  &min_unix_timestamp={patch_start}
  &min_duration_s={lower}
  &max_duration_s={upper}

GET /v1/analytics/player-performance-curve
  ?hero_ids={hero}
  &game_mode=normal
  &min_average_badge=106
  &min_unix_timestamp={patch_start}
```

Use non-overlapping duration queries. Verify whether maximum bounds are
inclusive before summing buckets.

### 16.3 Item timing and flow

```text
GET /v1/analytics/item-stats
  ?hero_ids={hero}
  &game_mode=normal
  &min_average_badge=106
  &min_unix_timestamp={patch_start}
  &bucket=game_time_min

GET /v1/analytics/item-stats
  ...same cohort...
  &bucket=game_time_normalized_percentage

GET /v1/analytics/item-stats
  ...same cohort...
  &bucket=net_worth_by_1000

GET /v1/analytics/item-flow-stats
  ?hero_ids={hero}
  &game_mode=normal
  &min_average_badge=106
  &min_unix_timestamp={patch_start}
```

For an opening item, prefer the absolute-time view and raw validation over
net-worth buckets until a valid economy sample exists.

### 16.4 Ability path and combinations

```text
GET /v1/analytics/ability-order-stats
  ?hero_id={hero}
  &game_mode=normal
  &min_average_badge=106
  &min_unix_timestamp={patch_start}

GET /v1/analytics/item-permutation-stats
  ?hero_id={hero}
  ...same cohort...
```

Filter or compare paths by exact prefix only when that is what the endpoint
semantics guarantee.

### 16.5 Raw validation

```text
GET /v1/matches/metadata
  ?hero_ids={hero}
  &min_average_badge=106
  &min_unix_timestamp={patch_start}
  ...bounded duration/item filters...
```

The exact bulk route and limit should be taken from the current docs. Respect
its tighter request quota. Extract no more player identity than the calculation
requires.

## 17. Validation and rejection checklist

### Data contract

- [ ] Patch start/end and retrieval time are present.
- [ ] Mode, hero, and rank cohort match across every comparison.
- [ ] `106` is labeled Ascendant VI+, not Phantom+.
- [ ] Asset IDs resolve to current enabled/shopable records.
- [ ] Purchase counts and distinct buyer counts are not conflated.
- [ ] Rebuys/sells are handled.
- [ ] Pre-180-second net worth is missing/derived, never silently final NW.
- [ ] Duration buckets are non-overlapping.
- [ ] 50+ conclusions disclose the small population.
- [ ] Item outcomes use an aligned hero/exposure baseline.
- [ ] Ability-path and item-flow samples pass volume/player gates.

### Tactical quality

- [ ] Output has exactly I, II, III, IV in that order.
- [ ] Tier is never equated automatically with early/mid/late.
- [ ] Each tier states the hero's current job.
- [ ] Each tier gives positioning or map-location guidance.
- [ ] Ability order affects at least one meaningful instruction.
- [ ] Relevant actives are named with timing and target.
- [ ] Item names explain a change; item descriptions are not dumped.
- [ ] A core spike has a conversion target.
- [ ] A failed engage condition has a reset/disengage instruction.
- [ ] Farming advice names the threshold or map condition it serves.
- [ ] The build's reinforcement/compensation pattern is represented.
- [ ] Very-long-game advice is a contingency, not the default.
- [ ] Different archetypes produce genuinely different instructions.

### Reject the generated result if

- it uses “play aggressive,” “play safe,” or “scale” without a trigger/action;
- it prints raw win rates as proof;
- it invents a cooldown, timer, item property, or matchup;
- it recommends a map objective without lane/contest prerequisites;
- it treats an 800-soul late purchase as early solely because it is Tier I;
- it treats the pre-first-snapshot final-net-worth artifact as real;
- it lists items instead of explaining play;
- it gives every hero the same farm-fight-reset template;
- it overfits a tiny 50+ sample;
- it exposes a private account or player-level narrative.

## 18. Known gaps and future research

1. **Causal item value:** aggregate correlations cannot isolate what would have
   happened had the same player chosen a different item. Propensity/matched
   pre-purchase-state studies could improve this.
2. **Exact adoption rate at scale:** the website's current relative popularity
   is not exact pick rate. A deduplicated hero-player denominator should be
   materialized.
3. **Early economy attribution:** the first-sample gap should be fixed or
   explicitly represented upstream so Tier I net-worth analytics cannot ingest
   final net worth.
4. **Build adherence:** selected-build statistics do not prove the player
   followed the listed items or ability order.
5. **Mastery control:** consistent hero-experience filters are not available in
   every relevant aggregate.
6. **Live-state recommendations:** normalized time uses eventual match duration
   and cannot be known live. A live assistant would need current time, economy,
   structures, inventory, cooldowns, and objective state.
7. **Composition-conditional paths:** sample fragmentation grows rapidly when
   filtering by enemies, lane, items, and rank. Hierarchical shrinkage is more
   appropriate than independent tiny buckets.
8. **Objective attribution:** future raw-event research could measure whether a
   purchase is followed by a structure, Urn/Rift, boss, or fight conversion
   within a defined window.
9. **Patch adaptation:** an item can be mechanically unchanged while the meta
   changes around it. Track both rule changes and rolling behavioral drift.
10. **Steam description limits:** validate the current allowed length,
    formatting, and update behavior before publishing generated prose.

### 18.1 Read-only audit of the current local pipeline

The existing `deadlock-build-sync` project was inspected without editing it.
Several foundations are already strong:

- asset descriptions are cleaned and supplied to a separate Codex process;
- item tiers are arrays of objects with item, category, active flag, timing
  windows, relative popularity, raw outcome, and volume;
- the complete 16-step ability path and current patch metadata are exported;
- narrative artifacts are schema-constrained, hashed, and rejected when stale;
- Steam cache installation is separated from Codex generation and guarded by
  backups/validation.

The research above exposes the following future changes:

| Current local behavior | Why it is insufficient | Required future behavior |
|---|---|---|
| Context labels badge range `[106,116]` as `PHANTOM` | `106` is Ascendant VI | Derive the display name from rank assets: `Ascendant VI+` |
| Context and prompt force I–IV to mean establish/accelerate/pressure/close | Item tier is a price class; cheap purchases can occur late | Infer the state of each item from its purchase distributions and timing class |
| Ability step `index // 4` assigns four upgrades to each “quarter” | Equal path chunks have no demonstrated alignment with item-price tiers or clock time | Export the ordered path and mechanical milestones; align them only through actual level/economy/timing evidence |
| A power spike must combine an item with the ability assigned to the same quarter | The imposed quarter can fabricate a relationship | Detect mechanical synergy and temporal overlap independently; allow no declared spike when evidence is inadequate |
| Schema requires at least one power spike | Ordinary growth can be forced into a “spike” label | Allow zero, one, or at most two meaningful spikes |
| Ability-path `pick_rate` divides by matches across retained complete paths | It is conditional on qualifying complete paths, not all hero appearances | Label it “share of qualifying complete paths,” or calculate an all-hero-game denominator |
| Item `relative_pick_rate` is used as popularity | It is relative to the top item, not adoption | Keep the internal name, label it “relative popularity,” and add exact distinct-buyer adoption |
| Prompt requires a named top-three item and promotes leading actives | It can force an item mention even when the tactical connection is weak or situational | Mention a name only when mechanics and supported timing change the instruction; keep active instructions when genuinely core |
| Duration is collapsed into EARLY/MID/LATE phase labels | Useful internally, but it can leak the rejected phase framing into tier prose | Retain duration as outcome-conditioned context while keeping player headings strictly I–IV |
| Export lacks category-purchase bonuses and cumulative investment crossings | It misses deterministic power changes | Add category spend before/after, per-purchase bonus, thresholds crossed, and incremental shared bonus |
| Export lacks item-flow reach, exact adoption, raw rebuy/sell, objective state, and the early-net-worth warning | The model cannot distinguish core, counter, replacement, or invalid timing evidence robustly | Add the evidence-packet fields and quality flags defined in Section 12 |

The desired implementation should preserve the existing safety boundary,
schema validation, patch fingerprinting, and separate Codex stage while
replacing the artificial quarter-to-time/ability alignment.

## 19. Recommended final architecture

```text
Patch feed + current assets
            │
            ├── hero/ability mechanics
            ├── item mechanics + investment thresholds
            └── map/objective/economy rules
            │
Exact build ├── tier groups
            └── ability order
            │
Analytics   ├── hero and game baselines
            ├── duration distribution/curves
            ├── item timing/flow/combinations
            └── counters/synergies when supported
            │
Raw matches ├── exact adoption/order/rebuy/sell
            └── validation and pre-purchase state
            │
            ▼
Patch-bound evidence packet
            │
            ▼
Codex tactical synthesis
            │
            ▼
Schema/statistical/factual checks
            │
            ▼
I / II / III / IV player-facing description
```

The key boundary is between **evidence assembly** and **language synthesis**.
Deterministic extraction decides what the game data says. Codex decides how to
express those facts as concise tactical instructions. Codex should never be
asked to infer the API data from item names alone.

## 20. Source index

### Primary Deadlock/API sources

- [Deadlock API interactive documentation](https://api.deadlock-api.com/docs)
- [Deadlock API repository](https://github.com/deadlock-api/deadlock-api)
- [Deadlock API hero assets](https://api.deadlock-api.com/v1/assets/heroes)
- [Deadlock API item assets](https://api.deadlock-api.com/v1/assets/items)
- [Deadlock API generic data](https://api.deadlock-api.com/v1/assets/generic-data)
- [Deadlock API map data](https://api.deadlock-api.com/v1/assets/map)
- [Deadlock API rank data](https://api.deadlock-api.com/v1/assets/ranks)
- [Website Item Stats table implementation](https://github.com/sxndmxn/deadlock-api/blob/e7bd075b558548745fdf9700cee425572264963f/website/src/components/items-page/ItemStatsTable.tsx)
- [Website Purchase Analysis chart implementation](https://github.com/sxndmxn/deadlock-api/blob/e7bd075b558548745fdf9700cee425572264963f/website/src/components/items-page/ItemBuyTimingChart.tsx)
- [Tiered Purchase Guide UI](https://github.com/sxndmxn/deadlock-api/blob/e7bd075b558548745fdf9700cee425572264963f/website/src/components/purchase-guide/PurchaseGuide.tsx)
- [Purchase-window algorithm](https://github.com/sxndmxn/deadlock-api/blob/e7bd075b558548745fdf9700cee425572264963f/website/src/lib/purchase-guide.ts)
- [June 30, 2026 Deadlock patch](https://steamcommunity.com/games/1422450/announcements/detail/688635449342692004)
- [May 22, 2026 Deadlock patch](https://steamcommunity.com/games/1422450/announcements/detail/670617878982034053)

### Secondary Deadlock mechanics references

- [Shop tiers and investments](https://deadlock.io/en/articles/mechanics/shop-tiers-and-investments)
- [Neutral camps](https://deadlock.io/en/articles/mechanics/neutral-camps)
- [Mid Boss and Rejuvenator](https://deadlock.io/en/articles/mechanics/mid-boss-and-rejuvenator)
- [Patron](https://deadlock.io/en/articles/mechanics/patron)
- [Lanes and troopers](https://deadlock.io/articles/mechanics/lanes-and-troopers)

### Cross-MOBA primary sources

- [Dota Plus real-time item and ability suggestions](https://www.dota2.com/plus)
- [Dota 7.00 gameplay and level/talent milestones](https://www.dota2.com/700/gameplay?l=english)
- [League of Legends 2026 Season 1 patch notes](https://www.leagueoflegends.com/en-us/news/game-updates/patch-26-1-notes/)
- [League of Legends Patch 14.3](https://www.leagueoflegends.com/en-us/news/game-updates/patch-14-3-notes/)
- [Riot on balancing new champions and mastery curves](https://www.leagueoflegends.com/en-us/news/dev/dev-balancing-new-champions/)

## 21. Public API route-family inventory

This inventory prevents the strategy pipeline from mistaking “the endpoints
used today” for “everything the API can expose.” It reflects the current
repository route modules. The interactive OpenAPI document remains
authoritative for methods, complete schemas, authentication, and live limits.

### 21.1 Analytics routes

All are nested under `/v1/analytics`; scoreboards are nested one level further.

| Route | Primary unit/use |
|---|---|
| `/ability-order-stats` | Ordered ability upgrades and outcomes |
| `/badge-distribution` | Rank/badge population |
| `/build-item-stats` | Item occurrence in published builds |
| `/game-stats` | Match-level duration, combat, economy, level, and objective aggregates |
| `/hero-ban-stats` | Draft/ban behavior |
| `/hero-build-stats/{hero_id}` | Initially selected database build |
| `/hero-comb-stats` | Multi-hero lineup combinations |
| `/hero-counter-stats` | Enemy matchup outcomes |
| `/hero-stats` | Hero performance baseline |
| `/hero-synergy-stats` | Ally-pair outcomes |
| `/item-flow-stats` | Stage-based item nodes and transitions |
| `/item-permutation-stats` | Unordered item combinations |
| `/item-stats` | Per-purchase item outcome/timing aggregates |
| `/kill-death-stats` | Kill/death-event analysis |
| `/player-performance-curve` | Absolute/normalized progression curves |
| `/player-stats/metrics` | Available player-stat metric definitions/aggregates |
| `/scoreboards/heroes` | Hero scoreboard |
| `/scoreboards/players` | Player scoreboard |

The current analytics router enforces 200 requests/minute per IP, 400/minute
per API key, and 2,000/minute globally before any tighter endpoint-specific
limit. Treat those as current implementation details and still honor response
headers.

### 21.2 Asset routes

All are under `/v1/assets`:

```text
/accolades
/build-tags
/client-versions
/colors
/generic-data
/heroes
/items
/loot-tables
/map
/misc-entities
/npc-units
/ranks
/steam-info
/images
/icons
/sounds
/fonts
```

Several collections also support an ID/name lookup. Items additionally expose
lookups by item type, hero ID, and slot type; heroes support ID/name lookup;
ranks support tier lookup. The media indexes are presentation resources, not
strategy evidence.

### 21.3 Match routes

The `/v1/matches` family includes:

```text
/active and /active/raw
/metadata                         (bulk filtered metadata)
/{match_id}/metadata
/{match_id}/metadata/raw
/{match_id}/salts
/salts                            (ingest)
/{match_id}/live/url
/live/urls                        (read/ingest)
/recently-fetched
/to-fetch
```

`/v1/matches/demo` provides schema discovery, asynchronous query submission and
status, plus live demo queries. `/v1/matches/custom` provides the create,
ready/unready, start, leave, and match-ID lifecycle for custom lobbies.

Demo/query/custom routes are operationally powerful but unnecessary for the
first description generator. Add them only when aggregate and metadata evidence
cannot answer a clearly defined question.

### 21.4 Player routes

The `/v1/players` family includes:

```text
/{account_id}/account-stats
/{account_id}/card
/{account_id}/enemy-stats
/{account_id}/mate-stats
/{account_id}/match-history
/{account_id}/mmr-history
/{account_id}/mmr-history/{hero_id}
/{account_id}/rank-predict
/{account_id}/rank-predict/image
/hero-stats
/mmr
/mmr/{hero_id}
/mmr/distribution
/mmr/distribution/{hero_id}
/rank-predict/image
/steam
/steam-search
```

Some routes are gated or protected. Personalized description generation should
use account data only after explicit account authorization and should not
publish player-level evidence in a public guide.

### 21.5 Remaining route families

| Prefix | Surface |
|---|---|
| `/v1/builds` | Search/retrieve public database builds with filters |
| `/v1/leaderboard` | Regional and hero-specific normalized/raw leaderboards |
| `/v1/patches` | Patch feed and major-patch days |
| `/v2/patches` | Newer patch-feed version |
| `/v1/graphql` | GraphQL asset/analytic projection |
| `/v1/sql` | Query plus table/schema discovery |
| `/v1/commands` | Variables, command resolution, and widget versions |
| `/v1/info` | API information and health |
| `/v1/servers` | Lists, Steam list, status, and metrics |
| `/v1/auth` | Patreon login/callback/logout/webhook flow |
| `/v1/patron` | Patron status/account association |
| data-privacy handlers | Verified account protection/unprotection |

The build route is a retrieval/search surface; it should not be confused with
an official Valve endpoint for publishing a guide to a player's account.
Publishing still requires an authorized game-client/account workflow. The
description generator can produce the text independently, then hand it to that
separate publishing boundary.

## 22. Final recommendation

Build the descriptions from a patch-bound evidence packet, not from item names
or raw win rate alone. Sort items by exact adoption when available (otherwise
label the current matches-based value as relative popularity), retain each
item's supported purchase windows, and combine those windows with the hero's
ability path, investment thresholds, duration curve, inventory constraints,
and the map objectives likely to be available.

Then let Codex write four compact tactical sections. The ideal result reads
like a coach:

- what to pressure now;
- what ability or active starts the play;
- which target or area matters;
- what completion makes the commit worthwhile;
- what to take after success;
- and exactly when to leave.

That framework accommodates a late Tier I purchase, a damage-heavy Tier III
spike, a compensating defensive Tier IV, a gank-heavy Kelvin, a close-range
Abrams, and a farm-to-execution Haze without forcing any of them into the same
generic “early/mid/late” script.
