# Deadlock build usage and design audit

Date: 2026-08-13

Repository: deadlock-build-sync at 7464dd8d94192d75a40ad8d14cd7528e0e2e634e

Live client context: 2560×1440, August 12 client update; inspected managed builds were generated from the July 30 matchmaking epoch

Decision: preserve the exact five-section structure CORE ITEMS, TIER 1, TIER 2, TIER 3, TIER 4.

## Implementation verification — 2026-08-14

All five linked phase briefs are implemented on pull request #3. Fresh schema-2 build
evidence freezes the August 12 minor update through August 14 for ranked Normal,
badges 71–115, client 6677: 7,007 matches, 83,027 eligible player appearances, 38
heroes, and zero exclusions. Unsupported situational comparisons remain explicit
abstentions; no counter cards were admitted.

Narrative schema 6 / prompt 22 rejects incomplete or corrupted roles. The authorized
live run updated all 38 managed guides, created none, validated a temporary cache,
backed up the original, and replaced it atomically. The backup and installed cache
both retain 65 unpublished entries and the same out-of-scope fingerprint. Post-install
status reports every artifact stage and the installed cache current. The full local
gate passes 288 tests and pull-request CI/CodeQL are green. A representative fresh
client visual recheck remains pending only while the Hyprland session is locked.

## Executive verdict

The five-section layout is good and should remain. It is calmer and more legible than most public builds, its Queue semantics are now correct, and it works across weapon, spirit, melee, tank, and hybrid heroes. The repository behind it is unusually strong at evidence identity, legality, failure handling, and safe Steam mutation.

The main problem is not the layout. It is that the best information already produced by the pipeline does not reach the player:

- the installed state narrative artifact contains a tactical profile, eight ordered core-item explanations, and five category summaries for every one of 38 heroes;
- installation uses the build summary but drops the tactical profile and all eight action explanations;
- all five generated category summaries are replaced with generic fixed sentences;
- item hovers therefore lead with purchase window, raw adopter win rate, and pick rate instead of the hero-specific reason to buy the item;
- the three build-tag slots render as unknown badges because the encoder emits no field 11 tags;
- the title repeats author, hero, and patch but omits the archetype the player is choosing;
- 297 of 1,520 optional tier slots, or 19.54%, repeat an item already present in CORE.

The first release should therefore be an information-routing release, not an algorithm rewrite:

1. Correct the stale ability-path wording.
2. Put the generated core-item instructions into the item hovers.
3. Put role and Queue instructions at the top of the build description.
4. Encode three validated build tags.
5. Remove CORE duplicates from optional tier menus, or explicitly relabel them if duplication is retained.

Only after those changes should the project attempt state-reactive or counter-specific recommendation. The present data supports an observational default and a popularity-based option menu. It does not support causal “best item,” matchup-counter, or universal-path claims.

## Scope, methods, and limits

No build was made active, copied, favorited, queued, edited, installed, or published during this audit. Public entries were opened only in the browser preview. No Steam cache mutation or live sync was run. The only intended repository change is this report.

The evidence came from four complementary passes:

1. **Live client inspection.** I opened the build browser with B and inspected My Builds and public previews for McGinnis, Mina, Abrams, and Mirage. These represent a hybrid summon hero, a newer spirit hero, a melee/tank hero, and a weapon/spirit flex hero. I inspected titles, tags, descriptions, category geometry, item hovers, optional rows, and ability orders.
2. **Current stratified public-build sample.** On 2026-08-13, I queried the current [Deadlock API build search](https://api.deadlock-api.com/docs) for the ten most weekly-favorited, English, latest-version builds updated after the July 30 epoch for each of the 38 active heroes. This produced 380 builds. The sample is balanced by hero and is used to study authoring and UI conventions, not to declare any build tactically correct.
3. **Cross-MOBA research.** I compared official Dota and League recommendation principles and relevant sequential/contextual recommendation research.
4. **Repository audit.** I traced the current build-evidence selector, ability selector, mechanics and policy validators, narrative generation/admission, Steam projection, protobuf fields, cache transaction, tests, CI, and current state artifacts.

The live service changes quickly. Numeric findings below describe the frozen audit sample, not permanent game facts. During final verification, the API patch feed reported an August 12 minor update and latest available client assets at version 6677, while the inspected managed artifacts were pinned to client 6673 with an August 9 as-of cutoff and the July 30 matchmaking patch. The installed builds were therefore stale at audit time. The zero-argument sync path fetches the newest patch and should reject the old build evidence before installation; fresh offline build evidence is required rather than silently stretching the old cohort across the new patch. Public-guide popularity is also affected by prior exposure, creator audiences, jokes, stale guides, and promotional traffic. It is useful UX evidence and weak strategic evidence.

## Evidence snapshot

### Live client observations

The managed build rendered consistently on all four inspected heroes:

- CORE ITEMS occupied the upper-left panel and was the only automatic path.
- TIER 1 occupied the upper-right panel.
- TIER 2 and TIER 3 formed the middle row.
- TIER 4 used the full-width bottom row.
- CORE displayed eight cards in a 6+2 flow.
- TIER 1–3 displayed ten cards in 5+5 flows.
- TIER 4 displayed ten cards in one horizontal row.
- Tier rows were marked optional, which is essential because optional rows are excluded from the default Queue.
- Item hovers displayed the normal item mechanics plus three added lines: purchase window, win rate, and pick rate.
- Managed previews showed three unresolved tag badges.
- The full ability order was present and easy to scan.

The public examples showed the strengths and weaknesses of community authoring:

- McGinnis had clear archetype titles such as turret, gun, and ultimate variants, often with version markers and audience tags. The best description immediately stated the role and how to play it. Other descriptions were promotions, jokes, or retirement messages.
- Mina’s public list was much sparser and included several explicitly outdated entries. This is where an automatically refreshed, support-gated private build has the clearest value.
- Abrams had a small set of simple default/beginner/melee builds. Some descriptions were actionable; others amounted to “stats do not lie.”
- Mirage showed distinct gun and spirit identities. Titles and tags made those variants discoverable even when descriptions were extremely short.

The browser preview consistently elevated five surfaces: title, three tags, a representative item strip, description, and full ability order. Those are the surfaces the managed build should optimize first.

### Stratified community-build measurements

The 380-build current sample contained:

| Measure | Result |
|---|---:|
| Active heroes represented | 38 of 38 |
| Builds per hero | 10 |
| Categories | 2,675 |
| Categories explicitly optional | 1,359 (50.8%) |
| Categories with a description | 1,044 (39.0%) |
| Item entries | 16,078 |
| Item entries with an annotation | 6,171 (38.4%) |
| Item entries with positive sell priority | 157 (1.0%) |
| Item entries with an imbue target | 791 (4.9%) |
| Builds with at least one optional category | 328 (86.3%) |
| Builds with at least one item annotation | 271 (71.3%) |
| Builds with at least one category description | 277 (72.9%) |
| Builds with a complete 16-change ability order | 286 (75.3%) |
| Median categories per build | 7 (range 2–42) |
| Median item entries per build | 42 (range 18–103) |
| Median description length | 84 characters |
| Descriptions containing a URL/promo marker | 86 (22.6%) |
| Titles containing a win-rate-style claim | 34 (8.9%) |

This supports a restrained conclusion: players use builds as more than shopping lists. They use optional groups, annotations, ability orders, archetype titles, and imbue hints. It does **not** support copying the largest public guides. A 42-category or 103-item build is difficult to search under match pressure.

The balanced sampling matters. A single global 500-result popularity query returned only two hero IDs in this audit. Global public-build samples can be dominated by a small number of heroes or authors; per-hero sampling is the safer way to study build structure.

# HOW BUILDS ARE USED

## 1. As an automatic shopping path

The simplest use is Queue/Quickbuy: the player expects the non-optional cards to be purchased left to right. Current community discussions repeatedly describe builds this way, especially for new players. They also warn that optional rows must not silently enter that queue. Valve’s build schema makes this executable: optional categories are excluded from the default Queue.

The current managed build gets this right. CORE ITEMS is non-optional and TIER 1–4 are optional. This is a major improvement over prose-only “situational” advice because the machine-readable behavior agrees with the label.

The automatic path still needs to be understood as a default, not a rail. Lane pressure, early deaths, enemy healing, active-item burden, component ownership, flex unlocks, and the player’s execution comfort can justify deviation.

## 2. As an in-shop decision aid

Experienced players do not merely queue every card. They open B, compare items, hover mechanics, and buy directly. For this use, the build is a compact reference surface:

- CORE answers “what is the default coherent progression?”
- TIER 1–4 answer “what else in this price tier is common or mechanically relevant?”
- annotations answer “why, when, instead of what, and how do I use it?”

This is why tooltip quality matters more than adding more categories. A player usually has seconds, not minutes, to interpret the build.

## 3. As a learning guide

Newer players use annotated builds between waves, while dead, or before a match. They need:

- the hero’s job;
- the default buy order;
- what can be skipped;
- which options answer sustain, healing, control, or damage pressure;
- how active items and imbues are used;
- the ability order and its main breakpoint.

The best live public examples supplied this information directly. The weakest examples assumed the player already understood the author’s shorthand.

## 4. As a build browser and identity system

The browser is a discovery UI. Public authors encode identity in:

- **title:** gun, spirit, melee, turret, support, ultimate, hybrid, beginner, or advanced;
- **tags:** damage axis, function, signature ability/item, and intended audience;
- **description:** a one- or two-sentence tactical thesis;
- **version/update marker:** a freshness signal.

The managed title currently communicates authorship and patch freshness but not variant identity. The blank tags waste an especially valuable discovery surface.

## 5. As an ability-order guide

Three quarters of the stratified public sample included a full 16-change ability order. This is not decorative. Players use it to:

- know the first unlock;
- identify the first maximized ability;
- see when the ultimate enters the plan;
- recover after saving or spending multiple ability points;
- understand which part of the kit the item build is intended to support.

The managed build’s native ability order is a strong feature. Its evidence label needs to be more accurate and more useful.

## 6. As a patch/freshness filter

Deadlock changes too quickly for an unlabeled guide to remain trustworthy. Mina’s sparse/outdated public list demonstrated the problem directly. The managed build’s exact patch, client, queue, rank cohort, as-of timestamp, snapshot, and policy identities are valuable. They should remain available, but they should not occupy the first screenful of player-facing prose.

## 7. What other MOBAs teach

[Dota 2 Hero Builds](https://www.dota2.com/workshop/builds/overview?l=english) treats a guide as item ordering, ability ordering, and author-written tactical tooltips available inside the match. [Dota Plus Assistant](https://www.dota2.com/plus) goes further: it uses recent skill-bracket data, current purchases, and lineups; offers several sequences; and recalculates after deviation. The transferable principle is to recommend the next legal action from current state, not merely publish one immutable global ranking.

[League’s shop redesign](https://www.leagueoflegends.com/en-us/news/dev/preseason-item-shop-update/) emphasizes a small set of understandable recommendations with visible reasons such as enemy healing or defenses, while leaving the player in control. Riot’s [item-balancing discussion](https://www.leagueoflegends.com/en-gb/news/dev/dev-updated-approach-to-item-balancing/) also explains why aggregate item win rate is distorted by purchase timing, champion selection, and access to expensive slots.

The research agrees on the sequence/context point:

- [Sequential Item Recommendation in the MOBA Game Dota 2](https://arxiv.org/abs/2201.08724) found order-aware models substantially better than popularity at imitating the next observed purchase. It did not establish that the imitated purchase was optimal.
- [Interpretable Contextual Team-aware Item Recommendation](https://arxiv.org/abs/2007.15236) supports incorporating hero, role, and team context and giving interpretable reasons. Its winner-only training population is an important selection limitation.

The product lesson is not “copy Dota or League.” It is: preserve a simple default, make alternatives explainable, adapt after deviation when state is available, and never present popularity or adopter outcomes as causal item strength.

# WHAT WE CAN FIX

## Confirmed P0: the installed roster is behind the live patch

The managed builds inspected in the client were generated from:

- client 6673;
- data through 2026-08-09;
- the July 30 Matchmaking Update.

At final verification on 2026-08-13, the [patch feed](https://api.deadlock-api.com/v2/patches) listed an August 12 minor update and the [client-version endpoint](https://api.deadlock-api.com/v1/assets/client-versions) listed 6677 as the latest available asset version.

The safety behavior is correct: cli.py configures collection from the frozen build-evidence identity, while api.py still fetches the newest patch; service.py compares that current patch identity against the build evidence and rejects a mismatch. It does not weaken the validator or silently reinterpret July 30 evidence as August 12 evidence.

The operational gap is upstream of installation: zero-argument sync cannot refresh until the offline player-match pipeline produces a new, full-roster build-evidence artifact for the new patch/client. Make that state unmistakable:

- add a read-only status/preflight command that compares installed artifact, latest patch, and latest asset client;
- show “STALE — regeneration required” before any model call or Steam operation;
- report which stage is stale: build evidence, policy/context, narrative, or installed cache;
- document and automate the offline build-evidence refresh handoff;
- never fall back to a longer cross-patch window merely to restore coverage.

This finding increases, rather than reduces, confidence in the existing fail-closed boundary. The fix is faster visibility and artifact production, not a weaker compatibility check.

## Confirmed P0: the ability-path description is stale

The installed description says:

> Ability-path pick rate compares reliable complete 16-step paths (20+ matches).

That no longer describes the selector in [ability_order.py](../src/deadlock_build_sync/ability_order.py). The current algorithm accepts observed prefixes of length 1–16 and constructs a path one legal state at a time from all rows that reached that state. It does not choose the most popular exact complete path.

The algorithm is the stronger part; the copy is wrong. Rename “pick rate” to “final-branch support share” everywhere and describe the result as a “state-composed observed default.” Do not imply that the final 16-step sequence was itself observed.

Recommended first-step annotation:

> State-composed default • tail support n=2,571 • observational.

The adopter outcome rate is not useful enough to deserve the only ability annotation slot.

## Confirmed P0: validated tactical prose is discarded

The installed state narrative artifact is internally compatible with its frozen July 30 snapshot: schema 4, prompt 19, and complete for all 38 active heroes. It is not current for the August 12 live patch. Each hero entry has:

- a primary role;
- fight-role and economy instructions;
- one build summary;
- eight core action explanations;
- five category summaries.

[narratives.py](../src/deadlock_build_sync/narratives.py) validates those fields but applies only the build summary. Core action explanations are never mapped back to GuideItem.tactical_annotation. The category summaries are admitted and then replaced by standard_category_description for every standard section.

This is the largest return-on-effort opportunity in the project. Of the 304 generated core-item instructions, 302 already fit within the renderer’s 240-byte annotation ceiling. The pipeline has done the difficult work; the projection drops it.

Recommended behavior:

- map core-1 through core-8 to the exact corresponding CORE item;
- require the item name, node ID, evidence reference, and order to remain unchanged;
- normalize each instruction to a smaller budget, ideally 150–170 bytes;
- append a deterministic timing/adoption line only if the combined result stays within 240 bytes;
- fail closed on a mismatched node or item;
- keep the analytics-only annotation as a fallback when narratives are intentionally disabled.

Suggested two-line hover:

> Third: apply the supplied anti-heal mechanic after establishing reliable hits.
>
> Usually 12k–18k net worth • adopted in 58.9% of eligible appearances.

The exact wording must remain mechanics-grounded. The example illustrates hierarchy, not a universal claim.

## Confirmed P0: the player-facing description is backwards

[protobuf.py](../src/deadlock_build_sync/protobuf.py) places marker, generator provenance, patch, client, matchmaking mode, ranks, snapshot hash, policy hash, and a statistical disclaimer before the hero-specific summary. The live preview therefore reads like an audit manifest before it reads like a guide.

Keep every identity because the cache validator and reproducibility model depend on it. Reorder, do not delete:

1. hero role/archetype;
2. how to use CORE and tiers;
3. one economy/fight instruction;
4. short freshness/cohort line;
5. managed marker and full snapshot/policy provenance.

Recommended shape:

~~~text
Mobile damage-over-time pressure; maintain contact and convert clean picks.
AUTO: CORE left→right. TIER 1–4 are optional and never auto-queued.
Ranked • Emissary I–Eternus V • data through 2026-08-09 • client 6673.

[managed marker]
Snapshot: …
Policy: …
Claim limit: observational; no causal item effect.
~~~

The rich sidecar remains the authoritative audit record. The build preview should be the authoritative player instruction.

## Confirmed P1: build tags are absent

The live managed previews rendered three unknown tag badges. Deadlock currently exposes a 14-tag taxonomy through the [build-tags endpoint](https://api.deadlock-api.com/v1/assets/build-tags), including Weapon, Spirit, Vitality, Damage, Utility, Healing, Crowd Control, Mobility, Melee, Headshots, Debuff, and three complexity levels.

The current CMsgHeroBuild contract stores repeated tags in protobuf field 11. The adjacent [deadlock-api source](https://github.com/deadlock-api/deadlock-api) decodes and re-encodes that exact field. This project emits fields 7–10 and 12 but no field 11.

Add exactly three pinned, validated generic tags:

1. **primary axis:** Weapon, Spirit, or Vitality;
2. **functional identity:** Damage, Utility, Healing, Crowd Control, Mobility, Melee, Headshots, or Debuff;
3. **audience:** New, Intermediate, or Advanced.

Selection must be deterministic and mechanics-grounded. A conservative first version can derive the primary axis from CORE investment, derive function only from explicit hero/item mechanics, and default to Intermediate until a reviewed complexity rule exists. Every ID must belong to the build-tag catalog for the pinned client version. Never emit zero as a placeholder.

## Confirmed P1: optional menus repeat CORE

The current 38-hero artifact contains 1,520 tier slots. Of these, 297 repeat an item already shown in CORE: 19.54% of all optional-menu space. Thirty-two of 38 heroes repeat all eight CORE items in the tier rows.

This follows directly from the algorithm:

- CORE is selected from supported final inventories.
- Each tier independently takes the ten most adopted items.
- Tier membership does not exclude CORE.

The repetition may help a player find an item by catalog tier, but the row description calls these cards “optional choices.” A mandatory/default CORE item is not a distinct optional choice merely because it also has a tier.

Recommended default:

- exclude CORE IDs before selecting tier alternatives;
- take the next adequately supported non-CORE item;
- keep at most ten items per tier;
- permit fewer than ten rather than filling with weak evidence;
- if duplicate display is intentionally retained, change the tier copy from “optional choices” to “price-tier reference, including CORE” so the semantics are truthful.

The preferred option is disjoint menus because it recovers nearly one-fifth of the option space without adding a section.

## Confirmed P1: raw adopter win rate consumes the hover

The code correctly does not use item outcome rate to select CORE, select tier membership, or order either. The UI nevertheless gives raw win rate one of three prominent annotation lines.

This creates a hierarchy conflict:

- the player needs “why/when/how”;
- the displayed number estimates outcomes among players who managed to own the item;
- expensive and late items are disproportionately accessible in already-advantaged or long games;
- counter items can have low raw outcomes precisely because they are bought in difficult states;
- no comparison against a legal, similarly accessible alternative is shown.

Keep adopter outcome in the sidecar and preview JSON. In the live hover, prioritize:

1. mechanics-grounded use;
2. observed purchase window;
3. adoption with its eligible denominator or support class.

If win rate remains, label it “adopter outcome” and place it after support, never simply “Win rate.”

## Confirmed P1: the title answers the wrong question

Current grammar:

> persona | hero | patch title

The browser already knows the hero and author. The player’s unanswered question is “which way am I building this hero?” Public authors routinely answer that with gun, spirit, melee, turret, support, ultimate, hybrid, beginner, or advanced.

Recommended grammar, still under the current 50-character cap:

> archetype | queue | epoch date

Examples:

- Burn / Dash | Ranked | 2026-07-30
- Turrets / Utility | Ranked | 2026-07-30
- Melee Sustain | Ranked | 2026-07-30
- Evidence Default | Ranked | 2026-07-30

Use the fallback unless the archetype is deterministically supported. Avoid “best,” “optimal,” “highest WR,” and confidence claims the artifact cannot prove. Put the exact patch title and client in the description, where truncation is less destructive.

## P1 acceptance question: do queued upgrades expand components correctly?

The current CORE represents final owned items reconstructed from match telemetry. Consumed components are not necessarily visible as separate CORE cards. Across 38 heroes:

- the first CORE item’s listed cost had a median of 1,600 souls;
- its median observed first-ownership point was 3.3k net worth;
- most complete CORE paths were dominated by Tier 2–4 final items.

This is not enough to declare a defect. The client may correctly expand upgrade components when the parent is queued. It is enough to require a live acceptance test:

- queue a parent upgrade from CORE;
- verify that Quickbuy offers the intended component/incremental cost;
- verify behavior when a branching component is already owned;
- verify recovery after manually buying a different child;
- verify no stall occurs at an imbue prompt;
- verify the next CORE item remains sensible after component consumption.

Until that test passes on the pinned client, describe CORE as an observed final-item path, not a complete lane shopping script.

Resolution recorded 2026-08-15: live review showed required components such as Extra
Health for Fortitude and High-Velocity Rounds for Express Shot in Paradox's optional
Tier 1 row rather than the automatic CORE path. The frozen full-roster audit found the
same projection defect in all 38 heroes. The implementation now renders the existing
component-expanded evidence path as CORE and excludes all of its item IDs from optional
menus while retaining the eight-item set as final-inventory analytics.

## P2: tier rows lack actual situational evidence

The tier rows are high-adoption price-tier menus. The policy explicitly abstains from claiming that adoption identifies a counter trigger. This is statistically honest.

The UI can still be clearer. Today “optional choices” invites the player to ask which choice applies, but the artifact usually cannot answer. Near-term annotations should classify only explicit mechanics—anti-heal, spirit defense, bullet defense, mobility, ally protection, active burden—and avoid asserting matchup benefit.

True “buy this when X” guidance requires a decision-state comparison:

- current enemy threat;
- current inventory/components and active slots;
- liquid currency and shop opportunity;
- next objective/fight deadline;
- legal alternatives including save;
- enough overlap and support to compare the alternatives.

Do not use generic hero-counter rates to bridge this gap.

# WHAT WE CAN KEEP

## Keep the five exact section names

These names are simple, stable, and already understood:

- CORE ITEMS
- TIER 1
- TIER 2
- TIER 3
- TIER 4

Do not rename tiers to early/mid/late. They are price tiers, and the evidence shows purchases within a tier can occur across widely different net-worth and clock windows.

## Keep the current geometry

The current dimensions in [protobuf.py](../src/deadlock_build_sync/protobuf.py) were captured from a user-tuned 2560×1440 Viscous build:

| Section | Width | Height | Observed flow |
|---|---:|---:|---|
| CORE ITEMS | 567.0 | 307.5 | 6+2 |
| TIER 1 | 465.75 | 318.75 | 5+5 |
| TIER 2 | 562.5 | 315.75 | 5+5 |
| TIER 3 | 465.75 | 319.5 | 5+5 |
| TIER 4 | 1039.5 | 152.25 | 10×1 |

The geometry worked consistently across all four live heroes. Do not spend the first implementation cycle on pixel tuning. Revisit it only after screenshot testing at other aspect ratios and UI scales.

## Keep CORE as the only automatic row

This is the most important executable invariant. Optional prose cannot repair an accidentally queued item. Preserve:

- exactly one non-optional row;
- left-to-right order;
- every tier row optional;
- no alternative entering Queue by default;
- protobuf round-trip tests for the optional field.

## Keep outcome-agnostic selection

The current selectors use support/adoption and observed timing, not raw win rate, to choose and order items. Adopter outcome is descriptive metadata only. Keep that separation.

## Keep coherent joint CORE selection

Selecting one supported eight-item final inventory is better than independently taking eight popular items that may never coexist. The current selector also rejects:

- cost above median final net worth;
- component conflicts that do not leave the selected final set;
- duplicate/unique-limit violations;
- more than four active items;
- paths that cannot fit in the validated inventory.

Keep this as the conservative baseline even if a sequential policy is added later.

## Keep left-to-right observed timing

CORE is ordered by median observed acquisition time. Tier membership is selected by adoption, then displayed by observed first-ownership net worth and time. That makes row order meaningful without claiming causation.

The wording should say “observed order” or “usually earlier to later,” not “optimal order.”

## Keep strict artifact identity and fail-closed admission

The inspected state artifacts cover all 38 active heroes and consistently use:

- patch identity;
- client 6673;
- ranked normal mode;
- Emissary I–Eternus V;
- immutable as-of time;
- separate mechanics, matchmaking, objectives, and telemetry epochs;
- exact item, hero, rank-label, context, policy, narrative-basis, prompt, and model identities.

Within a compatible current build-evidence snapshot, stale or incomplete narratives are regenerated by sync. A stale build-evidence patch is rejected before that point, and incompatible bundles are rejected by preview/install. Keep this even when it makes the workflow less convenient.

## Keep the policy/narrative boundary

Deterministic code chooses items, ordering, Queue membership, legal ability levels, and protobuf behavior. The model explains a closed packet and cannot add, remove, reorder, or strengthen claims. That is the right architecture.

## Keep the Steam mutation boundary unchanged

The safety work in [cache.py](../src/deadlock_build_sync/cache.py) is excellent and should not be mixed into a presentation refactor:

- refuse before any install while Deadlock is running;
- recheck immediately before replacement;
- preserve favorites, selected builds, saved builds, unrelated private builds, and out-of-scope fields;
- identify only same-account, same-hero entries carrying the managed marker;
- refuse duplicate managed entries;
- require complete snapshot/policy identity;
- create and fsync a backup;
- write and validate a temporary replacement;
- fingerprint out-of-scope data before and after;
- atomically replace the cache;
- validate the installed result;
- restore from backup if any step fails.

This boundary is more important than any build-content improvement.

## Keep the Python implementation

This repository contains no Rust manifest, Rust source, or Rust toolchain. It is a Python project, and no Rust rewrite is justified. Python already has the needed KV3 dependency, a strict typed toolchain, broad tests, and clear boundaries.

# HOW WE CAN BEST MAKE USE OF SPACE

## Treat the UI as a hierarchy of surfaces

Use each surface for the question it answers best:

| Surface | Best use | Avoid |
|---|---|---|
| Title | archetype, queue, freshness | redundant hero/author, WR claims |
| Three tags | axis, function, audience | zero/unknown IDs, three synonyms |
| First description lines | role, Queue rule, economy/fight plan | hashes and disclaimers first |
| Category description | one short executable rule | full item enumeration |
| Item hover | why/use, timing, adoption/support | raw WR as the main takeaway |
| Ability-order annotation | selection method and weakest support | misleading exact-path popularity |
| Sidecar/preview JSON | full evidence and provenance | forcing audit detail into combat UI |

## Keep category descriptions short

The generated category summaries currently have a median length of about 253 bytes and often enumerate all ten items. That duplicates the visible cards and is too slow to scan.

Recommended fixed descriptions:

- CORE ITEMS: “AUTO QUEUE • Default path, buy left→right.”
- TIER 1–4: “OPTIONAL • Excluded from Queue; choose deliberately.”

If a trustworthy hero-specific condition becomes available, use a second compact clause. Do not dump all item names into the header.

## Spend hover space on action, not provenance

Use a maximum of two short lines:

1. hero-specific mechanics-grounded action;
2. deterministic observational context.

Example template:

> {order/use sentence, ≤165 bytes}
>
> Usually {q25–q75 net worth} • adopted {rate} (n={eligible}).

If evidence is sparse or net-worth coverage is weak, say so instead of filling the line with a noisy number.

## Reclaim duplicate cards before changing dimensions

Removing CORE duplicates from tier menus recovers 297 slots in the current roster. This is the cleanest space improvement because it increases distinct information without adding categories, shrinking cards, or changing the user-liked layout.

## Do not fill space merely because it exists

CORE’s 6+2 flow leaves visible room on the second line. That whitespace is not automatically a defect. It separates the automatic path from dense option menus and makes the eight-card sequence easy to count. Adding weak items to fill it would reduce clarity.

## Limit active and execution burden per realized path

The menu can contain several active options, but the default realized path must remain under four active bindings. Optional annotations should reveal activation burden. Complexity tags should reflect:

- active-item count;
- precision/targeting burden;
- imbue choices;
- conditional deviations;
- whether failure to activate removes most of the item’s value.

## Preserve one-screen navigation

Do not imitate public-guide outliers with dozens of categories. The current five sections make every major price tier reachable without scrolling through an author’s full notebook. Put deeper logic in the artifact sidecar and concise reasons in the hovers.

# ALGORITHMS

## Current CORE algorithm

For each hero, the offline artifact provides up to 64 eight-item final-inventory candidates, sorted by joint player-match support. [build_evidence.py](../src/deadlock_build_sync/build_evidence.py) selects the first candidate that:

1. has at least 20 joint appearances;
2. costs no more than the hero cohort’s median final net worth;
3. can be purchased legally from an empty validated inventory;
4. respects components, unique/max-count rules, slot capacity, and four active bindings;
5. leaves exactly the selected final item set after component consumption.

The eight selected items are then ordered by each item’s median observed first-ownership time, with item ID as a deterministic tie-breaker.

Current roster diagnostics:

| Diagnostic | Minimum | Median | 90th percentile | Maximum |
|---|---:|---:|---:|---:|
| Exact CORE joint share | 1.78% | 5.37% | 10.00% | 16.47% |
| Exact CORE joint support | 208 | 1,044 | 2,160 | 3,921 |
| CORE cost / median final net worth | 39.2% | 63.6% | 80.0% | 93.6% |

### What it proves

- the eight final items co-occurred in a meaningful number of eligible player appearances;
- the final set is mechanically legal under pinned assets;
- its total catalog investment is plausible relative to the cohort;
- the displayed order roughly follows observed acquisition timing.

### What it does not prove

- the displayed eight-step order occurred in one player’s match;
- every player should complete all eight;
- the path is optimal;
- the path includes every useful component or temporary item;
- the same path is right while behind, ahead, or facing a particular threat;
- adopter outcomes are caused by the items.

### Recommended near-term improvement

Keep this selector as “observed coherent default v1,” but make its identity explicit in the UI and evaluation. Add:

- component-expansion acceptance tests;
- a minimum joint-share/support warning class;
- per-step support/coverage metadata;
- a flag when core cost approaches median final net worth;
- optional path truncation at a supported stopping point rather than implying every game reaches card eight.

Do not use raw win rate to break ties.

## Current tier-menu algorithm

For each price tier:

1. select the ten items with highest eligible-player adoption;
2. tie-break by adopter count and item ID;
3. display those ten from earlier to later median first-ownership net worth;
4. fall back to observed clock time and item ID when needed.

This is deterministic, comprehensible, and outcome-agnostic. Its weakness is semantic: it creates a popularity reference menu, not a set of validated situational choices.

Recommended v1.1:

1. exclude CORE IDs;
2. require minimum adoption/support and usable timing coverage;
3. take up to ten, not exactly ten at any cost;
4. assign a mechanics-only job label;
5. display earlier-to-later as today;
6. keep every tier optional.

Recommended future v2:

- generate the legal candidate set from current inventory/components/slots;
- include “save” as a real candidate;
- condition on queue, patch, rank/mastery, owned items, liquid currency, hero, allies, enemies, and observable threat state;
- compare only similarly accessible alternatives;
- partially pool sparse heroes/items without crossing patch or queue boundaries;
- output uncertainty and abstain when overlap is inadequate;
- recover after deviations instead of restarting a fixed list.

A sequence model can improve next-purchase imitation. It cannot by itself convert observational choices into optimal or causal recommendations.

## Current ability-order algorithm

Each API row represents one player appearance grouped by its observed ability sequence, which may be a prefix from length 1 through 16. The selector:

1. rejects malformed rows, impossible counts, and paths with more than four abilities or more than four uses of one ability;
2. groups decisions by position and current ability-rank state;
3. sums match support for each legal next ability among all rows that reached that state;
4. chooses the highest-supported next ability, with numeric ability ID as deterministic tie-breaker;
5. repeats until 16 changes are selected;
6. requires exactly four abilities, each appearing four times;
7. schedules the selected changes at their earliest legal levels using pinned unlock/AP mechanics;
8. rejects the hero if a complete legal projection cannot be produced.

In compact form, at state s_i the selector chooses:

~~~text
next(s_i) = argmax_a observed_support(a | s_i)
~~~

subject to the four-rank limit and final 4×4 completeness.

### Strengths

- uses partial observations rather than discarding every non-complete match;
- conditions on the actually reached rank state;
- is independent of raw outcome rate;
- validates exact current levels and AP costs;
- fails closed when it cannot finish legally;
- exposes support at every decision.

### Limitations

- the synthesized 16-step path may not have appeared exactly;
- one default does not express common branch points;
- state excludes items, allies, enemies, lane, and live objectives;
- late decisions naturally have less support;
- the public property named pick_rate is actually final-branch support divided by all valid telemetry appearances;
- the sole annotation emphasizes final adopter outcome instead of the decision with weakest support or the first major breakpoint.

### Recommended improvement

Keep the selector, rename its measures truthfully, and surface:

- “state-composed observed default”;
- minimum and final decision support;
- the first meaningful branch where runner-up support is close;
- the legal level of major upgrades;
- an explicit low-confidence tail marker.

If the Steam schema continues to support only one order, place alternatives in prose/sidecar rather than corrupting the executable sequence.

## Statistical language policy

Keep four claim classes separate:

| Evidence | Allowed language | Reject |
|---|---|---|
| Pinned mechanics | grants, requires, can target | guarantees the fight |
| Descriptive adoption | observed, adopted, common | best, optimal |
| Predictive temporal holdout | predicts, ranks, calibrated | improves win chance |
| Causal/experimental | estimated effect under stated assumptions | universal causation |

The current project is primarily mechanics + descriptive evidence. That is enough to make a trustworthy guide if the UI is honest.

# TITLES

## What a title must communicate

In priority order:

1. build identity/archetype;
2. queue/cohort distinction;
3. freshness;
4. managed provenance only if space remains.

Hero and author are already visible elsewhere in the browser. Patch title may be vague or long; “Matchmaking Update” says little about how McGinnis or Mirage is built.

## Recommended grammar

~~~text
<archetype> | <queue> | <YYYY-MM-DD>
~~~

Rules:

- hard cap at 50 characters;
- truncate archetype last, not date/queue first;
- use a stable date from the governing mechanics/telemetry epoch;
- use “Evidence Default” when no reviewed archetype exists;
- never include WR, “best,” “broken,” or “mathematically optimal”;
- do not use a version number unless it is tied to the projection fingerprint.

If multiple managed variants are added later:

~~~text
<variant> — <archetype> | <queue> | <date>
~~~

## Tags should share the load

Do not force the title to encode damage axis, role, ability focus, and audience simultaneously. Use the three tag slots for:

- axis;
- function;
- complexity.

Then the title can remain short and legible.

# ABILITY ORDER

## Keep

- native 16-change Steam encoding;
- the 1/2/5 AP upgrade deltas;
- exact pinned unlock/AP scheduling;
- state-conditioned support;
- outcome-independent choice;
- rejection of incomplete heroes;
- one annotation on the first change rather than repeating it 16 times.

## Fix

- remove the obsolete complete-path pick-rate sentence;
- rename pick_rate in internal/public descriptions;
- remove raw outcome rate from the primary in-game annotation;
- state that the path is synthesized from reached legal states;
- include tail/minimum support;
- add a compact “first max / ultimate timing” phrase only when it can be derived from the legal timeline without model invention.

## Do not do

- do not divide the ability order into four “quarters” aligned with item tiers;
- do not optimize ability order by raw win rate;
- do not infer an item/ability combo merely because both are popular;
- do not hide a low-support tail;
- do not emit an illegal complete path just to avoid skipping a hero.

# SECTION-BY-SECTION SPECIFICATION

## CORE ITEMS

Keep:

- exact name;
- eight cards for the current evidence method;
- only non-optional category;
- left-to-right Queue order;
- current upper-left geometry.

Change:

- description to “AUTO QUEUE • Default path, buy left→right.”
- map the eight validated action explanations to these eight hovers;
- show why/use first and timing/adoption second;
- call it an observed default, not universal;
- flag a late/low-support tail;
- verify component expansion and deviation recovery in the live client.

Selection:

- retain highest joint-support legal final inventory within median final net worth;
- retain outcome-independent selection;
- retain legality simulation;
- consider a supported stopping point or upgrade-expanded path in a later algorithm version.

## TIER 1

Keep:

- exact name;
- optional flag;
- upper-right location;
- earlier-to-later observed purchase ordering.

Change:

- exclude CORE duplicates;
- describe it as a price-tier reference, not “early game”;
- prefer explicit bridge, sustain, or lane-stability mechanics when supported, without pretending tier implies phase;
- show concise mechanics job + observed window;
- never auto-queue the row.

## TIER 2

Keep:

- exact name;
- optional flag;
- middle-left location;
- price-tier identity.

Change:

- exclude CORE duplicates;
- distinguish enablers/upgrades from generic stat choices using pinned component and mechanics data;
- surface active/imbue requirements;
- avoid “counter” language without a named, supported threat state.

## TIER 3

Keep:

- exact name;
- optional flag;
- middle-right location;
- chronological display among selected options.

Change:

- exclude CORE duplicates;
- make opportunity cost visible because Tier 3 choices increasingly compete for slots and timings;
- indicate active burden and replacement/sell implications when known;
- use mechanics-only defensive labels until comparative threat evidence exists.

## TIER 4

Keep:

- exact name;
- optional flag;
- full-width bottom row;
- a maximum of ten one-line capstone choices.

Change:

- exclude CORE duplicates;
- do not call every Tier 4 item “late game”;
- show slot consolidation, active burden, and prerequisite/component information;
- do not let high adopter outcome turn a luxury item into an automatic recommendation;
- allow fewer than ten if support is weak.

# REPOSITORY AND LANGUAGE PATTERNS

## Engineering verdict

| Area | Verdict |
|---|---|
| Architecture boundaries | Strong |
| Steam data safety | Excellent |
| Internal artifact identity | Excellent |
| Live-patch freshness visibility | Needs improvement |
| Mechanical legality | Strong |
| Statistical claim discipline | Strong |
| Python typing/lint/testing | Strong |
| Player-facing information routing | Weak |
| Title/tag discovery UX | Weak |
| State-reactive recommendation | Not yet implemented |

The tracked repository is approximately 15,900 lines of Python across source, tests, scripts, and evals. It also includes a detailed README, license, changelog, contributing and security guidance, scoped AGENTS.md instructions, JSON schemas, CI, tag-driven release automation, Dependabot, and a monitoring runbook. The runtime dependency surface is deliberately small: keyvalues3 is the only required project dependency; model/evaluation and quality tools live in the development group.

The current head has already resolved several serious findings documented in the older strategy research:

- Ranked/Unranked mode is explicit rather than silently pooled.
- Client, as-of cutoff, rank labels, patch, and four epoch identities are frozen.
- Hero descriptions and structured mechanics are preserved.
- Tier categories are truly optional in protobuf.
- item annotations can encode flex, sell, and imbue fields;
- ability selection uses reached-state prefixes instead of exact-complete-path popularity;
- price tiers are no longer equated with ability “quarters”;
- core selection uses reconstructed final inventory rather than raw purchase-event popularity;
- current sync requires a build-evidence artifact and rejects aggregate substitution.

That delta matters: the older research remains valuable background, but its historical defect list should not be copied into new issues without checking the current code.

## Python patterns to keep

The codebase uses Python appropriately:

- src layout and a small dependency surface;
- frozen dataclasses for admitted domain values;
- StrEnum for policy and evidence vocabulary;
- explicit validators at JSON/protobuf/cache boundaries;
- custom domain exceptions with precise failure reasons;
- deterministic sorting and SHA-256 fingerprints;
- atomic JSON writes;
- separation between dynamic API Any payloads and validated domain objects;
- Ruff with ALL rules, strict ty settings, pytest, locked uv environment, CI, release verification, wheel smoke test, and pinned GitHub actions;
- regression coverage for mechanics, policy, rendering, protobuf, KV3, cache recovery, artifacts, narratives, CLI, telemetry, and evals.

The strongest recurring pattern is “parse dynamic input once, validate aggressively, then pass an immutable typed object.” Apply the same pattern to build tags and player-facing narrative projection.

## Python patterns to improve

1. **Create a typed BuildPresentation domain object.** It should own title archetype, three tag IDs, short description lines, per-item tactical annotations, and ability annotation. Do not assemble these ad hoc inside protobuf.py.
2. **Separate audit description from display description.** Preserve the full manifest in the backup/sidecar and a trailing metadata block, while giving the player-first text its own validated type and length limits.
3. **Make narrative application complete.** Every generated field should either have a documented consumer or be removed from the expensive generation contract.
4. **Rename misleading compatibility properties.** Keep a temporary alias only if external callers require it.
5. **Make standard section policy data-driven but identity-locked.** The names and optional semantics remain constants; membership and compact descriptions are validated inputs.
6. **Keep renderer/protobuf pure.** It should encode an already-complete presentation, not decide statistical meaning.
7. **Split orchestration only at stable seams.** service.py, cache.py, policy.py, and scripts/generate_narratives.py carry explicit complexity waivers because they validate transactions and closed artifacts. Keep the named stages, but extract pure presentation mapping and tag selection rather than breaking the transactional cache path into loosely coordinated helpers.
8. **Add a tracked reproduction command.** The project documents the full uv gate, but the live/public-build measurements in this report currently require shell reconstruction. A read-only audit command or script should emit a versioned JSON summary without writing Steam data.

## Rust findings

There is no Rust in deadlock-build-sync. The request to inspect Rust patterns is therefore “not applicable” to this repository, not a missing implementation.

The adjacent deadlock-api repository is Rust and provides useful interop evidence:

- BuildHero is a typed serde struct with u32 identity fields, Option for sparse fields, and a default Vec<u32> for tags.
- Build-tag assets are deterministically sorted and IDs are derived from stable class names.
- API structs distinguish absent optional category/item fields instead of coercing them into false facts.
- The source confirms tags are a repeated list and the protobuf exporter confirms field 11.

Those are patterns to borrow in Python—explicit optionality, typed IDs, deterministic ordering, and schema fixtures—not reasons to introduce a second language. A Rust component should be considered only if a measured offline telemetry bottleneck cannot be solved cleanly in the existing analysis project.

# PRIORITIZED ROADMAP

## Phase 0: truth and routing

Implementation brief: [Phase 0 — Truth and routing](roadmap/phase-0-truth-and-routing.md).

1. Add a read-only freshness preflight comparing installed artifacts with the latest patch/client.
2. Correct ability-path terminology in descriptions, JSON preview, tests, and docs.
3. Add a presentation model with explicit length limits.
4. Map exact validated core action explanations to exact CORE items.
5. Reorder build description so tactical use precedes provenance.
6. Keep all marker/snapshot/policy strings required by cache validation.

Exit criterion: the build says exactly how its current algorithms work, and every expensive generated field has a player-facing or audit-facing consumer.

## Phase 1: tags, titles, and duplicate space

Implementation brief: [Phase 1 — Discovery and space](roadmap/phase-1-discovery-and-space.md).

1. Fetch/pin the build-tag taxonomy with the same client identity as items/heroes.
2. Encode exactly three valid repeated field 11 tags.
3. Add deterministic tag selection and golden decode tests.
4. Change title grammar to archetype | queue | epoch date.
5. Exclude CORE IDs from tier-menu selection.
6. Permit up to ten adequately supported tier items rather than requiring filler.

Exit criterion: no unknown tag badges, no misleading title, and no unexplained CORE duplication in optional space.

## Phase 2: hover hierarchy

Implementation brief: [Phase 2 — Hover hierarchy](roadmap/phase-2-hover-hierarchy.md).

1. Produce ≤165-byte core tactical instructions.
2. Append deterministic window/adoption within the 240-byte total.
3. Remove raw adopter outcome from the default hover.
4. Add mechanics-only job labels for tier options.
5. Show active/imbue/sell/flex requirements when actually encoded.

Exit criterion: a player can hover any CORE item and learn what it does for this hero and roughly when it is observed, without reading a statistical disclaimer.

## Phase 3: sequence and deviation research

Implementation brief: [Phase 3 — Sequence and deviation](roadmap/phase-3-sequence-and-deviation.md).

1. Evaluate component-expanded shopping paths in the live client.
2. Reconstruct purchase, upgrade-consumption, discretionary-sell, and save decisions.
3. Build an outcome-agnostic next-observed-action baseline.
4. Add current inventory, components, currency, slots, queue, rank, and patch context.
5. Evaluate temporally on a later patch window.
6. Report recall/NDCG only as imitation quality, plus legality, coverage, calibration, and deviation recovery.

Exit criterion: the system can recover after a manual deviation and can abstain when evidence is sparse.

## Phase 4: situational policies

Implementation brief: [Phase 4 — Situational policies](roadmap/phase-4-situational-policies.md).

1. Define a mechanics-first threat taxonomy.
2. Generate only legal response candidates.
3. Compare alternatives at the same decision opportunity with overlap checks.
4. Encode observable trigger, replacement, execution, and failure conditions.
5. Keep unsupported branches in the sidecar as abstentions.

Exit criterion: every “when X, choose Y” sentence has a verified mechanism, a feasible timing, a comparator, adequate support, and a failure condition.

# VALIDATION PLAN

## Deterministic tests

- Decode field 11 and assert exactly three nonzero IDs from the pinned tag catalog.
- Round-trip title, tags, description, categories, item annotations, ability order, imbues, sell priorities, flex gates, and optional flags.
- Assert CORE is the only non-optional category.
- Assert exact section names and stable order.
- Assert no tier item duplicates a CORE item under the disjoint-menu policy.
- Assert no item/category annotation exceeds its UTF-8 byte budget.
- Assert narrative node/item/evidence identity before applying an instruction.
- Assert the managed marker, Snapshot line, and Policy line remain discoverable after description reordering.
- Add a synthetic ability fixture where the state-composed path is not an exact observed complete path; assert all labels remain truthful.
- Assert low-support tails are flagged.
- Property-test item paths for component consumption, max counts, nine base slots, flex slots, and four active bindings.

## Model-backed tests

Prompt or validator changes require the relevant DeepEval suite:

- no policy/category/item mutation;
- no invented mechanics or timings;
- no causal language from adoption/outcome evidence;
- complete sentences;
- exact action ordering;
- exact category identity;
- byte-budget success rate;
- useful hero-specific content rather than generic item restatement.

Add a metric for **projection utilization**: every required narrative field must be consumed by a declared UI or audit surface.

## Live client acceptance matrix

Run only with explicit authorization and with normal backup protections:

- representative weapon, spirit, melee/tank, summon/support, and new/sparse hero;
- 2560×1440 plus at least one 16:9 lower resolution and one ultrawide;
- My Builds preview title and three resolved tags;
- CORE Queue left-to-right;
- every tier excluded from automatic Queue;
- queued parent upgrade expands or purchases components correctly;
- manual deviation does not strand Quickbuy;
- imbue target does not stall automatic purchase;
- annotations fit without clipping;
- ability order schedules at correct legal levels;
- game-running checks prevent any cache write.

Do not weaken a validator to make the client test pass. Fix the evidence or projection.

# REPRODUCIBILITY

The live-client conclusions require visual inspection, but the repository and API measurements can be repeated without touching Steam.

## Frozen artifact checks

~~~bash
jaq '{
  hero_count: (.heroes | length),
  client_version: .snapshot_manifest.client_version,
  as_of_timestamp: .snapshot_manifest.as_of_timestamp,
  patch: .patch.title
}' ~/.local/state/deadlock-build-sync/artifacts/strategy-context.json

jaq '{
  schema_version,
  prompt_version,
  hero_count: (.heroes | length),
  patch: .patch.title
}' ~/.local/state/deadlock-build-sync/artifacts/narratives.json
~~~

## Live freshness checks

~~~bash
curl -fsSL https://api.deadlock-api.com/v2/patches \
  | jaq '.[0:5] | map({title, pub_date, link})'

curl -fsSL https://api.deadlock-api.com/v1/assets/client-versions \
  | jaq 'sort | reverse | .[0:10]'
~~~

## Per-hero public-build sampling

The audit iterated the active hero IDs and requested ten builds per hero with these query parameters:

~~~text
min_unix_timestamp=1785438877
sort_by=weekly_favorites
sort_direction=desc
only_latest=true
build_language=English
limit=10
~~~

The resulting JSON was streamed directly into jaq; it was not saved in the repository. Recalculate the percentages because the endpoint is live.

## Repository inventory

~~~bash
git status --short --branch
git ls-files
fd -t f -e py
fd -t f -e rs
tokei src tests scripts evals
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv pip check
uv build
~~~

At audit time the repository contained Python, Markdown, JSON, TOML, YAML, and fixtures, but no Cargo.toml or Rust source. The final gate for this documentation-only change was executed in an isolated temporary copy so build/test artifacts did not alter the user’s working tree.

# SOURCES

## Primary Deadlock/API sources

- [Deadlock API documentation](https://api.deadlock-api.com/docs)
- [Current active hero assets](https://api.deadlock-api.com/v1/assets/heroes?only_active=true)
- [Current public build search](https://api.deadlock-api.com/v1/builds)
- [Current build-tag taxonomy](https://api.deadlock-api.com/v1/assets/build-tags)
- [deadlock-api source](https://github.com/deadlock-api/deadlock-api)
- [Valve: Shop Rework, May 8, 2025](https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/1799088287841594)
- [Valve: November 21 slot/level/economy update](https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/1816849002015766)
- [Valve: July 28, 2026 update](https://store.steampowered.com/news/app/1422450/view/680756685198855508)
- [Valve: July 30, 2026 matchmaking update](https://store.steampowered.com/news/app/1422450/view/680756685198854910)
- [Valve: August 12, 2026 minor update](https://store.steampowered.com/news/app/1422450/view/708906085669405228)

## Community evidence, used qualitatively

- [Deadlock community discussion: how players interpret left-to-right and optional build rows](https://www.reddit.com/r/DeadlockTheGame/comments/1rhidza/question_about_builds_in_deadlock/)
- [Deadlock community discussion: Queue versus manual buying](https://www.reddit.com/r/DeadlockTheGame/comments/1u5hhhe/queue_build_or_buy_from_left_to_right/)
- [Deadlock forum: optional items entering auto-queue](https://forums.playdeadlock.com/threads/auto-queue-is-adding-optional-items.110648/)
- [Deadlock forum: imbue items and autobuy](https://forums.playdeadlock.com/threads/autobuy-imbue-items-breaks-it.63439/)
- [Deadlock forum: request for dynamic/flexible build choices](https://forums.playdeadlock.com/threads/new-build-feature-flex-pick-categories-dynamic-shop-logic.119788/)

## Cross-MOBA and research

- [Dota Plus Assistant](https://www.dota2.com/plus)
- [Dota 2 Hero Builds overview](https://www.dota2.com/workshop/builds/overview?l=english)
- [Riot: Preseason Item Shop Update](https://www.leagueoflegends.com/en-us/news/dev/preseason-item-shop-update/)
- [Riot: Updated approach to item balancing](https://www.leagueoflegends.com/en-gb/news/dev/dev-updated-approach-to-item-balancing/)
- [Riot: 2024 item changes](https://www.leagueoflegends.com/en-us/news/dev/dev-2024-item-changes/)
- Dallmann et al., [Sequential Item Recommendation in the MOBA Game Dota 2](https://arxiv.org/abs/2201.08724)
- Villa et al., [Interpretable Contextual Team-aware Item Recommendation](https://arxiv.org/abs/2007.15236)

## Final recommendation

Do not redesign the five rows. Make the information already produced by the system visible and truthful:

> CORE ITEMS is the only automatic, observed default path. TIER 1–4 are compact, disjoint, optional price-tier reference menus. Titles and tags identify the archetype. Descriptions teach the role. Hovers explain why and when. Ability order is labeled as a state-composed default. Full evidence remains in the sidecar. Steam safety remains untouched.
