# Repository and Deadlock Build Research

<!-- markdownlint-disable MD013 -->

Research date: 2026-08-17
Repository commit: `1bcef6f1f1579ec710a80044f1138dbd6e1fed89`
Repository branch: `fix/sonarqube-cleanup`
Deadlock client seen in the live UI: `#6,679`

This is a research report, not an implementation. No match was started, no live
sync was run, and no Steam build data was changed.

## Contents

- [Executive summary](#executive-summary)
- [Scope, method, and safety](#scope-method-and-safety)
- [Priority research roadmap](#priority-research-roadmap)
- [Confirmed Kelvin layout defect](#confirmed-kelvin-layout-defect)
- [What current community builds show](#what-current-community-builds-show)
- [How strong MOBA builds are created](#how-strong-moba-builds-are-created)
- [Current build evidence, in plain language](#current-build-evidence-in-plain-language)
- [Player-visible wording audit](#player-visible-wording-audit)
- [Repository audit](#repository-audit)
- [Proposed test and research backlog](#proposed-test-and-research-backlog)
- [Verification record](#verification-record)
- [Sources](#sources)

## Executive summary

The repository is safety-minded, well tested, and appropriately written in
Python. It should not be rewritten in Rust, Go, or TypeScript. The highest-value
work is to simplify the existing Python boundaries and make the build UI match
what the code produces.

The most important findings are:

1. Kelvin's hidden CORE items are a confirmed layout bug. The build contains 15
   queued CORE cards in a fixed-height panel. Only 12 are fully visible at
   2560 by 1440. Escalating Exposure, Boundless Spirit, and Greater Expansion
   occupy the clipped third row.
2. This is a roster-wide risk. Nineteen of 38 current builds contain more than
   12 CORE cards, and 45 cards in total fall after the twelfth position. Of
   those 45, 42 are intended final targets, not prerequisite reminders.
3. The code validates eight final CORE items, then adds component cards without
   rechecking display capacity. The serializer always applies the same CORE
   dimensions. The tests cover the eight-item rule, not the rendered card
   count. The same contract mismatch affects text: all 38 reviewed descriptions
   and 50 card notes exceed the current in-shop editor's limits.
4. Current analytics support a legal default ending set and a broadly sensible
   purchase order, not one commonly observed exact route. The current packet is
   also too weak for matchup-specific counter claims: it checked 5,700 possible
   situational rules and admitted zero. Silver's linked transformed abilities
   are also silently dropped from ability support, although normalizing them
   did not change the selected order.
5. Four offline data bugs require rebuilding from the saved raw input: some
   winner-only matches pass the filter, same-second event replay can keep
   removed components, the next-item model loses upgrade credit while mixing
   two moments in the match, and its test choices include items that cannot fit
   in a full inventory.
6. The read-only `recommend` command is not ready as a player workflow. It
   repurchases consumed ancestors in nested upgrades and, after all 38 default
   paths were supplied as complete, recommended another buy for 36 heroes.
7. AI-written text checks file and record IDs but not every factual claim. Both
   generation stages accept invented abilities, item effects, and unsupported
   numbers when the answer preserves IDs and passes a few phrase checks.
   Reviewed text bypasses even those generation checks and can still be labeled
   current.
8. Saved-file hashes show that a file agrees with its own declared identity,
   not that duplicated build data agrees across files. A test file with freshly
   calculated hashes accepted invalid Steam behavior fields and changed support
   under an unchanged build-plan ID. The current saved bundle agrees exactly,
   so this is a loader weakness rather than present corruption.
9. The fact that no counter choices currently pass validation masks a broken
   threat parser: all 156 current items are labeled as both bullet and spirit
   pressure because disabled property names are read as active mechanics.
10. The Steam installer preserves out-of-scope user data well, but its error
   path can replace the cache after Deadlock starts. Selected marker-owned
   copies can also remain stale, it lacks a compare-before-swap check, and
   restore is not scoped to the exact Steam installation in the manifest.
11. The August 16 Sonar cleanup is real as a historical result, but a fresh
   checkout cannot reproduce it. The repository has no Sonar project file,
   quality profile, issue export, or CI job.
12. The largest maintainability problem is concentration, not language choice.
   One report function is 827 lines, the narrative runner is a 1,903-line
   top-level `scripts` module shipped in the wheel, and component expansion is
   implemented in three places.
13. Player-facing names are too academic. Keep exact statistical terms inside
   offline analysis, but use Deadlock words such as build, item, ability,
   purchase path, souls, match group, Extra Slot, patch, and skipped hero in the
   CLI and generated guides.

## Scope, method, and safety

### Repository work

The review covered all 125 tracked files, the package and test layout, release
automation, documentation, current branch history, CLI help, dependency use,
module imports, function size, and configured static checks. It also inspected
the current generated build packet under the user's XDG state directory.

The production package contains 43 Python modules and 21,053 code lines, or
23,195 physical lines when blanks and comments are included. The full tracked
Python estate contains 90 files and 30,819 code lines, including tests, offline
analysis, and scripts.

### Live Deadlock work

The game was already open. Inspection stayed in the lobby and build interface.
No hideout, bot match, public match, queue, build selection, or purchase was
started. A desktop shortcut eventually opened the lock screen, so the visual
pass stopped there rather than risk further input.

The live pass directly verified the current Kelvin build at 2560 by 1440. A
read-only parse of the installed VPK directory and embedded compiled Panorama
style strings then checked the current build-panel overflow rules. A bounded
ValveResourceFormat 20.0 pass decompiled only the relevant layout/style copies
into a temporary directory; it did not change the game installation. API
research sampled public builds without changing the game or Steam files.

The local Steam manifest identifies this client as Steam build `24741201`,
last updated at Unix time `1786756548`. The 6,890,081-byte
`citadel/pak01_dir.vpk` directory has SHA-256
`d31546abcd3b7a5cb477e2cc2979df39531de92b11f301a86b7781d3e7e6e82e`.
Within it, the compiled build-surface and category-style payloads have SHA-256
`47a59c732e44136e335a339a5ae6a4b66987f9eed3a6e238b5f6905280264c3a` and
`e19631b4375785cca9287bb217ed8a51b3c1db3753694636675b0cdb6969e559`.
The compiled card style that defines the 80-by-125 box hashes to
`98034c4218c8c526c3ca73c261f1a7e3f8a4e3c213939b1093f78fe5127d45cc`.
The Queue Build and HUD Quickbuy layout payloads hash to
`f77eb35ddb70f6e401a3f09e8301c4b149b1f0fb5c170b9adb61f945f1ff70cf`
and `05aaa781d0edb244e338cc2fb579a1ade25f14897cd77838e6e79bf27b1bc2e0`.
The compiled build-details style used for description visibility and scrolling
hashes to
`ab55ed7f2d4a12bc74d7410150aa80feb0eb21bc686cae298c055aff266acd72`.
The in-shop build editor layout that defines its separate text limits hashes to
`0e742d76bf50c87d53c52d963ee7d321957666753d0e5be06eb2c27ee4d7f9e2`.
The current ability-order layout and style payloads hash to
`beeadcbbf0d04702a580855fa9ade11a31bb3f1dbcaed24b0320afa021c22089`
and `3f146f1dbda3551b0cfe8830de0711aa9682eeb6dcfc68226010ee58781534e7`.
These identities make the client-side layout evidence reproducible after a
patch. Steam build `24741201` and asset client version `#6,679` are different
version systems; their numbers should not be compared or substituted.

### Community-build sample

The sample used the public build endpoint documented by the
[Deadlock API][deadlock-api] and its [query contract][build-api-query]. It
requested the ten most weekly-favorited current English builds for each of the
38 active heroes, with `only_latest=true` and a minimum timestamp of 2026-07-30.
The endpoint applies `min_unix_timestamp` to the build's **last update**, not
its original publication. This produced 380 builds. It is a balanced layout
sample, not a popularity-weighted estimate of all builds or newly created
guides. A final active-asset query still returned exactly the same 38 playable,
non-disabled hero IDs, so replay drift came from builds rather than a roster
change.

### Limits

- Public-build favorites reflect author reputation, exposure, age, and player
  taste. They do not prove that a build wins games.
- Public-build search has no game-mode filter. Three of 380 fresh rows included
  Street Brawl Legendary cards, so the sample is a layout/design reference,
  not a pure ranked-build population.
- A forum report describes observed client behavior, not a stable Valve API
  contract.
- Buyer win rate is an association after a purchase. It is not the effect of
  buying that item.
- The current analytics window is short and spans a very wide rank range.
- No match was entered, so native queue expansion still needs a safe lobby or
  hideout experiment before any layout design relies on it.

## Priority research roadmap

The 98 decision rows contain 19 P0, 51 P1, 27 P2, and one P3 finding. Here,
**P0** means the issue blocks trusting a result or a Steam safety path; it does
not mean current Steam data is known to be corrupt. **P1** should be resolved
before expanding the affected production feature, **P2** is planned cleanup or
hardening, and **P3** is opportunistic simplification.

| Priority | Finding | Recommended next decision |
| --- | --- | --- |
| P0 | CORE cards are clipped | Define and test a visible-card contract |
| P0 | Components expand after validation | Choose final-only or dynamic CORE |
| P0 | CORE order is reconstructed, not observed | Relabel and score route coherence |
| P0 | Ability “tail support” is not path support | Show state and path evidence separately |
| P0 | Nested upgrades repurchase consumed parts | Stop traversal at an owned upgrade |
| P0 | Completed CORE keeps recommending buys | Check the inventory goal before fallback rules |
| P0 | Row filtering retains winner-only matches | Admit or reject the whole match together |
| P0 | `as-of` limits match start, not match events | Define and enforce one cutoff grain |
| P0 | Equal-time replay retains removed items | Make explicit removal win the timestamp tie |
| P0 | Upgrade replay drops component credit | Replay each timestamp as a mechanics-aware bucket |
| P0 | Ranker query mixes two game times | Define one observable pre-purchase state |
| P0 | Ranker scores items that cannot fit | Carry Extra Slot state and filter candidates mechanically |
| P0 | Mechanics text carries malformed units | Normalize and cross-check value/unit pairs before generation |
| P0 | Generated prose accepts invented mechanics | Bind both stages to supplied mechanic references |
| P0 | Reviewed prose bypasses generation checks | Re-run semantic admission before preview or install |
| P0 | Projection behavior can diverge from policy | Recompute and compare one typed final projection |
| P0 | Restore is account-scoped, not install-scoped | Validate manifest and preserve current cache |
| P0 | Rollback can write after Deadlock starts | Track swap state and recheck before every replacement |
| P0 | Cache mutation has no interprocess lock | Lock per cache and recheck live bytes |
| P1 | Identical syncs still rewrite Steam data | Skip a byte-equivalent managed projection |
| P1 | Projection fingerprints omit visible output | Hash the complete typed presentation |
| P1 | Descriptions exceed the in-shop editor limit | Fit the final description within 512 characters |
| P1 | Fifty card notes exceed the editor limit | Keep the advice; fit the final note within 200 characters |
| P1 | Selected managed copies remain stale | Refresh marker-owned saved copies without changing selection |
| P1 | Status ignores selected managed copies | Report canonical and selected-copy freshness separately |
| P1 | Status collapses duplicate managed builds | Report ambiguity instead of taking the last entry |
| P1 | Decision state accepts unknown IDs | Validate current items, heroes, and abilities |
| P1 | Sonar zero is not reproducible | Add pinned scan configuration and CI |
| P1 | Release rebuilds after verification | Publish the exact verified artifact |
| P1 | License metadata uses a deprecated duplicate | Keep SPDX; remove the license classifier |
| P1 | No counter rules passed | Label tier cards as popularity choices |
| P1 | Threat text reads disabled properties | Require active mechanics, not labels |
| P1 | Counter runtime ignores its comparison point | Match phase, tier, and replaced item |
| P1 | Build tags read dormant schema text | Tag the plan, not raw asset keys |
| P1 | Near-tied ending sets are hidden | Validate hero-specific build variants |
| P1 | 145 imbue cards lack targets | Validate a target or prompt the player |
| P1 | Optional upgrades silently replace CORE | Label upgrade chains and final state |
| P1 | Sell guidance is unused | Explain exits from optional detours |
| P1 | Sell priorities reverse planned sale order | Encode highest number on the earliest sale |
| P1 | “Eight-item path” shows up to 17 cards | Name final items and purchase steps separately |
| P1 | Each CORE hover sees eight item packets | Bind every action to its own mechanics record |
| P1 | Same-second buys are ordered by item ID | Model tied buys as a choice set |
| P1 | “Net worth at buy” is a lagged snapshot | Carry observation time and age |
| P1 | Candidate cap runs before Queue checks | Scan until 64 representable endings pass |
| P1 | Investment spikes are not evaluated | Show and test category breakpoints |
| P1 | Promotion gate can reuse the test fold | Seal one final test and require later data after iteration |
| P1 | XGBoost budget reads all folds | Build candidate constraints from train data only |
| P1 | Ranker identity does not bind its outputs | Hash data, models, metrics, software, and hardware |
| P1 | Phase labels ignore uncertainty | Suppress unsupported strongest/weakest claims |
| P1 | Broad rank label hides subgroup shifts | Report rank stability before making variants |
| P1 | Serializer hard-codes ability costs | Encode the asset-validated currency schedule |
| P1 | Greedy ability choices can reach a dead end | Search for the strongest completable state path |
| P1 | Silver's transformed ability ranks are dropped | Normalize aliases and retain linked-form mechanics |
| P1 | Model changes can reuse old prose | Key reuse and provenance by the generating model |
| P1 | Prompt identity is a hand-maintained number | Hash prompts, schemas, runner, and Codex CLI |
| P1 | Read-only Codex can still inspect host files | Isolate model input in a no-tool, minimal-environment runner |
| P1 | “Current” ignores data-cutoff age | Define an in-patch refresh policy |
| P1 | Patch and asset discovery can straddle an update | Resolve a coherent run boundary and verify it before admission |
| P1 | Online `as-of` selects a future patch | Select the patch published by the cutoff |
| P1 | A forum mirror can revive an old patch | Canonicalize mirrored patch entries before selection |
| P1 | A frozen offline run can be overwritten | Make completed run directories immutable |
| P1 | Producer identity hashes Git's index | Hash the code and environment actually executed |
| P1 | Online evidence stores hashes, not bodies | Archive deidentified responses |
| P1 | Unused Steam persona enters snapshot ID | Remove personal identity coupling |
| P1 | Three component expanders exist | Give game mechanics one owner |
| P1 | Narrative runner ships as `scripts` | Move it into the named package |
| P1 | Runtime schemas ship at top level | Use namespaced package resources and smoke their defaults |
| P1 | Dated layout advice now conflicts | Mark document authority and status |
| P1 | Sync overwrites the working artifact bundle mid-run | Stage and promote one versioned bundle |
| P1 | Policy JSON accepts non-finite evidence | Reject non-standard numbers at decode and encode |
| P2 | Report function is 827 lines | Split calculation from output |
| P2 | CLI exposes research jargon | Give player commands game-language help |
| P2 | Every role line renders `.:` | Join complete sentences without extra punctuation |
| P2 | Every patch line renders a double space | Trim display copy without changing raw provenance |
| P2 | Model packets repeat disabled item defaults | Export one typed mechanic view per action |
| P2 | Category text has no native hard cap | Keep short named phases and reject invisible padding |
| P2 | Ability notes have no visible authoring control | Prove tooltip display and edit/save preservation |
| P2 | Managed tags use only generic labels | Test one validated plan-defining item or ability icon |
| P2 | Full policies are stored twice | Join by ID at deterministic boundary |
| P2 | State-path logic is repeated | Add one small internal XDG path helper |
| P2 | Item defaults differ by loader | Normalize asset fields once |
| P2 | State files repeat derived counts | Derive mechanics from owned items |
| P2 | Live matchup rows are audit-only | Move them offline or give them a closed consumer |
| P2 | Aggregate guide generation is test-only | Remove the obsolete fallback path |
| P2 | A test-only policy evaluator shadows `recommend` | Remove it or choose one runtime engine |
| P2 | Generic compatibility helpers are test-only | Delete unclaimed internal APIs |
| P2 | Read-only generation requires Steam | Keep account discovery at install and cache status only |
| P2 | Snapshot records omit API origin and redirects | Record requested and final source URLs |
| P2 | JSON responses have no size ceiling | Stream into route-specific decompressed-byte limits |
| P2 | Extra Slot requirement has no visible editor | Keep it empty until a native round trip proves support |
| P2 | Backup privacy relies on parent mode | Create private directories and files explicitly |
| P2 | Evaluation scaffolding is documented as operational | Mark it experimental or wire one real workflow |
| P2 | Status hides cache discovery errors | Preserve the real unavailable reason |
| P2 | Freshness has an unreachable duplicate return | Delete it and add dead-code analysis |
| P2 | Artifact coverage lists accept duplicates | Require one requested/excluded row per hero |
| P2 | Source archives include untracked files | Build from an explicit committed manifest |
| P2 | Python 3.14 cannot install the analysis stack | Upgrade the stack before claiming support |
| P3 | Policy types depend back on their codec | Use one serialization direction |

The first two rows should be decided together. Merely increasing one height
constant could reveal the hidden row while pushing later categories below the
viewport.

## Confirmed Kelvin layout defect

### What the client displayed

Kelvin's managed build was titled:

> Utility / Spirit | Ranked | 2026-08-12

The CORE block fully displayed two rows of six cards. The third row appeared
only as clipped card tops. The three clipped cards, in queue order, were:

1. Escalating Exposure
2. Boundless Spirit
3. Greater Expansion

The UI proved the three clipped positions; the names were not readable in the
slivers. Their identities come from matching the 12 visible cards and saved
managed Queue order in the validated current packet.

The item is named **Greater Expansion** in the current client and artifact.

Kelvin's first 12 visible CORE cards were:

1. Extra Regen
2. Extra Charge
3. Extra Spirit
4. Sprint Boots
5. Torment Pulse
6. Healing Booster
7. Healbane
8. Enduring Speed
9. Mystic Expansion
10. Rapid Recharge
11. Improved Spirit
12. Mystic Vulnerability

The build's eight final target items are Torment Pulse, Healing Booster,
Healbane, Enduring Speed, Rapid Recharge, Escalating Exposure, Boundless
Spirit, and Greater Expansion. Seven lower-cost component cards expand that
eight-item plan to 15 visible cards.

The eight final items fit the current nine starting universal item slots and
leave one slot for a deliberate detour. Components are consumed by their
upgrades, so the 15-card display does not mean 15 simultaneous inventory slots.

### Kelvin evidence in context

The current Kelvin match group contains 2,505 eligible player records. Median
final net worth was 38,396 souls. The selected eight-item target set appeared
together in 109 records, or 4.35% of the eligible Kelvin records. Its targets
cost 27,200 souls, or 70.8% of that median ending net worth.

| Hidden item | Buyer records | Middle last-seen net worth | Buyer win rate | Rough 95% range | Pick rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Escalating Exposure | 1,325 | 17k-27k souls | 56.8% | 54.2%-59.5% | 52.9% |
| Boundless Spirit | 1,517 | 18k-29k souls | 58.1% | 55.6%-60.5% | 60.6% |
| Greater Expansion | 1,398 | 19k-30k souls | 57.5% | 54.9%-60.1% | 55.8% |

### What the clipped cards do for Kelvin

The pinned mechanics packet and the independently checked current client data
support a plain, hero-specific explanation. They do **not** support saying that
any item caused the buyer win rates above.

| Card | Current mechanic | Kelvin-specific fit | Limit on the claim |
| --- | --- | --- | --- |
| Escalating Exposure | Repeated spirit damage builds a 4.5% Spirit Amp per stack on that target, up to 12 stacks. The direct fields show a 0.7-second per-target trigger delay and 12-second duration. | Arctic Beam deals spirit damage continuously, and Torment Pulse deals periodic nearby spirit damage. Those are mechanically capable of building or refreshing the effect during a sustained fight. | The data does not prove the item makes Kelvin win, that every beam tick adds a stack, or that the target remains in range long enough to reach the cap. |
| Boundless Spirit | Its direct fields show 30 Spirit Power, 15% Spirit Power, 75 bonus health, and four out-of-combat health regeneration. | Kelvin's supplied kit text explicitly gives Spirit scaling to upgraded Frost Grenade damage and healing, upgraded Arctic Beam damage, and the final Frozen Shelter healing upgrade. The health and regeneration are general survival stats. | Say which unlocked ability benefits; do not turn general Spirit Power into an invented combo or claim it directly improves every part of the kit. |
| Greater Expansion | Its direct fields show 30% qualifying ability range, 30% effect radius, and 10% Spirit Resist. | Kelvin's exported properties explicitly mark Frost Grenade radius, Arctic Beam length, Frozen Shelter cast range, and Frozen Shelter radius as range- or radius-scaled. | Ice Path has no matching range/radius marker in the packet. Do not say the item enlarges every Kelvin ability. |

This is the useful player explanation the current generic card notes stop short
of giving. In game terms: Escalating Exposure fits sustained spirit hits,
Boundless Spirit is the broad late Spirit stat package, and Greater Expansion
makes the explicitly marked grenade, beam, and dome geometry reach farther.
That mechanical fit explains why the cards form a coherent idea; the adoption
and outcome rows only show that players bought them together.

The raw assets contain both direct property records and separate upgrade-delta
records. The report therefore does not add those fields into homemade tooltip
totals. Production prose should use a deterministic, game-resolved value table
before it quotes exact final numbers; a language model should not infer how to
combine the two structures.

The three are also a common **ending cluster**, not three unrelated popular
cards. Replaying final inventory found at least one of them in 2,110 Kelvin
records (84.2%), at least two in 1,431 (57.1%), and all three in 660 (26.3%).
Pairwise ending presence was 980 records for Escalating Exposure plus
Boundless Spirit, 806 for Escalating Exposure plus Greater Expansion, and 965
for Boundless Spirit plus Greater Expansion. Thus the clipped trio appeared
together about six times as often as the exact selected eight-item ending.
The buy-before-explicit-removal timestamp sensitivity discussed later changed
the triple count by only one record, to 659, so the conclusion is not an
equal-time replay artifact. Ending presence is distinct from the buyer counts
above because a bought item can later be sold or consumed.

Those three cards are also the final three targets after sorting by separate
item medians. Their median purchase times were 26.1, 27.2, and 27.8 minutes.
The rough ranges above are unclustered Wilson intervals and therefore do not
correct for repeat players; their heavy overlap gives no support for ranking
the three by buyer outcome.

Kelvin's second-ranked ending is also informative but is not a clean alternate
build. It has 100 supporting records versus 109 for the selected set and swaps
Greater Expansion for Spirit Lifesteal, reducing target cost from 27,200 to
22,400 souls. Sixty-six records contain **both** eight-item subsets, which is
possible after Extra Slots; only 43 contain the selected subset without the
runner-up, and 34 contain the runner-up without the selected subset. Spirit
Lifesteal's individual median purchase time is 21.0 minutes versus 27.8 for
Greater Expansion. Present evidence therefore supports an earlier survivability
detour and later luxury check more strongly than two mutually exclusive Kelvin
variants. A dynamic layout should show the timing and slot question rather than
silently replacing Greater Expansion or queueing both.

Only three of the 109 joint-set records bought all eight targets in the
displayed order, and none contained all 15 expanded cards in that order even
when unrelated detours were allowed. The first target matched 78.9% of the
joint records, but the first two matched only 28.4%. Kelvin needs a clear late
target display, not a claim that one exact 15-card script is common.

The purchase range is the middle half of valid **last-observed** pre-purchase
net-worth values, not an exact live balance or mandatory timing. “Buyer win
rate” is descriptive and must not be shown as the item's causal effect.

### Why it happens

The defect crosses four boundaries:

1. [`offline/layout.py`](../src/deadlock_build_sync/offline/layout.py)
   selects exactly eight final CORE items.
2. [`purchase_guide.py`](../src/deadlock_build_sync/purchase_guide.py)
   expands that set into a legal component purchase path.
3. [`renderer.py`](../src/deadlock_build_sync/renderer.py) validates the eight
   final items and the tier menus, but it does not limit the expanded CORE card
   count.
4. [`protobuf.py`](../src/deadlock_build_sync/protobuf.py) always writes the
   fixed CORE size `(567.0, 307.5)`. Its comment says the box has room for 11
   cards, while the current client showed 12 complete cards.

Each local decision is understandable. Together they produce an unchecked UI
state: valid analytics, valid purchase order, valid serialized data, and an
invalid visible layout.

The regression suite checks final CORE count and tier count. It does not render
or otherwise assert the capacity of the component-expanded CORE category.

The current compiled client style confirms why the slivers are not recoverable
inside CORE. `citadel_shop_mods_build_category` gives its `#ModsContainer`
right-wrapping flow and `overflow: clip`. The parent
`citadel_shop_mods_build` gives the all-category `#CategoryContainer`
right-wrapping flow and `overflow: squish scroll`. In other words, scrolling
belongs to the whole build surface; overflow within one encoded category is
clipped. This matches the live absence of a CORE-local scrollbar and makes
“the player can scroll that panel” an invalid workaround.

This is also a known client scaling failure, not only a bad repository
constant. An April 2026 report reproduced cards pushed below their category at
2560 by 1440 with no further scroll, while the comparison layout fit at 4K.
Another multi-resolution report found builds that fit at 1920 by 1080 and 4K
but wrapped a final card onto a nearly hidden row at 2560 by 1440. The live
Kelvin result matches that reported failure mode. A card-count formula can
prevent obviously undersized panels, but its acceptance threshold must be
resolution-specific until the client makes its scaling invariant. See the
[2560-by-1440 clipping report][build-1440-clipping] and
[cross-resolution build report][build-resolution-scaling].

### Roster-wide impact

The current 38-hero packet projects 487 CORE cards.

| Metric | Result |
| --- | ---: |
| Mean CORE cards per hero | 12.82 |
| Median CORE cards per hero | 13 |
| Minimum | 9 |
| Maximum | 17 |
| Heroes above the code comment's 11-card capacity | 29 of 38 |
| Heroes above the live 12-card capacity | 19 of 38 |
| Cards after position 12 | 45 |
| Final targets after position 12 | 42 of 45, or 93.3% |
| Prerequisite cards after position 12 | 3 of 45, or 6.7% |

CORE card-count distribution:

| Cards | Heroes |
| ---: | ---: |
| 9 | 1 |
| 10 | 3 |
| 11 | 5 |
| 12 | 10 |
| 13 | 6 |
| 14 | 5 |
| 15 | 4 |
| 16 | 3 |
| 17 | 1 |

The 19 builds above 12 cards are Infernus, Vindicta, Paradox, Dynamo, Kelvin,
Haze, Holliday, Bebop, Calico, Grey Talon, Viscous, Pocket, Vyper, Sinclair,
Victor, Paige, The Doorman, Apollo, and Rem.

The overflow is not merely extra component detail. Comparing the displayed
cards with each hero's eight selected final targets shows that 42 of the 45
cards after position 12 are final targets. Every affected hero hides at least
one final target. The only hidden prerequisite cards are Spirit Lifesteal for
Vindicta and Superior Cooldown for Viscous and Paige. This makes the defect a
plan-visibility failure: the UI disproportionately hides the intended ending
items because prerequisites are inserted earlier in the purchase path.

Those 42 cards are 13.8% of all 304 final targets, while only three of 183
prerequisite cards are hidden, or 1.6%. A final target is therefore 8.4 times
as likely to be outside the visible capacity. The hidden targets' median buy
rate is 51.2%, and 22 appeared in at least half of their hero's eligible player
rows, so they are not fringe suggestions. They are later goals: the median of
their item-level first-ownership medians is 27:47 at 24,595 net worth, versus
14:25 at 10,116 for the 262 final targets that remain within the first 12
cards. These are summaries from different buyer groups, not one observed
eight-item route, but they explain the visual bias: prerequisite-first ordering
leaves the late ending plan outside the visible box.

The failure also concentrates in common late upgrades. Greater Expansion is
hidden for seven heroes, Boundless Spirit for six, Transcendent Cooldown for
five, and Superior Duration for four. Those four names account for 22 of the
42 hidden final targets, or 52.4%. Kelvin's three clipped cards therefore
expose a shared ordering pattern rather than a hero-only exception.

Viscous is the worst current case at 17 cards. Five cards can fall onto an
incomplete third row with the current six-card row behavior.

### Dynamic layout options

The best option depends on one client behavior that must first be verified.

#### Option A: show eight final items

Show only the eight final target items and let Deadlock add their required
components to the queue. This would make the CORE panel smaller and teach the
actual target build more clearly.

Roster-wide, this removes 183 prerequisite cards from the visible panels, a
37.6% reduction from 487 CORE cards to 304. Every hero would show exactly eight
cards, safely below the 12-card capacity observed in the current fixed box.
That proves the visible-card result; it does not prove the native Queue will
expand prerequisites correctly.

Valve's [Shop Rework Update][shop-rework] defines the intended behavior:
optional categories stay out of Quickbuy, and a whole build can be queued.
A later official-forum bug report says lower-level prerequisites can be added
for non-optional parent items, but also reports inconsistent optional-item
behavior between automatic loading and manually pressing Queue Build. That
makes prerequisite expansion promising but not yet safe to assume. See the
[auto-queue report][auto-queue].

Before choosing this option, verify in a no-match environment that:

- every final item queues all required components;
- upgrades do not duplicate already owned components;
- left-to-right target order remains intact;
- optional categories do not leak into Auto-queue; and
- selecting or reloading a build behaves the same as pressing Queue Build.

The pinned client's decompiled Panorama layouts sharpen the boundary without
answering that last mechanics question. `Queue Build` calls the native
`CitadelHudHeroBuildsQuickbuyQueueFullBuild()` dispatcher. No build-related
Panorama script is present in the VPK, so prerequisite expansion is inside a
native panel or engine path and cannot be proved from the XML. The behavior
test above remains required.

The layouts and installed English text do establish the player model:

- the build action is `Queue Build`;
- the HUD contains separate `QuickbuyQueue` and `QuickbuySellQueue` panels;
- queue entries can say `Slots Full` or `Marked for Sell` and can be reordered
  or removed;
- `Auto-queue selected build at game start` is backed by the
  `citadel_auto_queue_build` setting; and
- `Auto-buy items when within range of shop` is a separate toggle.

Therefore “non-optional” means included when the build is added to the Queue;
it does **not** by itself mean the client will purchase the item automatically.
Use `Queue Build`, `Quickbuy`, `Auto-queue`, and `Auto-buy` for those distinct
behaviors. The existing guide word `AUTO` collapses them and should be replaced
even before layout behavior changes.

#### Option B: size CORE from its actual cards

Keep explicit component cards, but derive the width and height from card count.
A third visible row may be better than a wide two-row panel because category
width also controls the flow of every later section.

Test native sizing before adding arithmetic. The decompiled category style
defaults the outer panel to `height: fit-children`, and its edit overlay exposes
a draggable `CategoryResizeHandle`. The current protobuf always emits width and
height floats, so an inline/serialized value can override that content-sized
base while the nested `ModsContainer` still uses `overflow: clip`. A no-match
fixture should omit the dimension fields entirely—not encode zero—and test
initial rendering, edit-mode behavior, save/reload persistence, category flow,
and cache round trip. If the client derives and preserves a safe rectangle,
use that native behavior. If omission collapses or mutates unpredictably, keep
explicit dimensions and use the count calculation below.

The current layout reveals a useful approximation. A 1,039.5-unit row is the
full content width. CORE plus Tier I is 1,032.75 units wide, and Tier II plus
Tier III is 1,028.25, so the five categories occupy three rows. A one-row
category is about 152 units tall and CORE's two rows are 307.5 units. At the
observed six cards per CORE row, 13-17 cards need three rows, or roughly 463
units after client measurement.

A 2025 forum report provides a useful behavior warning: its author first
thought custom categories failed to grow beyond one card row, then discovered
that the box had to be resized with the hard-to-find native handle. That is
consistent with the compiled edit overlay and argues against assuming
content-fit dimensions will always repair an imported build. It remains a
community observation from an older client, so the current no-match fixture is
still the acceptance authority. See the
[manual category resize report][manual-category-resize].

The compiled client style makes the card calculation more concrete. A
`CitadelShopMod` is 80 by 125 units with a two-unit margin on every side, and
the category's item container has four units of padding. Six outer card widths
use 504 units; seven use 588, which explains the observed six-card wrap inside
the 567-unit category. Three rows use 387 units before eight units of item
padding, the category header, and border. The fixed 307.5 height cannot contain
that layout. The proportional 463-unit candidate remains a useful test value,
not a proven constant.

Use a one-way preflight even before client rendering. Let
`columns = max(1, floor(width / 84))` and
`card_height = 129 * ceil(card_count / columns)`. Because that generous column
count ignores the known eight units of inner padding, outer border, and whole
header, a category shorter than `card_height` is conclusively undersized;
passing is only permission to run the visual test. Kelvin computes to six
columns, three rows, and 387 card-only units, 79.5 more than the encoded height.
Subtracting padding and adding measured header space may make the production
rule stricter, never looser.

Item annotation lines do **not** change that card footprint. The installed
localization says item notes appear in the shop tooltip, and the live cards do
not render the three-line managed annotations in the panel. The apparent
height association in the public sample was therefore confounded by different
layout choices and should not become a sizing rule. Category description text
does render in the header and can change its height; a layout contract should
account for card rows and measured header content, then test the resulting
rectangle in the client.

That interaction has failed historically: an older forum reproduction showed
a long category description collapsing item space until cards were hidden.
The current client may differ, but the failure shape supports testing header
text and cards together instead of validating either budget alone. See the
[category-description clipping report][category-description-clipping].

Keeping CORE beside Tier I would then use about 935 vertical units across all
three category rows before gaps. Making CORE full-width would force later
categories into three additional rows and use about 1,098 units. These are
geometry-derived test candidates, not safe constants, but they show why width
cannot be chosen from CORE in isolation.

Valve has already implemented one content-aware rule elsewhere: the
[Map Rework Update][map-rework] made default build categories double height
when they exceed nine items. That does not prove unpublished custom categories
will size themselves when explicit dimensions are present, but it gives a
native threshold and behavior to test before inventing a separate geometry
system.

This option needs one shared layout calculation before protobuf serialization,
plus a validation rule for the resulting visible capacity. The calculation
should use named layout rules, not another hero-specific exception.

#### Option C: split the queued CORE path into phases

Split the queued CORE path into clearly named purchase phases while retaining
one left-to-right queue. This can improve scanning, but multiple non-optional
categories must be tested against native queue ordering. It also consumes more
headers and vertical space.

The [Map Rework Update][map-rework] says right-clicking a build-category header
adds every item in that category to Quickbuy and that Valve was reworking
default builds to assume items are bought in their specified order. A split
therefore creates several independent queue controls, not merely visual
subheadings. Test full-build Queue order, manual per-category queueing, and
requeue behavior before relying on the split to preserve one default path.

#### Recommendation

Test Option A first. If the client reliably expands prerequisites, eight final
items are the cleanest player model. The raw replay strengthens this choice:
only 31 of 8,220 joint-support records followed every displayed component card
in order, so exposing all prerequisites visually adds precision the observed
routes do not support. If the client does not expand safely, use Option B with
measured count breakpoints. For the current 13-17-card cases, test a three-row
CORE at its existing width before a full-width layout because it preserves the
compact three-row page. Use Option C only if the game preserves queue order
across category boundaries.

### Layout acceptance contract

A future layout change should not be accepted only because protobuf validation
passes. It should pass a visual and behavioral matrix:

- 2560 by 1440 and 1920 by 1080;
- 8, 9, 12, 13, 17, and the supported maximum number of CORE cards;
- no clipped card, title, annotation, or hover target;
- Tier IV remains reachable without an accidental overlap;
- queue order is left to right and then top to bottom;
- prerequisite expansion is correct;
- optional cards do not silently join Auto-queue; and
- a round trip through the real client preserves dimensions.

The test fixture should include Kelvin's current 15-card path and Viscous's
17-card path.

## What current community builds show

### All-hero API sample

Across the 380 public builds:

| Metric | Result |
| --- | ---: |
| Builds with a description | 380 of 380 |
| Builds with tags | 380 of 380 |
| Builds with an ability-order field | 380 of 380 |
| Categories | 2,707 |
| Median categories per build | 7 |
| Category count, 10th to 90th percentile | 4-10 |
| Maximum categories | 42 |
| Median item cards per build | 42 |
| Item count, 10th to 90th percentile | 27-56 |
| Maximum item cards | 103 |
| Median optional categories | 3 |
| Optional categories | 1,327 |
| Annotated cards | 5,906 of 15,956, or 37.0% |
| Builds with a category above 12 cards | 113 of 380, or 29.7% |
| Categories above 12 cards | 135 |

### Sample independence and API limits

A live top-ten query is not a frozen dataset. Exact-filter replays moved by a
few rows while this report was being written:

| Replay | Categories | Item cards | Annotated cards |
| --- | ---: | ---: | ---: |
| Initial layout pass | 2,707 | 15,956 | 5,906 |
| 14:57 UTC | 2,704 | 15,960 | 5,929 |
| 21:08 UTC | 2,708 | 15,989 | Not re-counted |
| 22:20 UTC | 2,708 | 15,990 | 5,938 |
| 22:50 UTC | 2,715 | 16,004 | 5,938 |

The stable sample definition is 38 heroes times ten returned rows, not one
immutable set of response bodies. Counts below retain their stated replay time
instead of pretending measurements from different pulls are one snapshot.
A final exact-patch-time check at 22:50 UTC contained 124 post-patch revisions
overall, up from 121–122 in earlier pulls, while the 13 heroes changed by the
patch remained exactly 43 of 130. That late drift came from other heroes and
does not strengthen the changed-hero freshness claim.

A follow-up pull at 2026-08-17 14:50 UTC checked concentration without
changing the layout sample definition:

- The 380 rows came from 260 authors. Two hundred eleven authors supplied one
  sampled build, and 215 appeared for only one hero.
- The most represented author supplied 20 builds, or 5.26%. The top five
  supplied 14.47%, and the top ten supplied 20.0%.
- A nonzero `origin_build_id` appeared on 187 builds, or 49.21%. The sample is
  not one-author dominated, but copied or descendant builds mean its design
  choices are not 380 independent votes.
- Build version had a median of 39, a 90th percentile of 300, and a maximum of
  1,987. Nevertheless, published and last-updated timestamps were identical on
  all 380 responses, so these latest-version rows alone cannot reconstruct
  maintenance history.
- The request sorted by weekly favorites, but `num_weekly_favorites` was null
  on all 380 responses in the 14:50 UTC snapshot. Total favorites were highly
  skewed: the median was 33.5, the 90th percentile 32,122, and the maximum
  80,569. An exact replay at 22:18 UTC produced the same counts with both the
  deprecated `language=0` filter and `build_language=English`, so this was not
  a transient missing-field response. An otherwise identical query without the
  July 30 minimum timestamp did expose 128 weekly-rollup rows and 252 all-time
  rows; each exposed only its corresponding count. The server ordering is
  therefore useful for discovery, but weekly popularity in the bounded sample
  is not independently auditable from the returned rows. The endpoint's
  [query source][build-api-query] explains how this can happen: its common table
  expression keeps `data AS builds` and `weekly_favorites` separately, then the
  final query selects only `builds` while ordering by the separate weekly
  column. The sort value can exist in PostgreSQL without being serialized in
  the returned build JSON. The installed client further describes its `Top
  Weekly` badge as builds most played in the past seven days, so the
  user-facing concept may be usage rather than literal new favorites; this
  response still does not establish which action its hidden weekly sort value
  measures.
- Only 121 builds, or 31.8%, were published at or after the August 12 patch.
  Among the 13 heroes changed by that patch, 43 of 130 sampled builds were
  post-patch. Seven, Ivy, and Paige each had only one post-patch build in their
  top ten; Vindicta, Wraith, Lash, and Drifter had two each.

The endpoint offers no match- or game-mode parameter. The 22:20 UTC
same-filter replay found 15 Tier V Street Brawl card occurrences in three builds, covering
nine Legendary item names; 13 of the cards were optional and four carried an
imbue target. This is only 0.79% of sampled builds, and it does not affect the
ranked telemetry or managed-item selector. It does mean public-guide tactical
counts are not a pure normal-ranked sample. Keep Tier V cards as useful layout
fixtures, exclude them from normal-mode item agreement, and record a mode when
the source eventually supplies one.

The same replay resolved every one of its 15,990 card IDs against pinned client
6,679. It found 15,969 current normal Tier I–IV cards (99.87%), the 15 Street
Brawl cards above, five disabled or unavailable legacy cards across three
builds, and one unknown ID in one build. The legacy names were Spirit Armor,
Bullet Armor, Soul Rebirth, and Silencer. This is reassuringly small
contamination, but `only_latest=true` clearly does not mean every card is valid
for the current normal shop. Filter tactical agreement through the pinned
normal item universe. Retain stale IDs only as explicitly labelled API/layout
fixtures; an unknown or disabled card may not render, so it must not count as a
proven visible-capacity test card.

### Popular guides are not compact-layout exemplars

A third live replay at 2026-08-17 21:08 UTC asked whether popularity at least
selects away malformed geometry. It returned another 380 rows, with 2,708
categories and 15,989 cards. The earlier response bodies were not archived, so
individual build identity changes cannot be reconstructed. Weekly
favorite counts were still null, so this check uses the returned lifetime
favorite count only; it does not explain or reproduce the endpoint's weekly
ranking.

It found the opposite of a compactness filter. Thirty-eight of the 95 builds
in the top lifetime-favorite quartile, or 40.0%, had a category above 12 cards,
compared with 24 of 95, or 25.3%, in the bottom quartile. Controlling crudely
for hero produced the same direction: within each hero's ten rows, 66 of the
190 upper-half builds were oversized, or 34.7%, versus 47 of the 190 lower-half
builds, or 24.7%. Twenty heroes had a higher oversized rate in their upper
half, ten tied, and eight went the other way.

The association is real but small, descriptive, and not causal. Within-hero
favorite rank had Spearman 0.121 with the oversized indicator and 0.152 with
total card count. It had stronger relationships with the share of optional
categories at 0.326 and annotated cards at 0.348, while its relationship with
mean cards per category was only 0.039. Popular guides tend to contain more
teaching structure, options, and annotations, not uniformly denser panels;
having more content gives at least one panel more opportunity to overflow.

Copy the useful conventions—named phases, real optional flags, concise
annotations, and explicit choices—but do not use favorites as layout
validation. A visible-card capacity rule is still necessary precisely because
successful community builds normalize some oversized sections.

### Favorites survive build revisions

The API's primary query source shows that `only_latest=true` partitions by hero
and build ID, orders by version, and keeps the newest version. Querying a build
without that filter then revealed the missing timestamp semantics. Public build
317824 had at least versions 1507 through 1543 in retained history; each row's
publish and update timestamps moved forward while its favorite count rose from
20,418 to 20,711. Builds 317825 and 317832 showed the same monotone cumulative
counter across frequent revisions. The latter is visibly named as a Tracklock
guide, consistent with automated or service-driven updates.

Therefore a build published after a patch is a **post-patch revision**, not
necessarily a newly created guide or a proof that its tactical content handled
the patch. Lifetime favorites also do not reset at that revision. This explains
why post-August-12 rows had much higher favorite counts in the live sample:
among each hero's upper five by lifetime favorites, 79 of 190 were post-patch,
or 41.6%, versus 47 of 190, or 24.7%, among the lower five. Active, established
authors appear more likely to revise their guides.

That maintenance signal is useful but incomplete. Among the 13 heroes changed
on August 12, only seven had a post-patch revision in the endpoint's first
weekly-ranked position, and only 43 of 130 sampled rows were post-patch. Treat
revision time as a freshness prerequisite, then compare the exact archived
item layout and ability order against the changed hero mechanics. Neither the
favorite counter nor a bumped version proves that review occurred.

These limits reinforce the role of the sample: it shows what the current client
can encode and what successful authors tend to expose. It is not a tactical
vote count or a stable leaderboard archive. A reproducible future audit should
save a deidentified response hash and aggregate summary at collection time.

### Match telemetry sees many builds but not one dominant guide

The current source carries `hero_build_id`, which the
[API contract][deadlock-openapi] defines as the first build selected when the
match started; it does not reflect a later build change. A research-only repeat
over the same 169,201 currently eligible rows found:

| Initial build ID class | Hero-player rows | Share |
| --- | ---: | ---: |
| Zero or unset | 122,120 | 72.2% |
| Local/private range, `1-999` | 11,631 | 6.9% |
| Published range, `1000+` | 35,450 | 20.9% |

The published rows referenced 3,473 distinct build IDs. By hero, published-ID
use ranged from 17.6% to 23.2%, with a 20.8% median. Even within players who
started on a published build, the most-used ID for a hero usually was not
dominant: its share had a median of 18.2%, ranging from 10.5% to 42.0%. This
supports browsing a balanced set of guides instead of treating one top build
as the community answer.

These classes have strict limits. Zero may mean default, unavailable, or no
selected custom guide. IDs below 1,000 are account-local and collide across
players; the managed private builds belong to that range, so their use cannot
be aggregated by number. A published ID records selection, not Queue Build,
item purchases, attention to optional rows, or the exact build revision shown
at match time. The repeated query also contains the late backfill described
below and is not current-artifact evidence.

A useful future study would archive a published build's exact version at match
start, then compare its stated Queue path and options with observed buys,
sells, and build switching. Measure route adherence, where players diverge,
and whether clipped or overlarge categories are abandoned. Do not rank guides
by the selecting players' raw win rates: guide choice, author popularity,
player skill, patch age, hero, and match context are all confounded.

### Managed CORE versus current community menus

A fresh 2026-08-17 17:52 UTC pull applied the same top-ten-per-hero filters and
compared each public menu with this project's eight final targets. It returned
all 380 expected builds. Across individual public builds:

- the median build displayed six of the eight managed targets anywhere in its
  menus; the mean was 5.69, the 10th percentile three, and the 90th percentile
  all eight;
- 86 builds (22.6%) displayed all eight, while 227 (59.7%) displayed at least
  six; and
- restricting the comparison to structurally non-optional panels reduced the
  median to five and the mean to 4.53 targets.

Looking from the target side, the median managed target appeared in eight of
its hero's ten sampled builds. One hundred sixty-three of 304 targets (53.6%)
appeared in at least eight builds, 18 (5.9%) appeared in two or fewer, and 42
appeared in all ten. Pocket and Shiv had a median eight-of-eight overlap per
public build. Bebop and Silver had the lowest median at 3.5 targets.

The weak tail is a useful review list. Silver's selected Tankbuster appeared in
none of its ten sampled builds. Ivy's Decay and Torment Pulse, Rem's Arcane
Surge and Opening Rounds, Warden's Intensifying Magazine, and Yamato's Bullet
Resist Shredder appeared once each. These are not automatic removals: public
authors may lag the patch, copy one another, or place a valid item outside a
top-ten sample. They are specific disagreements to explain with current match
support, timing, hero mechanics, and a later-patch slice.

Community frequency and local match adoption nevertheless agree more than
chance-looking noise would suggest: their rank correlation across the 304
managed targets was 0.606. Targets shown in zero to two public builds had a
19.2% median local adoption rate; the medians were 40.9% for three to five,
54.7% for six or seven, and 69.8% for eight to ten. Do not attach a conventional
independence p-value to this comparison because copied builds share authors and
ideas.

The outliers are more informative than the aggregate. Warden's Kinetic Dash
appeared in only two sampled builds despite 70.6% local adoption; Lash's Bullet
Resist Shredder appeared in two despite 44.6%. Those disagreements may reflect
a new patch, a guide convention, or a difference between an item people buy and
one authors consider defining. Community frequency had small positive
correlations with displayed target position (0.205) and median purchase time
(0.243), so agreement is not simply “everyone lists the same lane starter.”

Same-patch public builds agreed more closely. The moving sample contained 122
builds published at or after the August 12 patch and 258 older ones. Newer
builds displayed a mean 6.20 managed targets and a median seven; older builds
displayed a mean 5.45 and a median six. The pattern was similar for the 13
heroes changed by the patch (6.24 versus 5.32) and the other heroes (6.18
versus 5.51), so hero patch notes alone do not explain it. Recency, author
behavior, copying, and ranking exposure are all confounded here. Treat the
direction as reassuring convergence, not proof that the managed ending is
better. McGinnis is a notable exception: its eight post-patch builds averaged
4.63 targets versus six in its two older builds, consistent with the split
ending patterns found in match data.

This comparison is deliberately recall, not Jaccard similarity. Public menus
contain a median 42 cards and mix Queue paths with options, so their union
is much larger than an eight-item ending. The five-target non-optional median
also inherits the inconsistent optional flags documented below. Even with
those limits, broad agreement is useful independent evidence that the managed
selector usually reflects recognizable hero build vocabulary rather than an
alien statistical artifact.

Public card order supports the same “broad order, not exact route” conclusion
as the match replay. Among 364 builds containing at least two managed targets,
the median pairwise agreement with the managed target order was 80%. Restricting
the flattening to structurally non-optional panels raised it to 90% across 344
builds. Yet only three of the 86 public builds containing all eight targets put
those targets in the exact managed relative order; the non-optional comparison
was two of 33.

Category order, options, duplicates, and reference panels mean this is not a
literal Quickbuy replay. It is independent design evidence that
early-versus-late relationships are often recognizable while one exact
eight-item permutation is not. Kelvin's median pairwise agreement was 63.6%
across all panels and 70.0% in non-optional panels, despite the strong
item-presence agreement described below. High pairwise scores can also be based
on few shared items, so report order agreement beside recall rather than alone.

### Public ability orders agree early and branch later

The public-build `currency_changes` field is not safe to flatten blindly. In a
fresh 18:59 UTC replay, 284 of 380 builds had exactly 16 changes, nine were
shorter, and 87 were longer. After checking IDs and the four expected unlock,
one-point, two-point, and five-point spends, 366 builds had one mechanically
complete first 16-action block. Eighteen fields contained two or three clean
complete blocks back to back; another 65 began with a complete block and then
carried a partial or invalid tail. The [public response structure][build-api-struct]
does not assign a path identity to those concatenated changes, so they could be
alternate edits, stale client state, or ingestion residue. They are not 87
trustworthy extra strategies.

The first complete block still provides useful independent context. Among the
366 structurally comparable builds:

- 284, or 77.6%, matched the managed build's first ability action;
- 223, or 60.9%, matched its four-ability unlock order;
- only 11, or 3.0%, matched the entire managed 16-action order; and
- each hero's ten builds exposed a median of ten distinct first paths, with a
  range of six to ten.

Within each hero, the median majority choice was 80% at action one, 52.8% at
action two, and no more than 60% at any later action. None of the raw public
ability changes had an annotation. This is design evidence for one clear legal
default with stronger early confidence and later flexibility, not evidence for
copying a popular path or displaying ten unexplained variants. The managed
guide should make its first unlocks easy to scan, explain the few later branch
points that are mechanically meaningful, and keep state support separate from
whole-path support. Any future public-build comparison must first reject short,
invalid, and unlabelled trailing blocks.

### Choice labels are not structural metadata

A 2026-08-17 14:57 UTC replay of the same endpoint filters returned 2,704
categories instead of the original 2,707, a small reminder that even a
"latest" top-ten sample drifts while research is in progress. In that replay:

- 1,325 categories had the protobuf `optional` flag set; 1,379 did not.
- 288 names contained `optional`, `situational`, `counter`, `pick one`,
  `choose one`, or `choice`.
- Sixty-two of those choice-named categories, across 36 builds, did **not**
  have the structural flag set. Examples included plain `Optional`,
  `Situational`, `Luxury//Situational`, and `Counterpicks and Counterbuys`.
- Structurally optional categories held a median of five cards, a 90th
  percentile of 11, and a maximum of 44. Non-optional categories held a median
  of six, a 90th percentile of ten, and a maximum of 28.

The client and any validator must therefore use the serialized flag for
behavior and the label for communication. Inferring queue behavior from words
in a category title is unsafe. The managed generator should also validate the
opposite direction: a section presented to the player as an optional choice
should carry the optional flag, unless a deliberately tested client behavior
requires otherwise.

Of the original 2,707 categories, 2,673 supplied both dimensions. They
contained 2,485 distinct width and height pairs. This strongly suggests that
public authors and the client already use content-shaped layouts; one fixed
rectangle per category name is not representative.

The 2,704-category replay sharpened the malformed-geometry warning: 68
categories had a missing or non-positive width or height, including negative
outliers, and 96 had no cards. Across 15,960 cards, 5,929 had an annotation;
288 annotations used at least three lines. Categories with every card annotated
had a median positive height of 178 units, versus 159 for categories with no
annotations. This is an association across very different author layouts, not
a sizing rule. Current localization says item notes appear in the tooltip, and
the compiled card style has a fixed height, so annotation line count does not
establish visible card height. Detailed authors may simply choose larger
panels. Size managed categories from card geometry and headers, never from
note-line count.

For the 135 categories above 12 cards, the median panel was about 1,013 by 311
units. Eighty-two were at least 900 units wide. Of the 34 below 700 units wide,
19 were at least 400 units tall and 15 were both narrow and short. The two
common successful shapes appear to be a wide two-row panel or a narrower,
taller panel.

Specific medians reinforce that pattern: 13-card categories were about 1,046
by 304, 15-card categories were about 634 by 407, and 17-card categories were
about 946 by 311. Kelvin's fixed 567 by 307 panel is smaller than either common
15-card shape.

The compiled client styles provide a deliberately conservative clipping
preflight. An item card occupies an 80-by-125-unit box plus two units of margin
on each side, so a panel of width `w` can fit at most `floor(w / 84)` cards per
row and `ceil(card_count / columns)` rows need at least 129 units each. This
lower bound ignores the category header, border, and container padding; failing
it is therefore conclusive, while passing it is not. In the live
2026-08-17T21:21:26Z replay, 245 of 2,551 non-empty categories with positive
dimensions, across 155 builds, were shorter than even this card-only bound.
The median positive shortfall was 33 units and the 90th percentile was 90.
Only three of the 135 categories above 12 cards failed, because public authors
usually made those panels wider or taller. Kelvin's 15-card CORE is 567 by
307.5: six columns force three rows, whose cards alone need 387 units, leaving
a 79.5-unit shortfall before any header or padding. A hypothetical 23-unit
header allowance would raise the replay failure count to 658 categories, but
that is a sensitivity check rather than a universal constant. Client-rendered
acceptance tests remain the authority.

Public data are not a layout oracle. The sample also contained missing
dimensions, negative outliers, empty category names, and likely clipped narrow
panels. These values are useful test fixtures, not constants to copy blindly.

The most common category sizes by item count were four, six, two, three, five,
eight, and seven cards. Good public builds tend to use several smaller named
choices rather than one enormous undifferentiated menu.

A follow-up organization replay resolved the client's default localization
tokens as phase labels. Of 380 builds, 316 had an early, lane, start, or opening
panel; 210 had a mid-game panel; and 275 had a late-game or luxury panel. These
phase panels each held a median of six cards and a 90th percentile of ten. A
named CORE appeared in only 115 builds. Its median was eight cards, but its 90th
percentile was 14 and its maximum was 20. Community convention therefore
supports small phase panels, but it does not establish a safe 12-card CORE cap.

Choice-like panels held a median five cards and were structurally optional
72.1% of the time. They were not simply a footer: 238 builds, or 62.6%, placed
at least one optional category before a later non-optional category. Preserve
serialized category order in any dynamic layout; grouping every choice panel
at the bottom would change the author's teaching sequence.

Public build queue scope is also too broad to copy as the managed default.
Non-optional categories contained a median 20 cards per build, 282 builds had
more than 16, and 53 builds had a single non-optional category above 12. This
may be deliberate reference design or imperfect flag use. Either way, public
popularity is not evidence that automatically buying a 20-card route is safe.

Community organization also used recognizable game words. Category names
mentioned `early` 148 times, `core` 142 times, `late` 193 times, `lane` 105
times, `optional` 75 times, `situational` 71 times, and `counter` or `counters`
79 times. These labels are imperfect, but they are easier to scan than
statistical pipeline terms.

A fresh title-only vocabulary check found more specific patterns. Twenty
categories across 15 builds explicitly used `4.8k` or `4800`; their median was
only three cards. Names included `4.8k Gun Alternatives`, `4.8k Green (3200)`,
`4.8k Green (1600)`, and `Pick 4800 worth of items.` Thirteen builds had a
literal sell category with a five-card median, 13 used replacement or swap
titles, and 54 used `pick`, `choose`, or `choice`. Small breakpoint and choice
panels are therefore established client vocabulary, not a proposed analytics
term. Structural hygiene remains mixed: only 11 of the 20 4.8k panels and six
of the 13 sell panels were flagged optional.

The sample included 125 empty category names, 88 names longer than 50
characters, and 36 builds with at least one repeated item ID. Community builds
are therefore design references, not validation references.

A fresh 18:59 UTC replay examined those repeated IDs rather than treating them
as simple malformed rows. Thirty-seven of 380 moving builds contained a
duplicate. There were 223 repeated-item groups and 321 extra card occurrences;
216 groups, or 96.9%, crossed category boundaries, while only seven repeated
inside one category. Fifty-four crossed the optional/non-optional boundary.
Dispel Magic appeared in multiple panels in 21 builds, Counterspell in 18, and
Spirit Resilience in 15. Common patterns repeated one defensive active under
several threat headings, or repeated an early purchase in a later `SELL`
panel.

That makes a public category an overlapping teaching view, not a normalized
item partition or a trustworthy Queue segment. The managed queued CORE path
should still keep one canonical card per purchase step. If a later dynamic
design repeats an item for a counter, replacement, or sell reminder, mark that
copy as a non-purchase reference and prove in the client that it cannot enqueue
or repurchase the item. Deduplicating every public panel would erase useful
teaching structure; flattening every public card would turn the same structure
into a broken buy order.

### Kelvin sample

The ten sampled Kelvin builds contained five to ten categories and 22 to 64
cards. Examples included:

- `BEAMAXXING GIGACHAD`: 8 categories and 35 cards;
- `assersson - Frost Bomber Kelvin`: 8 categories and 47 cards;
- `Cirno's Medi-Beam`: 8 categories and 53 cards; and
- `KARRY KELVIN`: 5 categories and 44 cards, including one 19-card wide
  counter/extra category.

These builds demonstrate layout vocabulary, not tactical superiority. Their
useful patterns are named phases, explicit alternatives, hero-specific notes,
and dimensions matched to content.

The managed Kelvin target set also has broad qualitative agreement with this
small community sample. Each of its eight final items appeared in at least five
of the ten builds. Escalating Exposure and Boundless Spirit appeared in eight;
Greater Expansion appeared in nine. The clipping therefore hides three of the
most widely included targets, not obscure component trivia.

Kelvin authors used labels such as `Pick One`, `Pick Two`, `Mid Game (1 Flex
Slot)`, `Defense`, `CC Counters`, and `Stage 2: Healing items`. Their tactical
claims still require evidence, but their choice and inventory language is
immediately understandable.

## How strong MOBA builds are created

### A build is a plan plus choices

A static left-to-right list is useful for reducing mental load, especially for
new players. It becomes misleading when it pretends one sequence fits every
lane, enemy team, slot state, and soul total.

The strongest pattern across other MOBAs is:

1. Start with a small, reliable default path.
2. Observe what the player already owns.
3. Account for team lineups, lane, role, and available resources.
4. Offer a few clear alternatives rather than one silent override.
5. Recalculate after the player deviates.
6. Explain the game mechanic behind a choice.

Valve's [Dota Plus assistant][dota-plus] uses recent games by skill bracket,
shows three purchase sequences and a pool of popular items, and recalculates
from the player's current inventory. Its ability suggestions also adapt after
the player chooses a different level.

Valve's [streamlined Dota shop][dota-streamlined] adds a second useful pattern:
progressive disclosure. It starts new players with a hero-specific guided list,
reveals later choices after earlier purchases, and leaves the full shop
available when the player wants it. A Deadlock private build cannot reproduce
that interface exactly, but a small queued CORE path plus compact, deliberately
chosen option rows serves the same goal better than showing 40 optional cards
at once.

Riot's [item shop design][riot-shop] starts from current inventory and
high-level player data, then considers observed enemy damage, control, healing,
and defenses. It presents choices and leaves the decision to the player. Riot
also treats small-icon readability as a primary gameplay requirement.

Research on [sequential Dota 2 item recommendation][sequence-paper] found that
purchase order matters and that current items, team composition, and available
resources are relevant. Its result that an RNN beat a Transformer is specific
to that Dota dataset; it is not a reason to replace this project's validated
Deadlock model.

Research on [team-aware recommendations][team-paper] found value in team and
role context. That study's results also should not be transferred directly to
Deadlock without a chronological Deadlock evaluation.

### Deadlock-specific decision context

For this project, useful signals should be ordered by how directly they
describe the purchase decision:

1. Current inventory and queued purchases
2. Required lower-tier components
3. Available souls and current net worth
4. Open universal item slots and objective-unlocked Extra Slots
5. Hero ability choices and imbue target
6. Enemy heroes and their observed damage, healing, control, and defenses
7. Allied heroes and missing team needs
8. Lane state, match time, and current objective pressure
9. Patch, client version, rank range, and match mode

The current static Steam build can encode a safe default path and optional
reference menus. It cannot observe most live state. The read-only `recommend`
command is the appropriate place for live-state choices, provided its input and
output are described in player language and remain deterministic.

The slot wording matters. Valve's May 2025 [Shop Rework Update][shop-rework]
made every inventory slot universal and reduced the cap from 16 to 12. The
installed client now says `Extra Slot`, including `Required Extra Slots` in
builds; it no longer presents separate Gun, Vitality, and Spirit inventory
limits. The repository's global capacity calculation is therefore the right
shape. Player-facing state should say `extra_slots_unlocked`; retain
`flex_slots` only where the tracked protobuf or an internal compatibility
schema requires that old field name.

### Current objectives create review moments, not automatic item answers

The archived official patch feed gives a current, build-relevant objective
schedule. The June 30 [objective rework][objective-rework] separated the Urn
from Unstable Rift. Urns spawn at 10, 15, 20, 25 minutes and then every five
minutes, travel to the opposite end of the map, begin losing bounty 45 seconds
after pickup, disappear after another 45 seconds of decay, and grant the runner
souls plus four permanent buffs on delivery. Unstable Rift has a variable
start around its scheduled time, announces itself globally 25 seconds before
spawn, and shows its lane in-world 60 seconds before that announcement. The
same update reduced Guardian and Walker bounties to 1,250 and 3,500 souls.
July 9 [objective tuning][objective-tuning] then reduced the nearby-player
share of objective bounties and changed the Urn runner's movement bonuses.
The August 12 patch did not replace those general rules, although it did change
when a Walker treats a Doorman-dragged hero as a stomp target.

These facts identify moments when a player should reconsider the plan:

- an upcoming Rift can justify checking actives, mobility, and team-fight
  readiness before the announced contest;
- an available or carried Urn changes travel, fight, and cash timing;
- a Walker push can unlock the next Extra Slot and change whether another held
  item is legal; and
- objective bounty can change when the next target becomes affordable.

They do **not** prove which item to buy. The current evidence has no joined
objective state at purchase time, and `recommend` ignores its free-text
`objectives` field. Replace that field only when the producer can derive a
small current vocabulary such as `urn_available`, `urn_carried`,
`rift_warning`, `walker_push`, and `extra_slots_unlocked`. Evaluate whether
each value improves a named next-purchase task on later matches. Until then,
use objective times as player-facing review prompts, not hidden rules or
causal item claims. Record the June 30 objective rules as their own map epoch;
defaulting all four epoch identities to the latest hero balance patch is safe
but does not say when the map rule actually changed.

The objective cadence nevertheless lines up with useful **review** points in
the present build. Counting each final target whose individual median
first-ownership time had elapsed gives:

| Match time | Final-target medians elapsed | Typical hero count |
| --- | ---: | ---: |
| First Urn, 10 minutes | 60 of 304, or 19.7% | 2 of 8 |
| 15 minutes | 142 of 304, or 46.7% | 4 of 8 |
| 20 minutes | 190 of 304, or 62.5% | 5 of 8 |
| 25 minutes | 251 of 304, or 82.6% | 7 of 8 |
| 30 minutes | 294 of 304, or 96.7% | 8 of 8 |

Across heroes, the median of the latest target's individual median time was
27.6 minutes, ranging from 22.8 for Warden to 33.5 for The Doorman. These are
not eight-item completion times: every item's median comes from its own buyer
group, and the selected target order is reconstructed. They show that the
five-minute objective rhythm spans the part of a match in which the default
plan changes most. A compact guide can say “recheck choices at the next Urn,
Rift, or Extra Slot” without pretending the objective caused an item outcome.

The current source also exposes the actual Walker destruction arrays that
unlock slots. A research-only repeat over 13,885 currently complete 6v6 matches
under the same event/rank filters ordered each side's three positive
`Tier2Lane*` destruction times. The installed client says the first, second,
and third enemy Walkers unlock the three Extra Slots. The resulting timing is:

| Extra Slot | Teams reaching it by match end | Middle-half unlock time | Median |
| --- | ---: | ---: | ---: |
| First, after one enemy Walker | 96.7% | 14:46-20:29 | 17:59 |
| Second, after two enemy Walkers | 85.2% | 19:49-26:13 | 22:36 |
| Third, after all three enemy Walkers | 68.7% | 23:43-30:41 | 27:00 |

These are opportunity distributions, not timers or promises. The repeated
source has late backfill and contains 13,885 complete matches versus the
frozen extract's 12,178, so the table must not alter the current build packet.
It does show why `extra_slots_unlocked` belongs in a live recommendation: the
median first, second, and third unlocks land inside the same 18-27 minute span
where most final-target medians elapse, while a substantial share of teams
never earn the third. A static guide may say “check after the next Walker”; it
must never assume a slot exists merely because the clock passed 27 minutes.

### What `recommend` can actually change today

The decision-state schema is more ambitious than the admitted model. Purchase
history, owned items and components, open slots, unlocked Extra Slots,
active-item count, and liquid souls all affect legality or whether the answer
is `buy` versus `save`. Exact patch, client, mode, hero, and rank range protect
identity.

Several accepted fields do not yet personalize the choice:

- match clock, learned abilities, allied heroes, and objectives are parsed but
  never used after validation;
- average rank is checked against the broad cohort but does not choose a
  rank-specific model; and
- enemy heroes, enemy items, explicit threats, and active-slot pressure matter
  only through admitted situational branches. The current artifact has none.

The current contract is easier to understand as a game-state matrix:

| Game fact | Present in state file | Changes today's answer |
| --- | --- | --- |
| Purchase history | Yes | Chooses a next-new-item fallback and the completion check |
| Owned items and unlocked Extra Slots | Yes | Rejects illegal inventory or active-key combinations |
| Available souls | Yes | Changes only `buy` versus `save`, not the target item |
| Match clock | Yes | No |
| Average rank | Yes | Only accepts or rejects the broad match group |
| Learned abilities | Yes | No |
| Allied heroes | Yes | No |
| Enemy heroes and items | Yes | Only through a counter branch; none exist now |
| Named threats | Yes | Only through a counter branch; none exist now |
| Objectives | Yes | No |
| Queued purchases, lane, total net worth, and team lead | No | No |

Lane type does not justify another speculative field in this cohort. Across all
12,178 complete matches, each team had exactly three assigned lanes and exactly
two players in every lane; the only encoded lane IDs were 1, 4, and 6. There is
no solo-versus-duo variation to learn. A future lane-specific recommendation
would need a named current lane, opponent and ally context, enough repeated
support, and an explicit prediction task. Do not add an unused `solo_lane`
switch or infer a tactical role from the raw numeric lane ID.

The state contract is strict about JSON shape but permissive about several game
identities. Purchase-history IDs are not resolved against the current item
graph. The existing manual-deviation test deliberately supplies unknown item
`99`; recommendation accepts it, misses the specific transition contexts, and
silently falls back to popularity. Learned abilities and allied/enemy hero IDs
are likewise not checked against the selected hero kit and current roster.
Owned and observed enemy items are validated later because mechanics code uses
them, which makes the boundary inconsistent.

For a patch-bound state file, “off the default path” should still mean a real
current shop item. Resolve every purchase ID, hero ID, and learned ability at
admission; retain known sold items in history, and use a real off-path item in
the deviation fixture. Reject a typo as `unknown current item` instead of
changing the backoff level. Objectives also remain arbitrary free text and have
no consumer; either define current game-objective values when a model uses them
or remove the field from the required player workflow. A closed schema is only
closed when its IDs are closed too.

In particular, a 500-soul and a 50,000-soul state choose the same target if
their purchase and inventory history match; for an 800-soul target, only the
action label changes from `save` to `buy`. That is a valid narrow helper, but
not an economy-aware item planner.

A roster-wide metamorphic check made that behavior concrete. Starting from the
same empty-inventory state with enough souls, it changed clock, in-cohort rank,
learned abilities, allied heroes, enemy heroes, objectives, one known threat,
and one enemy item separately. None of the 304 hero-by-field comparisons
changed any recommendation field. Parsing context is not the same as using it;
this test should become the promotion checklist for each claimed live signal.

The manual state contract also asks for three facts deterministic code can
derive: `inventory.components`, `inventory.open_slots`, and
`inventory.active_bindings`. Validation recomputes all three from owned items,
flex unlocks, and the pinned item graph, then rejects a mismatch. That is a
useful cross-check for independent telemetry, but needless duplication for a
person-authored JSON file and another place to misuse “slot.” Either accept the
small source state and derive these values, or make independent reported values
optional and label them as cross-checks. The normal input should say owned
items, unlocked Extra Slots, and current souls; the output can explain consumed
components, empty inventory space, and active-item keys.

With an empty inventory, no purchases, Oracle-range rank, and the game's 400
starting souls, all 38 heroes return `save` for an 800-soul opening item using
the most specific first/previous/position transition context. Only 13 of those
opening item IDs match the first card in the installed CORE path. That is
explainable: `recommend` imitates common next purchases, while CORE is a legal
route toward an eight-item final inventory. It is still a product-level
contradiction unless the UI clearly says these are different jobs and explains
how an off-path lane item will later be upgraded or sold.

The stateful component expansion is incorrect for the six three-level upgrade
trees in the current shop. `_next_purchase` enumerates every transitive ancestor
and picks the first one not currently owned. If the player owns Improved Spirit,
Extra Spirit is absent because it was consumed; asking for Boundless Spirit
therefore recommends buying Extra Spirit again instead of upgrading the owned
Improved Spirit. The same failure occurs for:

| Target | Already owned | Incorrect recommendation |
| --- | --- | --- |
| Boundless Spirit | Improved Spirit | Extra Spirit |
| Transcendent Cooldown | Superior Cooldown | Compress Cooldown |
| Healing Tempo | Healing Booster | Extra Regen |
| Juggernaut | Enduring Speed | Sprint Boots |
| Divine Barrier | Guardian Ward | Grit |
| Indomitable | Reactive Barrier | Grit |

All 38 hero policies contain at least one transition to one of these targets:
1,124 stored context rows with 97,714 aggregate support, where support overlaps
across fallback levels and must not be read as unique matches. Fourteen heroes'
expanded default routes contain 16 such targets; Kelvin's Boundless Spirit is
one of them. The existing recommendation test covers only a one-level
component tree.

Traversal should stop when an owned node satisfies that prerequisite branch.
Descend only through a missing direct component; do not treat a consumed
ancestor as missing beneath an owned upgrade. Add all six real chains as a
table-driven regression plus a shared-component rebuy case, because repurchasing
is correct only after the relevant direct component was actually consumed by a
different parent.

Completion is checked too late as well. `_sequence_recommendation` always tries
the context fallbacks—including unconditional popularity rows—before the code
asks whether the component-expanded default path is complete. A roster-wide
simulation supplied every default purchase and the intended eight-item ending,
with the ninth starting slot open. Thirty-six heroes returned `buy`; only Warden
and Mirage returned `end`.

Of those 36 extra actions, 20 repurchased an item already present in purchase
history and 16 introduced an item outside the default route. Fifteen targeted
an already owned final item and recommended one of its consumed prerequisites.
Kelvin, for example, owned Greater Expansion after completing the route but was
told to buy Mystic Expansion *for Greater Expansion*. The proposed card was not
already owned, so the low-level inventory check considered the purchase legal.

Define the command's goal explicitly. If it guides the default ending, compare
the current inventory with the eight final targets before applying generic
popularity fallbacks: return `end` when all targets are owned, and repair a
missing target when one was sold. If it is meant to fill every spare slot after
CORE, call that a different optional-choice action and require a tactical
trigger. Do not silently turn one open slot into an unsupported ninth default
item. Add the 38 real completed paths as a characterization test; the current
custom END fixture removes popularity rows and therefore misses the production
control flow.

Do not call the current command matchup-aware or live-state adaptive merely
because its input file has those fields. Call it a legal next-purchase helper.
Promote each richer input only after a model uses it, a test changes the answer
when the field changes, and the output gives a plain mechanical reason.

### What not to infer

- High buyer win rate does not mean the item caused the win.
- A late purchase often selects players who were already rich.
- Ending-duration win rates are not a live power curve.
- A matchup table does not prove a particular counter item works.
- Public favorites do not measure match performance.
- A model that copies common next purchases does not prove those purchases are
  optimal.

### A clear guide shape

A player-facing Deadlock build should make these layers obvious:

1. **Queue path:** the normal purchases, in Queue order.
2. **Choose when needed:** two to four alternatives tied to visible mechanics.
3. **Later upgrades:** expensive targets that preserve component lineage.
4. **Ability order:** exact legal levels plus a short reason.
5. **Patch and sample:** when and where the recommendation came from.

The current official forum contains a community proposal for two-to-four-item
“Flex Pick” groups with a quick choice or skip action. It is not a shipped
feature, but it captures the right information design: reduce shop search while
teaching the player to choose. See the [Flex Pick proposal][flex-pick].

## Current build evidence, in plain language

### Sample definition

The installed packet was created on 2026-08-17 from:

- client version 6679;
- the 2026-08-12 minor patch;
- ranked normal matches;
- average ranks Emissary I through Eternus V;
- matches from 2026-08-12 22:57 UTC through 2026-08-15 15:05 UTC; and
- 38 active heroes.

That is a roughly 64-hour window. It gives strong freshness but limited time
coverage, and the rank band is too broad to call the result personalized.

The raw cohort contains 12,514 matches. A normal match contributes at most 12
hero-player records; the median here is 12 and the minimum after filtering is
five. Match duration had a 34.9-minute median, with the middle 80% from 28.1 to
43.8 minutes. Final net worth had a 39,525-soul median, with the middle 80%
from 27,431 to 55,239.

The retained duration range is 8.0 to 64.5 minutes. Three matches ended before
10 minutes, 17 before 15, and 87 before 20. Short matches are disproportionately
affected by the match-completeness defect below: 41 of the 87 have fewer than
12 retained players. Requiring a complete match leaves 46 of 12,178, or 0.38%,
under 20 minutes. Do not label every fast, fully scored match a remake without
a source flag. Report this tail, enforce whole-match quality first, and compare
opening-item results with and without a documented duration floor before
deciding whether any further exclusion is warranted.

Hero-player records are not the same thing as independent people. The
privacy-preserving extract retains only a per-hero distinct-account count. By
hero, unique accounts equal 35.9%-56.4% of records, with a 44.3% median; the
inverse is a median 2.26 records per unique account. The match bootstrap keeps
the 12 players in one match together, but it cannot cluster one person across
several matches after identifiers are discarded. This can make uncertainty
look narrower than it is. Keep account IDs out of durable artifacts, but
compute and retain aggregate player-clustered intervals before dropping the
temporary identity if outcome comparisons are revisited.

Requested rank range and observed rank coverage are different:

| Rank coverage | Result |
| --- | --- |
| Requested filter | Emissary I-Eternus V |
| Observed minimum | Emissary I |
| Observed median | Oracle IV |
| Observed 90th percentile | Phantom II |
| Observed maximum | Ascendant III |

The actual match mix was concentrated in the middle of that range:

| Average-rank tier | Matches | Share |
| --- | ---: | ---: |
| Emissary | 3,561 | 28.46% |
| Oracle | 6,874 | 54.93% |
| Phantom | 2,008 | 16.05% |
| Ascendant | 71 | 0.57% |
| Eternus | 0 | 0.00% |

No Eternus-average record appears in this frozen 64-hour cohort. The current
build title states the requested range, which is true, but it can be read as
actual support. Reports should show observed coverage as well.

Rank-stratified adoption is broadly stable but not interchangeable. Using the
match's average-rank tier and retaining a 20-adopter floor, the median pair of
top-ten lists shared nine items within each hero and price tier. Twenty-five of
the 152 Emissary-versus-Phantom menus shared seven or fewer cards, so the median
hides specific rank-sensitive choices. The later frozen stability table applies
its own common-support universe and reports the corresponding rank correlation
and Jaccard result.

The current broad optional menus mostly reflect the Oracle-heavy sample. After
excluding each hero's displayed CORE path, 98 of 152 Oracle top-ten menus
exactly matched the broad menu. The exact count was 64 for Emissary and only 28
for Phantom; 35 Phantom menus shared seven or fewer of the ten broad choices.
The eight final targets varied more in magnitude: the median absolute
Emissary-to-Phantom adoption difference was 8.13 percentage points, 120 of 304
targets differed by at least ten points, and 30 differed by at least 20. The
direction was mixed. Lady Geist's Kinetic Dash rose from 50.1% of 915 Emissary
records to 94.5% of 421 Phantom records, while Bebop's Mystic Burst fell from
69.9% of 1,996 to 26.7% of 1,144.

These are descriptive subgroup differences, not item effects or proof that a
rank-specific guide will improve play. Rank is the match average, the 64-hour
window may capture uneven adaptation, and retained data cannot cluster repeat
players. Keep one broad build until a subgroup ending set and route reproduce
chronologically with adequate support. In the meantime, label the guide
`broad ranked sample`, show observed rank coverage, and add per-rank adoption,
menu overlap, final-set support, and uncertainty to the review report. Never
put Eternus in a support claim when the observed group contains none.

The August 12 note was build-relevant, not merely a server fix. It contained 31
change lines across 13 heroes: Apollo, Billy, The Doorman, Drifter, Holliday,
Ivy, Lash, McGinnis, Paige, Seven, Vindicta, Vyper, and Wraith. Changes included
ability scaling, upgrade effects, cooldowns, ranges, health, regeneration,
resists, damage timing, and control duration.

Starting the match sample exactly at that patch is correct. The tradeoff is
that these 13 hero builds describe the first few days of player adaptation.
Once more data exist, compare early- and later-patch slices before treating the
first 64 hours as stable behavior. Do not solve the small window by pooling
pre-patch matches with changed mechanics.

The calendar coverage is also uneven: August 12 contributes 235 matches,
August 13 contributes 5,311, August 14 contributes 4,856, and the partial
August 15 contributes 2,112. The two complete middle days supply 81.25% of the
sample. A chronological stability check should compare equal-duration windows,
not treat these calendar dates as equally sized folds.

### Patch cadence gives “current” two meanings

Valve published 11 official patch-note posts in the 82 days from May 22 through
August 12, a median publication gap of 6.5 days and a maximum of 19 days. A
simple section-and-asset-name parse of the [official Steam News feed][steam-news-api]
found direct item or hero changes in eight of the 11 posts, including at least
154 item-change lines and 480 hero-change lines. The other three posts still
changed general play, especially repeated Urn rules. This is an actively moving
game, not a version where one build can be refreshed quarterly.

The current build roster is highly exposed to that churn. Fifty-one of its 91
distinct final items were named in those patch notes, covering 155 of 304 final
slots and at least one target in every hero build. Eighty-two of 154 distinct
option items were named, covering 745 of 1,518 option cards and again every
build. Thirty-seven of 38 active heroes had direct hero-change lines; Sinclair
was the only exception. This name-based count can miss renamed or removed
assets, so it is a lower-bound impact map rather than a semantic patch parser.

Keep whole-patch invalidation as the safe default. Add a report that maps each
changed hero, item, ability, component, and global rule to affected managed
guides so reviewers know where to look first. Shared targets deserve special
attention: Tankbuster appears in 11 final sets and was changed during this
window; Rapid Recharge appears in nine, while Restorative Locket appears in
seven and changed in two separate patch posts. An impact map accelerates
review; it must not silently exempt “unaffected” heroes from fresh telemetry.

Patch compatibility and data recency are separate. At 2026-08-17 15:27 UTC,
`status --json` called every stage `current` because client 6679 and the August
12 patch identity still matched. The evidence cutoff was 2026-08-15 15:05 UTC,
however: about 48 hours old and roughly 43% of the patch's elapsed lifetime was
then outside the sample. If Valve leaves a patch live for weeks, this same
early-patch packet remains “current” forever under the present check.

Keep the hard stale state for patch or client incompatibility. Add a different
age label such as `compatible, refresh available` after a documented in-patch
interval or after enough new eligible matches accumulate. Show patch age,
sample start, sample cutoff, and cutoff age in `status`. Refreshing should be a
deliberate deterministic evidence job; it should not quietly trigger a model
call or Steam write.

One recent title also demonstrates why timestamps need provenance: “Minor
Update - 05-25-2026” was published in the official feed on May 28. The code
uses the published timestamp as the telemetry boundary, which is conservative
but may omit several days after the named update. Keep both title date and
published time, and validate exceptional gaps rather than parsing the title as
truth.

### Outcome-filter qualification

The extraction query requires reward eligibility, a scored win or loss, a
valid team, the chosen queue, time, and average-rank range. It also retains an
`initial calibration games` flag. The current cohort contains 8,053 flagged
records, or 5.43%.

The flag is a small but measurable sample choice. Flagged records span 5,243
matches, have a median average badge of Oracle I rather than Oracle IV, a
35.8- rather than 34.9-minute median match, and a 51.52% rather than 50.53%
observed outcome rate. Removing only the flagged player records changes
supported hero-item adoption by a median 0.072 percentage points, a 95th
percentile of 0.429 points, and a maximum of 1.324 points. One hundred
forty-two of 152 hero/tier adoption top tens stay identical; the other ten
exchange one card. Among the 304 displayed final targets, the median absolute
change is 0.191 points and the maximum is 0.945.

That sensitivity did not rerun final-inventory selection, so it does not prove
all 38 target sets would remain unchanged. It does show that calibration rows
are not driving ordinary item popularity in this packet. Define whether the
flag excludes one player record or invalidates a whole match before enforcing
it: dropping every match containing one flagged player would remove a much
larger and different population.

The snapshot truthfully records `enforced_by_source=false` for the full
requested outcome policy, which also asks to exclude penalized, party-penalized,
abandoned, low-priority, and new-player records. The build-evidence artifact
does not state which of those conditions are implied by `rewards_eligible`.

Use “eligible” to mean the actual extraction predicate, not all desired flags.
Record an enforced, unavailable, or indirectly implied status for each
exclusion. This is a provenance gap, not a reason to discard the current
sample or weaken its validators.

There is also a concrete match-level filtering defect. The local cohort has
12 players in 12,178 matches, 10 or 11 retained players in 40 matches, and only
one retained team in 296 matches. The latter are 2.37% of the 12,514 match IDs
and contribute 1,773 hero-player records, 26,294 first-purchase rows, and
12,974 decision opportunities. All 1,773 retained records are winners.

A read-only check against the upstream rows explained the pattern. Each of the
296 match IDs has 12 source participants. In 247 cases the source has six
`Win`, five `NotScored`, and one `Penalized` outcomes; 46 have six wins, four
not-scored players, one penalized player, and one other excluded outcome; the
remaining three retain only five winners and have two penalized players. Thus
the row predicate removes the invalid losing side while treating the winning
side as ordinary evidence. The intended exclusions describe match quality, so
they must be evaluated before selecting individual player rows.

The effect is small for popularity but material for outcome display. Keeping
those matches raises the overall record outcome rate from exactly 50.0% among
complete matches to 50.58%. Removing them changes item adoption by a median
0.027 percentage points and at most 0.44 points; only five of 152 hero/tier
top-ten menus exchange one card. Buyer outcome rates move by a median 0.42
points, exceed a one-point shift in 364 supported hero-item cells, and move by
as much as 5.68 points.

It can also decide a close ending set. In a clean replay, Lady Geist's current
CORE and its materially different runner-up tie at 168 records and share only
five targets. The winner-only matches are what break the production tie. This
reinforces the variant finding rather than proving the alternate set is better.

Define two explicit units. For outcome, matchup, team-state, composition, and
whole-build selection, require a complete, two-team, scored match and reject
the entire match if its exclusion policy fails. If player-level eligible rows
are retained for a separate adoption-only sensitivity view, name that view and
never join it to a partial enemy composition. Record complete, partial, and
one-sided counts in every run manifest, and add a regression fixture where one
abandon makes five teammates `NotScored` so the winners cannot leak through.

This also creates feature leakage in the present outcome model. All 12,974
decision opportunities from one-sided matches are wins and lack enemy-team net
worth. The ridge pipelines median-impute missing state and add a missing-value
indicator, so “enemy team absent because its loss was excluded” becomes a
feature available to predict a win. Partial matches add 7,446 purchase rows
whose non-null lead compares teams with fewer than six observed players.
Rebuild the state, matchup, bootstrap, and situational tables after enforcing
match completeness; do not merely subtract 1,773 rows from the final report.

### The event cutoff is not a database snapshot

The cutoff is also not an event-time ceiling. The archived API schema says
`max_unix_timestamp` filters matches by **start time**, and the offline SQL uses
the same `start_time <= as_of` predicate. Once a match starts before that
boundary, its later purchases, sales, duration, final net worth, and outcome all
enter the aggregate even if they occur after `as_of`. That contradicts the
verified requirement's stronger statement that data after the cutoff must not
enter the run and makes “immutable analytics upper cutoff” easy to misread.

This retained run happened not to cross its declared 15:05 UTC boundary: its
latest included match ended at 14:13 UTC, leaving about 52 minutes of ingestion
lag. The guarantee nevertheless comes from timing luck, not the predicate. On
the same frozen rows, a hypothetical midnight cutoff on August 13, 14, or 15
would admit 140, 144, or 146 matches that ended afterward and respectively
14,138, 13,842, or 13,516 purchase events after the claimed boundary. The
furthest match end was 49.25 minutes beyond one cutoff. These are contract
probes over the frozen cohort, not claims about what the earlier database knew
at each midnight.

Choose and name one grain. If the product needs a fully observable match
sample as of a time, require `start_time + duration_s <= cutoff`, exclude every
event beyond the boundary, and record the latest admitted match end and
purchase time. If API aggregates expose only a maximum match-start filter,
label it `max_match_start_timestamp`; they cannot prove the stronger event-time
contract and should not be the sole source for a sealed replay. Add one fixture
whose match starts before and ends after the cutoff. Also record collection
time, because “known by the server by cutoff” is an ingestion-version question
that event timestamps alone cannot answer.

The local 148,338-row table is stable because the run saved its derived DuckDB
tables and Parquet exports. The upstream DuckLake is not frozen by the cohort's
`as_of` timestamp. Repeating the exact row predicate on August 17 returned
168,409 rows inside the same August 12–15 event-time window—20,071 more rows,
or a 13.5% historical backfill. `as_of` limits match start time; it does not
identify the database version that answered the query.

The online aggregate routes show the same issue on a smaller and especially
clear scale. The saved duration responses were fetched at 02:58 UTC on August
17. Repeating all seven requests at 21:50 UTC with the same patch start, rank
range, match mode, duration bounds, and `max_unix_timestamp` changed 260 of 266
hero-by-duration rows. The API added exactly 3,120 hero appearances: 1,560 wins
and 1,560 losses, or 260 complete 12-player games. The saved total was 174,228
appearances (14,519 games); the replay returned 177,348 (14,779 games), a 1.79%
increase behind an unchanged cutoff. This is direct evidence that a request
hash describes one fetched response, not a permanently reproducible API query.

The replayed response shape itself was clean. Every duration bucket contained
all 38 active heroes exactly once; all 266 rows had nonnegative counts, at
least 20 appearances, and `wins + losses == matches`. The current distribution
was 565 games under 25 minutes, 2,234 at 25–30, 4,655 at 30–35, 4,070 at 35–40,
2,157 at 40–45, 766 at 45–50, and 332 at 50 minutes or more. These checks
support the parser and the use of 12 hero appearances as an approximate game
count. They do not make the remote response immutable or turn ending-duration
groups into a live power curve.

Both matchup routes backfilled in lockstep. The same-lane replay changed 1,340
of 1,406 directed hero pairs and added 6,240 pair observations with 3,120 wins;
the whole-enemy-team replay changed 1,404 pairs and added 18,720 observations
with 9,360 wins. Those increments are exactly 24 and 72 directed pair
observations per one of the 260 added games. Both current responses still form
the complete `38 * 37 = 1,406` non-self active-hero pair set, reverse pairs
have equal match counts, and their wins are complementary. This is another
useful positive integrity check, but also another reason the response bodies or
derived rows—not only URLs and cutoffs—must be preserved.

A pinned-asset control behaved differently, as it should. Re-fetching client
6,679's items, active heroes, build tags, and ranks produced byte counts and
SHA-256 values identical to all four saved manifest records. The 5,771,301-byte
item body and 971,345-byte hero body were exact matches, not only semantically
similar JSON. This supports the client-version asset boundary. The backfill
finding applies to mutable analytics behind a time filter; it is not evidence
that every remote route is unstable.

The upstream catalog exposed 41 DuckLake snapshots numbered 0 through 40, but
all belonged to one August 17 rebuild spanning roughly seven seconds. It did
not retain the August 15 state used by this run. Record the attached DuckLake
snapshot ID and timestamp as provenance, but do not mistake that metadata for a
durable replay source. Preserve the deidentified extracted tables and their
hashes—as this run does—or archive the exact filtered source rows when the
extraction itself must be reproducible.

This is consistent with, but not guaranteed by, the storage format. The
[official DuckLake time-travel documentation][ducklake-time-travel] says each
retained snapshot is a consistent queryable state and can be selected by ID or
time; it also says historical snapshots may be explicitly deleted during
compaction. A numeric snapshot ID is reproducible only while that snapshot and
its data files remain available in the upstream system.

A source-shape probe on the later backfill found all telemetry timestamp and
net-worth arrays length-aligned, sorted, unique, and non-null. Item arrays were
also length-aligned, but 34,683 of 168,409 rows were not stored in purchase-time
order. The extractor's explicit `ORDER BY buy_time, item_id` is therefore
necessary, while the numeric-ID tie limitation remains. Turn both assumptions
into extraction counters: fail on misaligned state arrays, record unsorted item
arrays as normalized input, and separately count unresolved same-second ties.

### Volume and selection

| Metric | Result |
| --- | ---: |
| Eligible hero-player records | 148,338 |
| Records per hero, minimum | 1,804 |
| Records per hero, median | 3,576 |
| Records per hero, maximum | 7,658 |
| Qualifying purchase rows | 2,520,982 |
| Rows in supported hero-item summaries | 2,509,204 |
| Hero-item rows | 3,767 |
| Unique purchased item IDs | 156 |
| Item mechanics exported for prose | 154 |
| Final CORE items per hero | 8 |
| Optional cards per tier | 9-10; 150 of 152 menus have 10 |
| Minimum support for a selected item | 20 records |

Pocket's Tier III menu and Mina's Tier I menu contain nine cards; every other
hero/tier menu contains ten. Treat ten as a selection cap, not a guaranteed
shape, and preserve the actual count in layout tests.

The 11,778-row difference is expected: hero-item cells below the 20-record
support gate remain in the frozen extract but do not become summary rows.

The 156-versus-154 item count is also explainable, not a broken asset join.
Armor Piercing Rounds appeared in 842 purchase rows across 30 heroes and Shadow
Weave in 719 rows across 30 heroes, but neither item was selected into any
managed CORE or optional menu. The strategy context exports mechanics only for
cards the model may explain, so those two stay in the frozen analytics without
inflating the narrative packet. Preserve this as an explicit set-difference
check; an actually selected item missing mechanics must still fail closed.

The asset snapshot also contains 17 enabled rows with `shopable=true` labelled
Tier V, plus six disabled or unavailable rows at that tier. All cost 9,999
souls and use names such as Omnicharge Signet, Seraphim Wings, and Mystical
Piano. They are Street Brawl **Legendary** items, not choices in the standard ranked shop:
current forum reports explicitly describe receiving these items during Street
Brawl and users separately propose adding them to the normal mode.
Filtering the production item universe to Tiers I–IV is therefore correct for
this ranked cohort. The raw asset rows do not carry a useful `game_mode` value,
so preserve the tier rule and document it as a mode boundary rather than
assuming `shopable=true` means “available in ranked.” If standard mode later
adds Legendary items, the current hard-coded four-tier contract will need an
intentional schema and guide-design change rather than silently absorbing them.

The normal shop is broad relative to one readable guide. It contains 156 items:
23 Tier I, 43 Tier II, 46 Tier III, and 44 Tier IV; 53 are Weapon, 54 are
Vitality, and 49 are Spirit items. Forty-four are active items and 64 direct
component edges connect the upgrade graph. A managed hero currently shows 49
to 57 unique cards across CORE and optional menus, with a median of 52.5, or
33.7% of the normal shop. Across all 38 heroes, the guides collectively show
154 of 156 normal items. This is useful coverage, but it is not a reason to
make each hero menu exhaustive. Search and the base shop remain the escape
hatch; the guide should optimize for a small, understandable plan.

Price tier and purchase phase are related but not interchangeable. Restricting
to the 12,178 complete matches gives these first-purchase times:

| Shop tier | Purchase records | Middle time | Middle 80% | Before 3m | At 30m+ |
| --- | ---: | ---: | ---: | ---: | ---: |
| Tier I | 652,839 | 5.6m | 1.1-17.3m | 28.7% | 1.5% |
| Tier II | 814,638 | 13.0m | 5.6-26.5m | 1.0% | 5.5% |
| Tier III | 638,728 | 20.2m | 11.0-31.1m | 0.0% | 12.3% |
| Tier IV | 380,467 | 29.4m | 21.0-39.5m | 0.0% | 46.9% |

The progression is real enough to make tier useful shop vocabulary, but the
wide overlap is why `TIER III` cannot be translated to one exact game phase.
These are purchase records, not independent players, and describe the frozen
ranked sample rather than a rule for when a player must buy.

An independent current-client check supports the asset boundary. SteamTracking's
extracted `abilities.vdata` last changed in its client-6677 commit on August 12;
the pinned API bundle and installed client are 6679, with no later tracked
change to that file. Every one of the API's 156 standard-shop class names had a
top-level client-data record. After normalizing the internal `WeaponMod`,
`Armor`, and `Tech` enums to Weapon, Vitality, and Spirit, there were zero
mismatches in item tier, investment track, or direct component list. All 526
item-upgrade property/bonus pairs matched too. Of 2,902 API base-property
values, 2,818 had a directly stored `m_strValue` in the client record and all
2,818 matched; the other 84 use an omitted, inherited, or resolved default and
were not counted as an independent value match.

That check includes Escalating Exposure, Boundless Spirit, and Greater
Expansion. It materially reduces the chance that their names, tiers,
components, or exported numeric mechanics are an API-lag artifact. It is not a
Valve compatibility guarantee: SteamTracking and Deadlock API are both
reverse-engineered views of client data, and the comparison did not prove every
localized sentence or resolved default. Pin the [SteamTracking client-data
commit][game-tracking-deadlock-6677] as an optional conformance input and rerun
the same field comparison whenever the selected client version changes.

### Purchase-state completeness

The frozen purchase table exposes several useful quality checks:

| Check | Result |
| --- | ---: |
| Rows with a last-observed pre-purchase net worth | 2,322,844, or 92.14% |
| Rows with non-null team net-worth lead | 2,298,948, or 91.19% |
| Rows with complete six-versus-six team state | 2,291,502, or 90.90% |
| Purchases before three minutes | 198,138, or 7.86% |
| Rows with a nonzero removal time (`sold_time`) | 921,097, or 36.54% |
| Rows with a positive imbued ability | 210,040, or 8.33% |
| Purchases timestamped after match end | 5 |

Primary keys are otherwise clean. There are no duplicate match/player-slot
rows, duplicate hero picks within a match, duplicate match-fold IDs, exact
duplicate purchase records, or duplicate purchase `event_order` values within
a player. Start time, duration, and average badge are each internally constant
within every retained match, and the outcome flag is constant within each
retained team. Player slots are exactly 1-12, team IDs are 0 and 1, and the
only assigned lane IDs are 1, 4, and 6. The tiny team and lane count imbalances
come from the row-level admission defect above, not duplicate ingestion.
Repair the whole-match predicate and event replay; do not add a broad
deduplication pass that might erase legitimate source events.

Imbue telemetry is also internally clean. Every purchase of the nine standard
shop items whose current asset requires an ability target carries a positive
target; no other item does. All 210,040 targets resolve to one of that player's
four supplied hero abilities. This supports using the field for descriptive
target consensus later in the report, while saying nothing about which target
causes a better result.

The non-null wealth values are not observations at the purchase second.
`own_net_worth_at_buy` takes the last periodic stats point whose timestamp is
no later than the buy, then discards that observation timestamp. Across the
2,322,844 covered rows, the point was a mean 118 seconds and median 110 seconds
old; the 90th and 99th percentiles were 236 and 293 seconds, and the maximum
was 299. Only 638,911 covered rows, or 27.5%, were within one minute. When both
teams had state, their chosen snapshot timestamps matched exactly, so the team
lead compares the same instant; it remains a lagged lead rather than the lead
at the shop decision.

Rename exported fields to `last_observed_net_worth_before_buy` and
`last_observed_team_lead`, and retain `state_observed_at_s` plus
`state_age_s`. Purchase-window prose must disclose that cadence, use broad
bands, and never imply the player had that exact balance when buying. A model
can either carry the age as part of its feature contract or reject observations
older than a predeclared limit. Do not interpolate from the next stats point:
that would use information unavailable at the decision. Refit and recheck the
ranker after changing the field contract because both wealth features enter
its rows.

All 198,138 opening purchases have last-observed pre-purchase net worth marked
unavailable. This confirms the extractor no longer substitutes ending net
worth when no earlier state snapshot exists. Opening guidance must use order,
time, and item cost rather than inventing a soul-state estimate.

Four of the 148,338 eligible hero-player rows have no item record at all. All
four are losses; their matches lasted 10.2 to 30.4 minutes and their final net
worth ranged from 3,547 to 14,762 souls. Two hundred seventy-three rows have
fewer than eight recorded purchases. Four otherwise complete 12-player matches
contain a zero-purchase player, and 93 contain at least one player below eight.
These may mix genuine no-shop or disconnected play with incomplete item
telemetry; the retained fields cannot distinguish those explanations. Record a
purchase-history state (`present`, `empty`, or source-missing`) and show a
sensitivity before changing adoption denominators. Silently dropping empty
histories would inflate adoption, while silently treating missing telemetry as
“bought nothing” would depress it.

Every supported hero-item cell has exactly one purchase row per player-match
adopter; event inflation is 1.0 throughout this snapshot. The extract therefore
cannot measure repeated buy-sell-rebuy loops from observed rows, even though the
deterministic item scheduler can validate a required rebuy. Do not train or
describe a repeat-purchase habit from this cohort.

A nonzero `sold_time` is not automatically a discretionary sale. Matching the
removed item's class to a parent bought at the same second explains 756,585
rows, or 82.14% of removals, as direct component consumption. Another 49,144
items have their own buy and removal time in the same second, which commonly
occurs in a rapid upgrade chain. Golden Goose Egg is a separate mechanic: its
description says the player hatches it for souls and permanent buffs, so its
96.2% apparent “sale” share is mostly item activation, not a slot decision.

After direct component consumption, 164,512 rows remain—6.53% of all purchase
rows—as an *upper bound* for discretionary replacement. Frequent residual
removals include Restorative Shot (71.4% of buyers), Rebuttal (46.2%), Melee
Lifesteal (41.9%), Healing Rite (39.1%), Extra Regen (30.8%), and Monster
Rounds (30.7%). Those roster-wide associations are useful candidates for
research, not safe Quickbuy instructions. First classify graph consumption
and item-defined self-removal, then condition a residual removal on hero,
phase, inventory fullness, and the item bought at that moment. Call the raw
field `removal_time` in analysis language unless an event reason proves a sale.

The five after-end purchase timestamps are only 0.0002% of rows, and four
removal times also fall after match end. Count and quarantine both rather than
silently entering a model.

The final-inventory replay mishandles one removal case. It represents removal
as event type zero and purchase as type one, then tuple-sorts the timeline.
When an item's buy and removal share a second, removal runs first; a later buy
can leave an item that the source marks removed. There are 49,144 such rows.
After component processing, the current replay still retains 27,919 removed
items in 24,986 of 148,334 purchase-bearing player records, or 16.84%. Sprint
Boots accounts for 6,173, Extra Spirit 4,127, Extra Stamina 3,721, Grit 3,159,
and Duration Extender 2,410.

The bad postcondition is visible without knowing Valve's within-second event
order. Current reconstruction produces 11,291 normal-mode ending inventories
above the 12-slot maximum and a maximum of 16. Replaying all buys at a timestamp
and then applying explicit removals reduces the mean ending size from 10.96 to
10.77, caps every ending at 12, and leaves no source-marked removed item owned.
The selected eight-item CORE remains unchanged for all 38 heroes in both an
isolated correction and a combined correction-plus-complete-match sensitivity
run. Support still falls for 23 selected sets by a median of one record and a
maximum of four; McGinnis's 68-67 lead becomes a 67-67 tie.

Treat that robustness result as containment, not permission to keep the bug.
Final-state replay needs an explicit postcondition: an item with a nonzero
in-match removal and no later rebuy cannot remain owned. Preserve a real source
sequence if one exists; otherwise make explicit removal win an equal-time tie.
Test both numeric-ID orders for a component and parent, a same-second slot
replacement, self-removal, and the 12-slot ceiling before recomputing evidence.

The method selects an eight-item final set under the hero's median ending net
worth. It prefers sets seen together more often, then sorts targets using each
item's separate median purchase time. Outcome rate is explicitly excluded from
selection and order.

The strongest selected eight-item set was still uncommon for many heroes:

| Share appearing with all eight target items | Result |
| --- | ---: |
| Minimum hero | 1.30% |
| Median hero | 4.73% |
| Maximum hero | 21.20% |

Therefore “CORE” means the strongest supported target set under this method.
It does not mean most players completed exactly those eight items.

The eight target items cost 17,600 to 36,800 souls. The median target cost was
24,000 souls, or 63.0% of the hero group's median final net worth. The most
expensive relative case was The Doorman: 36,800 souls, or 92.0% of median final
net worth. A target can pass the budget rule and still leave little room for a
different lane start or a defensive detour.

Individual target items were well represented: adoption ranged from 10.9% to
98.7%, with a 59.1% median. Joint completion is much rarer because all eight
must occur in the same final inventory.

The advertised 64-candidate limit is applied at the wrong boundary. The
producer first keeps the 64 highest-support, in-budget ending sets and only
then removes sets whose expanded Queue would repeat a component card. Nineteen
of 38 heroes lose at least one candidate at that second step, and 348 of 1,216
examined candidates are removed. Vindicta retains only six candidates, Bebop
nine, Haze 12, and Paradox 18. For seven heroes, the first raw ending is also
unrepresentable, so the next legal ending correctly becomes the installed
choice.

Those short lists do not reflect evidence scarcity. A read-only full scan found
1,383 supported, in-budget, duplicate-free endings for Vindicta and 184 for
Bebop. Reaching the 64th representable option required scanning to raw rank 402
for Vindicta, 374 for Bebop, 234 for Haze, and 178 for Paradox. The 64th options
still had support of 86, 27, 65, and 79 player records respectively, all above
the configured 20-record floor.

The filtered endings are not necessarily illegal final inventories. Many need
the same cheap component twice because two final upgrades consume it; examples
repeat Rapid Rounds, High-Velocity Rounds, or Sprint Boots. The project's live
review already established that a duplicate component card is not an acceptable
static Queue representation, so this is a **Queue representability** filter,
not an inventory-legality claim. Apply it while streaming ranked endings and
stop only after 64 representable candidates pass. Correcting final-inventory
replay will remove false component-plus-parent endings, but real shared-component
rebuys remain possible and must retain this explicit product rule. Add a
filter-heavy regression where the 64th valid candidate occurs well after raw
rank 64.

### Several heroes have two different supported endings

The selector always takes the first legal eight-item candidate, but that first
place is often narrow. The runner-up ending set has a median 93.3% as many
supporting records as the winner. It is within 95% for 16 heroes, within 90%
for 24, and within 80% for 35. Twenty-eight runner-ups differ by only one item,
so many are ordinary flex choices. The other ten share six or fewer of the
eight targets and may represent a genuinely different way to build the hero.

Seven heroes combine a runner-up within 90% of first place with five or fewer
shared items: Lady Geist, McGinnis, Haze, Holliday, Calico, Grey Talon, and
Silver. A raw final-inventory replay found zero player-record overlap between
the first and second candidate cohorts for six of them; Holliday had only one
record in both. McGinnis is the clearest split: its top two sets have support
68 versus 67 but share only Intensifying Magazine. One ending is built around
Rapid Recharge, Healing Tempo, Heroic Aura, and Escalating Exposure; the other
leans into Battle Vest, Berserker, Escalating Resilience, Fleetfoot, Mercurial
Magnum, and Swift Striker. Calling either one *the* McGinnis build discards a
nearly equal, materially different player pattern.

Haze and Silver have exactly tied first and second support with only three and
four shared items, respectively. The producer breaks an equal support count by
the numeric item-ID tuple, so the selected default in those cases is a stable
computer tie-break, not a stronger game conclusion. Billy also has a tie, but
its two sets share seven items and are better presented as one flex choice.

Near ties can also separate a normal finish from a luxury finish. Grey Talon's
selected set leads only 123 records to 120, costs 32,000 versus 25,600 souls,
and comes from games with a 39.8-minute median and 46,897 median final net
worth. The runner-up cohort ended at 35.0 minutes and 39,740 net worth. For
Holliday the selected set leads 165 to 160, costs 28,800 versus 22,400, and its
cohort ended at 38.1 minutes and 47,005 net worth versus 35.4 minutes and
37,505. Their buyer win-rate gaps are also large, but remain the familiar
survival/economy association, not proof that the dearer ending causes wins.
The present cost check only asks whether a candidate is below the hero-wide
median ending net worth. It does not ask whether the set is a reachable default
in ordinary 25-35 minute games.

Candidate supports are not generally exclusive: a final inventory with more
than eight slots can contain two similar eight-item subsets. The raw cohort
overlap check above is therefore essential. Do not emit two variants from the
ranked candidate list alone. First cluster actual final inventories, require
chronological held-out support and distinct mechanics, then use recognizable
labels such as `Turret / Support` and `Weapon` rather than `variant A/B`. If a
split does not reproduce, keep one default and expose the disputed items in a
small choice panel. Score default reachability at named time and soul cutoffs,
then put genuinely late completions under `LUXURY` rather than allowing a
five-record lead to decide the whole build.

### The displayed CORE is a reconstructed route

The frozen raw purchase table allows a stronger distinction between inventory
support and route support. Across all heroes, 8,220 player records ended with
their hero's selected eight targets. For the median hero, only three of those
records bought the eight target items in the displayed target order. The
median exact-order share was 2.1%; six heroes had zero exact examples. Drifter
was the high outlier at 57.7%, while 15 heroes were below 1.5%.

The order is still useful. Within the same joint-support records, the median
player agreed with 89.3% of the displayed pairwise item order. That means most
item pairs are in a plausible early-versus-late relationship even when the
whole eight-item permutation differs. The marginal last-target purchase time
ranged from 22.8 to 33.5 minutes by hero, with a 27.6-minute median; seven
heroes were above 30 minutes and none above 35. These are eight separate item
medians, not one player's route clock.

Exact-prefix support falls much faster than pairwise agreement. Within each
hero's joint-ending-set records, the displayed first target had a median 87.3%
share and the first two had 57.2%. The medians fell to 21.3% for three targets,
11.8% for four, and 2.1% for all eight. Only 21 of 38 heroes had majority
support for the first two. Celeste's displayed first target was first in 6.7%
of its joint records and Graves's in 9.2%, while both still passed all current
route validators. Add per-hero target-prefix support to review; do not declare
a universal two-item opening phase.

Component expansion makes the exact-route claim weaker. Treating unrelated
detours as allowed and asking only whether the 9-17 displayed CORE cards occur
in order, the full expanded path appeared in 31 of the 8,220 joint-support
records. Thirty-two heroes had zero examples. Another 22 examples appeared in
records that later ended with a different inventory. Legal component replay
therefore proves the queue can work, not that the queue is an observed common
path.

The card annotations expose a smaller version of the same mismatch. Twenty-one
adjacent steps across 17 hero routes move backward in their separate median
purchase times; five move backward in median last-observed pre-purchase net
worth. The median
time reversal is only 29 seconds, but eight exceed one minute and four exceed
two minutes. Paradox's Long Range precedes High-Velocity Rounds even though
their marginal medians are 531 versus 218 seconds; Haze's Active Reload
precedes Extra Spirit at 427 versus 157. These are not impossible schedules.
They arise because each median describes a different adopter population, while
component scheduling and a coherent ending set impose one legal order. The
guide should not make neighboring `PURCHASE WINDOW` labels look like timestamps
from one typical run. Phase bands tolerate this honest overlap better than a
precise-looking single queue.

Rename `item_ids_in_observed_acquisition_order` in player-facing and exported
language to something like `targets_sorted_by_typical_purchase_time`. Describe
CORE as a “supported ending set with a reconstructed default route.” Evaluate
target-order and component-path support separately from final-set support, and
show broad early/mid/late phases when exact permutations fragment. This is the
item equivalent of the ability-order evidence issue below.

### Roster outliers worth reviewing

The aggregates hide materially different failure modes:

- Victor had the most coherent final set: 21.20% of eligible records contained
  all eight items. Rem was lowest at 1.30%, followed by Bebop at 1.37% and Paige
  at 1.74%. Low joint share may indicate several valid play styles, an
  over-specific target, or simply incomplete games; it is not automatically a
  bad build.
- The Doorman's eight targets cost 92.0% of median ending net worth. Dynamo was
  next at 83.1%, Grey Talon at 82.3%, and Viscous at 78.8%. These builds have
  the least budget room for a lane recovery item, counter, or alternate active.
- Viscous had the largest expanded CORE path at 17 cards. Holliday, Paige, and
  The Doorman had 16; Kelvin, Sinclair, and Vindicta had 15. The clipping issue
  is therefore concentrated enough to regression-test but too broad for a
  Kelvin-only exception.
- Wraith's selected final ability branch retained 26.9% of all valid ability
  appearances, while Lady Geist retained 3.1%, Yamato 3.3%, and Abrams 3.7%.
  This ratio measures how quickly observations split across legal choices. It
  should control claim strength, not whether the legal default is rendered.

The largest observed early-to-late outcome shifts were also hero-specific:

| Hero | Under 30 minutes | 45 minutes or more | Difference |
| --- | ---: | ---: | ---: |
| Haze | 42.9% of 1,208 | 54.5% of 506 | +11.66 points |
| Victor | 45.9% of 710 | 55.1% of 265 | +9.18 points |
| The Doorman | 43.1% of 394 | 51.7% of 259 | +8.59 points |
| Vyper | 58.8% of 699 | 43.2% of 192 | -15.57 points |
| Warden | 55.2% of 601 | 45.3% of 203 | -9.92 points |
| Celeste | 60.0% of 825 | 50.5% of 297 | -9.49 points |

These are descriptive match-duration slices. Match length is partly an outcome
of how a match unfolded, and the groups may contain different players and game
states. Use them to frame a hero's usual closing window, never to claim that
waiting longer causes a particular result.

The phase labeler also needs an uncertainty state. It requires 50 observations
per broad phase and classifies shape from fixed one- and two-point differences,
but it calculates no interval for the strongest-versus-weakest contrast. A
simple independent two-proportion 95% screening interval excluded zero for only
15 of 38 heroes; it included zero for the other 23. This screen does not cluster
repeat players and can therefore be too optimistic, so it is a lower bar than a
production claim, not the final method.

Three heroes are already classified `STABLE`: Dynamo's strongest-to-weakest
spread is 1.19 points, Viscous's 1.28, and Holliday's 1.30. Nevertheless, the
packet always names a strongest and weakest phase, and the reviewed Dynamo and
Holliday plans turn the arbitrary top point estimate into early-conversion
language. Preserve the raw ordering in audit data, but emit `NO CLEAR PHASE
DIFFERENCE` to the player when the stable rule fires or the phase-contrast
interval crosses zero. Add support and an interval to the profile, validate the
shape as well as copied labels, and reserve phase-specific advice for a
supported descriptive contrast. It must still never become “stall until late.”

### Purchase-order model

The read-only next-purchase helper uses deterministic fallback rules rather
than the XGBoost challenger. The existing offline accuracy table, however,
evaluates a simpler previous-item transition model. It does not execute the
shipped cascade of first item + previous item + purchase position, fallback
levels, component expansion, and inventory legality.

| Metric | Result |
| --- | ---: |
| Stored purchase-order rules | 33,821 |
| Rules per hero, minimum | 404 |
| Rules per hero, median | 843 |
| Rules per hero, maximum | 1,654 |
| Chronological test transitions | 477,068 |
| Previous-item model: correct first suggestion | 23.6% |
| Previous-item model: correct item in first three | 43.3% |
| Previous-item model: correct item in first five | 54.4% |
| Previous-item model: test target covered | 95.6% |

A read-only replay of the actual stored rule cascade on the same frozen test
fold produced a different, more relevant characterization. It matched each
held-out history against the first available rule level exactly as
`_candidate_rows()` does, while deliberately stopping before component and
inventory legality:

| Stored rule-cascade measure | All 477,068 transitions | 393,151 unambiguous transitions |
| --- | ---: | ---: |
| Observed target present in chosen rule level | 63.8% | 64.7% |
| Observed target ranked first | 25.7% | 26.8% |
| Observed target in first three | 39.5% | 40.5% |
| Observed target in first five | 45.4% | 46.4% |
| Mean reciprocal rank | 0.348 | 0.359 |

The unambiguous subset requires both adjacent timestamp buckets to contain one
item, so numeric item-ID tie ordering cannot decide either endpoint. Across all
506,776 held-out actions including openings, the cascade chose the most
specific first-item + previous-item + position level 207,429 times (40.9%),
previous item + position 95,541 times (18.9%), position alone 199,172 times
(39.3%), and unconditional popularity 4,634 times (0.9%).

The cascade gains about two top-one points over the simpler previous-item
model, but loses 31.8 target-coverage points and nine top-five points. Once a
specific level has any supported candidates, it never backs off merely because
the held-out target is absent—which is correct at prediction time, when the
target is unknown, but makes the earlier 95.6% coverage number inapplicable to
the shipped rule list. The actual command emits only the first legal action, so
top-three and top-five remain diagnostic list measures, not user-visible
accuracy. A final end-to-end evaluation must also replay inventory, components,
sales, affordability, completion, and abstention.

These metrics do not validate the static CORE queue. The stored transition
rules power `recommend`, while `component_expanded_default_path` is built by
sorting the selected targets with marginal soul and time medians and then
scheduling prerequisites. Calling both objects a `sequence_policy` hides two
different jobs. Name and evaluate them separately: `next_purchase_rules` for
stateful imitation and `default_core_route` for the Steam queue. The latter
needs the route-support measurements above, not next-item top-five accuracy.
Add an end-to-end held-out evaluation of the exact `recommend` cascade before
publishing an accuracy claim for that command. Report rule level, abstention,
legality rejection, intended target accuracy, actionable prerequisite accuracy,
and completed-build behavior separately.

Even `next_purchase_rules` is too broad a name for the observed target. Every
row in both `purchases` and `first_purchases` is unique by player and item, and
every `item_purchase_ordinal` is one. The source packet therefore describes the
next **first-time item ID**, not every shop transaction. It cannot teach a
sell-and-rebuy loop or distinguish a repeated consumable-style purchase. Call
the metric `next_new_item_accuracy` until an event source preserves repeats,
and do not present it as complete Quickbuy behavior.

The next-purchase order is not fully observed at one-second resolution.
There are 144,039 player/time groups containing two to five purchases, covering
293,486 events and 61.3% of hero-player records. The sequence query sorts tied
events by numeric item ID. Those ties create 149,447 adjacent within-second
transitions, or 6.30% of all adjacent purchase transitions. Only 46,546 tie
groups, 32.3%, contain a direct component-to-upgrade relationship that supplies
a logical order; a second can otherwise contain two fast shop clicks whose
relative order is unknown.

Treat each same-second bucket as a set. Infer a component before its parent,
but exclude unrelated within-bucket permutations from top-one evaluation and
exact-route support. The next observable step can condition on the completed
bucket. At minimum, report accuracy twice—with ambiguous transitions included
and excluded—so a stable numeric-ID tie-break is not mistaken for learned game
behavior.

The XGBoost state replay has a second equal-time problem. Before constructing a
purchase query it expires every owned item whose `sold_time <= buy_time`. In
the source, component removal normally has exactly the parent's purchase
second, so the component disappears before the candidate is scored. The
mechanics layer then cannot credit its price or expose it through
`owned_components`, even though `_apply_purchase` knows how to do both.

A full replay comparison found 952,725 first-time upgrade queries. Under the
current order, only 3,652 owned-component relations remain visible; processing
the timestamp as a bucket leaves 732,101 visible. In practical terms, 724,720
upgrade queries, or 76.1%, gain at least one component in the coherent replay.
The resulting `prior_spend` is overstated in 147,374 of 148,334 player records
(99.35%) by a median 5,600 souls, a 90th percentile of 9,600, and a maximum of
20,000. Across all query rows, 69.4% carry an overstatement; the known missed
component credit totals 841.5 million souls.

The ridge path is different but not clean: `prior_catalog_spend` deliberately
sums full list prices and never subtracts component credit. That proxy differs
from component-aware incremental spend on 843,831 of 1,269,153 decision rows,
or 66.49%, with a median 2,400-soul gap among affected rows. Either rename it
to make the proxy explicit and prove its value in an ablation, or replace it
with the same deterministic replay state used at runtime.

This does not change the currently installed deterministic guide, and the
XGBoost artifacts already say they are research-only. It does invalidate the
recorded promotion gate as evidence for a future promotion. Correct the bucket
replay, regenerate candidate groups, refit every hero model, and compare both
metrics and full-set support. The reported non-component score is not immune:
state after an earlier upgrade can remain wrong even when the current target is
not itself a component transition.

The evaluation subset reinforces that warning. Its `component_upgrade` flag
means only “the immediately previous purchase is one of this item's direct
components.” A component bought earlier is classified as non-component if one
unrelated purchase intervenes. In the full first-purchase table, a coherent
replay identifies 728,368 targets with an owned direct component; the flag
misses 482,647 of them, or 66.3%. Those missed upgrades make up 21.2% of the
2,274,645 rows nominally called non-component. Rename the present subset
`not_immediate_component_transition`, and use `owned_components == 0` for a
true no-component sensitivity. Report both, because immediate transitions are
still a useful measure of how much easy upgrade structure drives accuracy.

The query timestamp itself is inconsistent. `current_time_s`, own net worth,
and team lead come from the previous purchase, but `expire_sales(target_time)`
first advances the owned-item set to the later target purchase. Thus one row
can say “state at minute 12” while already removing an item that disappears at
minute 14. Across the snapshot, 874,675 queries (34.7%) expire at least one item
in this gap. They expose 917,170 removals; 85,470 happen strictly before the
target second and 831,700 at that second. The median previous-to-target gap for
affected queries is 115 seconds, the 90th percentile 249 seconds, and the
maximum 1,081 seconds.

This is future information if the task is “predict immediately after the last
purchase.” If the task is “recommend at the next shop decision,” the inventory
may be current but the clock and wealth features are stale. Pick one estimand
and one timestamp. For a live pre-purchase policy, construct every feature from
the state observable immediately before that purchase, then evaluate the same
contract at runtime. For an after-purchase next-action model, retain the earlier
state and do not apply later removals. Add a fixture with a two-minute purchase
gap and an intervening sale so mixed-time state cannot return.

An isolated single-axis sensitivity changed expiry from `<= target_time` to
`< target_time`, refit all 38 heroes on the same frozen database, and left the
repository and published artifacts untouched. This is not the final repair—it
retains the mixed-time contract and keeps unrelated same-second removals until
the next bucket—but it shows that component ordering is not harmless:

- pilot selection changed from `ndcg_depth6` to `ndcg_depth8`;
- match-bootstrap non-immediate-transition MRR lift fell from 0.1085 to 0.0882,
  an 18.7% reduction, although the current gate still passed;
- non-immediate-transition top-one accuracy fell from 35.86% to 33.09%, while
  its baseline moved from 23.53% to 23.93%; and
- 14 of 38 selected XGBoost eight-item sets changed relative to the recorded
  experiment. Viscous retained only three of eight items and Venator four;
  most other changes replaced one item.

The sensitivity still changed 22 candidates relative to the deterministic
ending. Eighteen had lower chronological test support, versus 19 in the
recorded experiment. Passing the same coarse gate after selecting a different
model and changing 14 hero sets is not reproducibility. A definitive rerun
must implement mechanics-aware buckets, align every feature to one timestamp,
and correct the subset label before any promotion decision.

A second isolated replay implemented that fuller pre-purchase contract without
changing repository code or published artifacts. For each target second it:

- set clock, phase, net worth, and team lead from the target purchase state;
- kept an owned direct component until its parent consumed it;
- applied unrelated removals before the bucket and explicit remaining removals
  after it;
- ordered components before parents inside the bucket;
- calculated component-aware prior spend; and
- called a target an upgrade whenever any direct component was owned, not only
  when that component was the immediately preceding item.

This replay also selected `ndcg_depth8` and passed the existing gate, but the
meaning of that pass changed materially:

| Held-out measure | Recorded replay | Pre-purchase replay |
| --- | ---: | ---: |
| All-query baseline MRR | 0.431 | 0.445 |
| All-query XGBoost MRR | 0.538 | 0.540 |
| All-query XGBoost lift | 0.107 | 0.095 |
| Rows called non-component | 320,992 | 247,728 |
| True non-component baseline MRR | not available | 0.394 |
| True non-component XGBoost MRR | not available | 0.456 |
| True non-component match-bootstrap lift | not available | 0.0623 |
| Bootstrap 95% interval | not comparable | 0.0613-0.0633 |

The absolute all-query ranker score is almost unchanged and remains useful for
its narrow prediction task. The smaller lift comes partly from a stronger
baseline under coherent target-time phase/state. The non-component comparison
cannot be read as a before/after performance drop: the repaired definition
removes 73,264 sampled test rows that the recorded experiment incorrectly put
in that subset, a 22.8% reduction.

The selected eight-item XGBoost set changed for 15 of 38 heroes relative to the
recorded run. Viscous again retained only three items and Venator four. Eighteen
corrected candidates had lower test-fold joint support than their deterministic
ending, the same count as the expiry-only sensitivity. Correcting state
therefore does not make next-item ranking a whole-build selector.

Normalized feature gain tells the same stability story, without establishing
causation. Mean gain assigned to `owned_components` rose from 11.6% to 16.3%
and `component_credit` from 7.1% to 9.8%; the immediate-previous-item
`direct_upgrade` proxy fell from 5.5% to 1.2%. The combined precomputed
transition/popularity scores still supplied about 46% of mean gain. A model
whose build sets and feature use move this much when state is made coherent is
research evidence, not a portable policy.

The chronological split itself is not leaking into fitting. Baseline counts
explicitly ignore non-train rows; pilot model selection and early stopping use
validation; and whole-build candidate selection uses train support plus
validation support and rank score before reporting test support. The governance
problem comes afterward: `_gate()` calculates the promotion verdict from the
test fold, and the reusable experiment command exposes that verdict on every
run. Nothing prevents an operator from changing replay, features, or thresholds
after reading it and running the same “test” again.

That is no longer hypothetical. The recorded experiment, expiry-only
sensitivity, and corrected pre-purchase replay in this audit all inspected the
same test period. It remains honest comparison data, but it is now a **spent
test set** for future model development. Keep iterative gates on validation,
write a sealed final-test manifest and one-shot result, and require later
chronological data—ideally a later patch-forward window—after a test result
influences design. The next repaired ranker cannot regain untouched status by
renaming or resampling the same rows.

The ranker artifact is not sealed either. Its `experiment_sha256` hashes only
the experiment manifest. That manifest names the source database and model
directory by absolute path, but does not hash either one; it also omits the
metrics CSV, selected-core JSON, feature-importance CSV, report, preview, and
all 38 saved model files. The retained client-6679 run has 132,323,632 bytes of
saved models, yet changing any of those bytes would leave its advertised
experiment hash unchanged. Conversely, moving an identical experiment to a
different run directory changes the hash because the absolute paths are in the
payload. `production_evidence._challenger()` copies that self-reported hash
without recomputing it or validating any result file.

The manifest records a seed and resolved device, which is useful but
insufficient. It does not record XGBoost, NumPy, Python, CUDA, driver, compiler,
or GPU identity. The environment inspected during this audit has XGBoost
3.3.0, NumPy 2.3.5, Python 3.13.9, an XGBoost CUDA 12.9 build, and an RTX 5090
on driver 610.57.04; the retained manifest cannot prove those were the versions
that produced it. One older retained experiment does not even have the device
fields. [XGBoost's own reproducibility guidance][xgboost-reproducibility] says
the software and hardware stack must remain the same because versions,
resources, and floating-point operation order can change results. A fixed
`random_state` is therefore necessary, not a complete provenance record.

The experiment manifest also hard-codes `producer_source_modified: false` and
`producer_source_unchanged: true`; those values are not derived from the outer
run's before/after identity check. Replace path identity with content identity:
hash the frozen input database, every output and saved model, the exact model
parameters and feature schema, imported source bytes, lockfile, relevant
package/native-library versions, and hardware/device description. Recompute
and verify that content manifest before allowing even a challenger label.
Repeat the repaired experiment twice on the declared promotion platform and
compare model bytes, predictions, selected cores, and gate metrics within a
predeclared tolerance. Preserve [XGBoost's stable JSON model
format][xgboost-model-io] for durable models rather than Python serialization.

One selection input also crosses the fold boundary directly.
`_typical_hero_budget()` takes median final net worth from every
`player_matches` row without joining `match_folds`, then passes that all-fold
number into `compare_cores()` as the maximum candidate cost. The manifest lists
`final_net_worth` among excluded future features. It is absent from per-query
model features, but it still changes which whole-build candidates are eligible.

All-fold and train-only hero medians differ by a median 173 souls and at most
554.5 in this run. Because final-set costs move in 800-soul units, the allowable
cost band changes for 11 of 38 heroes. None of the 38 currently selected
XGBoost endings exceeds its train-only median, so this did not admit an
obviously over-budget winner; lower-ranked candidate membership can still
differ. Calculate every learned selection constraint from train only, use
validation for candidate choice, and reserve test for reporting. The experiment
manifest should distinguish `model_features`, `selection_inputs`, and
`report_only_fields` instead of claiming a field is excluded globally.

This is still not the final clean experiment. It retains the winner-only
matches, orders unrelated same-second buys by item ID, lacks observed Extra Slot
state, and inherits the raw-asset uniqueness default. Repair those boundaries,
freeze the derived input, then refit once and compare a later untouched test
fold.

Candidate legality is also incomplete in that experiment. The shop catalog
filter excludes an already owned item and a fifth active item, but it does not
know how many Extra Slots the team has unlocked and does not test whether a
candidate can fit. The corrected replay reached 12 simultaneously owned items
immediately before 50,730 of 2,520,982 first-acquisition rows (2.01%). In those
full-inventory states, the current candidate builder emitted 7,020,166 rows;
6,832,446 (97.3%) did not consume an owned direct component and therefore could
not fit under the 12-item cap.

That count is a candidate-set audit, not a corrected accuracy score. The replay
still had 394 nominal observed targets without an owned direct component at the
cap and eight transient 13-item states, concentrated in same-second buckets.
Those contradictions are additional reasons to treat tied purchase, component,
and sale events as a partially ordered set instead of asserting one numeric-ID
sequence. They should be excluded or resolved before scoring, not force-added
as positive candidates.

The active-item cap has the same smaller contradiction. Under the ranker's own
replay, 49,281 queries began with four active items. `legal_candidates()`
correctly removed other active choices, then its unconditional target fallback
put an active target back in 143 queries across 22 heroes. Those 143 rows are
0.006% of all queries, so they do not explain the aggregate score, but a
positive label outside the declared legal set is still not a valid ranking
example. Count and quarantine it. First determine whether the source omitted a
same-second removal, the replay is wrong, or current shop behavior differs from
the four-key mechanics contract; never repair it by silently force-adding the
answer.

The problem is not limited to the hard cap. There were 730,546 queries with at
least nine owned items, 460,941 with at least ten, and 231,970 with at least
11. Whether another non-upgrade can fit in those states depends on the team's
observed Extra Slot unlocks, which are absent from `PurchaseQuery`. The current
metric can move in either direction because it ranks impossible negatives and
trains on the same mismatch; it is not an end-to-end shop-policy score. Join or
derive objective state at the target second, run candidates through the shared
mechanics owner, and report coverage/abstention when unlock state is unknown.

All 38 XGBoost challengers passed the recorded evaluation, but none was
promoted because no portable validated policy export was available. This is a
healthy fail-closed result. The guide should not imply that the learned ranker
is serving production paths.

The challenger gain is real for its measured job. On non-component held-out
purchases, top-one accuracy rises from 23.5% to 35.9%, top-five from 56.5% to
65.2%, and mean reciprocal rank from 0.385 to 0.494. That does not automatically
make a better eight-item guide. XGBoost changed 22 candidate cores; 19 of those
had lower full-set support on the chronological test fold, with a median drop
of 11.5 matches. Median item-set overlap with the deterministic candidate was
77.8%, but the minimum was 23.1%.

This is the difference between predicting the next common action and choosing
one coherent whole-match target. Keep XGBoost in the optional research stack,
evaluate both jobs separately, and require a portable legal policy plus
held-out full-path coherence before promotion. Its stronger next-item score is
not a reason to add XGBoost to the normal CLI install.

### Stability is strong in aggregate, uneven by hero and card

The split itself is sound at the match boundary: train, validation, and test
contain 7,508, 2,503, and 2,503 distinct matches respectively; no match crosses
a fold, every fold contains all 38 heroes, and no player/item first-purchase row
is duplicated. The folds are chronological with only seconds between adjacent
boundaries. This is a real strength even though the full window is short.

The offline chronological split supports adoption as the current ordering
signal. Train/test item-adoption order has median Spearman 0.9802 and median
top-ten Jaccard 1.0. Outcome-derived alternatives are much less stable:
Wilson lower bounds score 0.6067, empirical-Bayes means 0.3485, and the
state-adjusted ridge item order only 0.1446. Stable popularity is not optimality,
but it is a more reproducible descriptive basis than current outcome ranking.

Full paths are less stable than individual top-ten lists. All 38 train and test
paths remain mechanically legal; median item-set agreement is 81.8% and median
ordered overlap is 90.0%. Eighteen heroes have the exact same item set across
the split. Five fall below 80% set agreement: Billy is lowest at 53.8%, while
Paradox, Wraith, Vyper, and Apollo are each 66.7%. Kelvin is 81.8% by item set
but only 60% by exact position. Refresh and fingerprint per hero; do not treat a
population median as permission to freeze every path for the whole patch.

Rank-family medians are also reassuring but hide a few meaningful splits.
Emissary-versus-Phantom adoption has median Spearman 0.903 and median top-ten
overlap 81.8%, yet Bebop's Tier II overlap is only 33.3% and Tier IV is 42.9%.
Rem's Tier IV order reverses direction at -0.321, though only seven shared
supported items make that estimate fragile. Even Emissary-versus-Oracle,
Kelvin's Tier III top-ten overlap is 66.7%. One broad-rank build is a useful
default, not a rank-personalized answer. Only offer rank variants after each
hero/tier cell has enough shared support and a stable held-out difference.

Two robustness checks support pooling where the build currently does. Match
adoption and unique-account breadth have median Spearman 0.9886 and median
top-ten overlap 1.0 across 152 hero/tier cells, so a few repeat players are not
usually driving item order. Calibrated-versus-provisional player adoption has
median Spearman 0.9534 and the same perfect median top-ten overlap. Keep both
audits, but neither fixes the sparse Phantom, Ascendant, or absent Eternus tail.

Purchase windows are usually stable but require a per-card display gate. Across
1,503 comparable cells, median train/test shift is 21 seconds and 372.5 souls;
the 90th percentiles are 82.5 seconds and 1,790 souls. The maxima are 770
seconds and 13,319 souls. Only 0.7% of time ranges and 3.4% of soul ranges have
less than half-overlap, but those outliers should lose their numeric label
rather than inherit the global result.

Golden Goose Egg is the clearest current example. Its train/test soul-range
overlap is zero for Graves, 0.016 for Kelvin, 0.060 for Wraith, and 0.083 for
Celeste, with only about 3%-13% of those purchases having valid pre-purchase
state. Yet the current optional cards display a precise-looking `2k-5k`-style
range for all four heroes. Show purchase order or time for opening items and
omit the soul range when valid state or split overlap fails. This is a wording
and evidence-admission fix, not a reason to fill missing opening state.

### Situational choices

| Metric | Result |
| --- | ---: |
| Candidate counter rules checked | 5,700 |
| Rules admitted | 0 |
| Heroes with an admitted rule | 0 of 38 |
| Explicit hero-level abstentions | 38 |

This is one of the most important product facts. The four optional tier menus
are adoption reference menus, not validated counter recommendations. Their
left-to-right order is typical purchase timing, not “best first” or highest win
rate.

The zero is not a near miss. All 5,700 exported candidate entries passed the
mechanics and raw-support checks, but only 3,906 had a same-opportunity
comparator. Just one had a comparison interval narrow enough for the configured
ten-percentage-point width limit, and its interval still crossed zero. Twelve
entries had a positive lower bound, but all twelve were too wide. No entry
passed the positive-comparative-advantage gate. Chronological stability passed
for 1,139 entries, overlap failed for 39, and effective support failed for 123.
These counts overlap because one candidate can fail several checks.

The uncertainty bottleneck matches the available cell sizes. Among comparable
exported entries, the target-support median is 141 and the comparison-support
median is 211; their interval-width median is 16.5 percentage points. The
narrowest interval is 9.56 points. A rough balanced-binomial calculation near
a 50% outcome rate needs about 668 observations on each side to meet the
ten-point width rule, before asking that the full interval also be positive.
No observed comparison had at least 668 records on both sides. Keep the strict
abstention, but surface this power diagnosis instead of a single catch-all
sentence.

The zero-rule abstention is also containing a mechanics-classification defect.
Both threat helpers search the flattened JSON of the entire item record. The
asset payload includes labels for disabled or zero-valued generic properties,
so a phrase can exist without being an active effect. On the current 156-item
catalog, `classify_observed_item_threats` labels **every item** as both bullet
pressure and spirit pressure. It adds mobility to 46, control to 12, and
healing to seven. Any observed enemy item would therefore manufacture at least
two threats.

The response side marks 101 items as answering at least one threat: 87 as ally
protection, 35 as spirit-burst responses, 34 as bullet-pressure responses, and
11 as healing responses. Implausible examples include Glass Cannon as ally
protection and Armor Piercing Rounds as a bullet-pressure defense. These false
labels then multiply one statistical comparison into several of the 5,700
candidate entries and satisfy the service's nominal mechanics check.

Match phrases only in an active effect whose value or description proves the
mechanic. Prefer structured property types plus effective nonzero values and a
small reviewed mapping over full-record substring search; descriptions can be
a conservative fallback. Add full current assets as negative fixtures, not
only the present minimal descriptions. Until then, keep branches disabled and
do not describe the candidate-audit threat names as mechanically validated.

There is also a policy-shape defect to fix before enabling any result. The
source comparisons are conditioned on `phase` and shop `tier`, but the exported
candidate and branch discard both fields. A branch would therefore say only
“against enemy hero N, choose item A instead of item B,” even though its
evidence applied at one particular phase and tier. Overlap is reused at the
hero-item level and chronological stability is reused at the whole
hero-and-scope level, so neither is specific to the enemy/opportunity cell.
The 5,700 count also expands one item/opportunity comparison into multiple
mechanic-response labels; it is not 5,700 independent build decisions. Export
the opportunity state, report unique comparison cells separately from response
labels, and evaluate stability at the finest supportable state before exposing
a player-facing rule.

The runtime would broaden that evidence again. `_matching_counter()` checks
only the threat label and optional enemy hero, then counter recommendation runs
before the normal purchase path. It does not require the compared item to be
the current planned choice, check whether that comparator is owned, or match a
purchase position, price tier, or phase. A future admitted branch could
therefore fire at minute five even when its comparison was supported only at a
late Tier IV shop decision. Carry the full compared opportunity into the
portable branch and require it at runtime; otherwise abstain. Test the same
enemy/threat at the wrong tier, wrong phase, and wrong planned item so a valid
local comparison cannot become a universal counter rule.

`same_lane` also needs a player-facing definition. In every complete match,
lanes 1, 4, and 6 contain exactly two heroes per team. The join therefore links
each purchase decision to both members of the opposing lane duo. It is not a
one-to-one lane opponent, and it records the assigned opening lane rather than
who the player actually fought after swaps and rotations. A supported future
claim should say “when X was one of the two heroes assigned to your lane,” not
“against X.” Keep full-enemy-team presence, opening-lane presence, and observed
live threats as three different inputs.

The held-out outcome test explains why. A model using match state alone scored
0.208835 Brier loss; adding item identity made it slightly worse at 0.209306.
Lower is better, so this cohort does not show extra predictive value from
knowing the item after accounting for the available state. Even among top-ten
adopted items, overlap-weighted comparable-state support has a median of only
39.4% of raw observations and a 10th percentile of 6.6%. A large purchase count
is not automatically a large fair comparison group.

Generated prose should say things such as “commonly bought around this soul
range” and “optional choice.” It should not say “buy this against” until a
mechanics-backed, stable comparison passes the existing gates.

The optional menus themselves are broad. Of 1,518 cards, 186 were bought by
less than 5% of the relevant hero records and 513 were bought by less than 10%.
Median adoption was 14.6%. Support ranged from 21 to 6,893 records, and 86
cards derived their displayed soul range from fewer than half of their purchase
records having a valid pre-purchase net-worth value.

This does not make the rare cards wrong. It does mean targeting ten cards per
tier is a coverage choice, not a confidence threshold. Sample size and
mechanics should decide whether a rare option receives a hover explanation.

Simple sensitivity counts show the size/coverage tradeoff. A 5% adoption floor
would retain 1,332 of 1,518 cards, or 87.7%, but only 17 of 152 tier menus would
shrink to six cards or fewer. A 10% floor would retain 1,005 cards, or 66.2%,
and put 79 menus at six cards or fewer; the median menu would be six. A 15%
floor would retain 736 cards and make 121 menus one-row candidates. At 20%, two
menus would become empty.

Do not turn one of those percentages into a universal tactical rule. Use a
moderate adoption floor as the compact reference baseline, then admit a rare
item only when real mechanics and a named game situation justify the exception.
That exception should carry the explanation the common items do not need. This
would make panel size respond to actual evidence while preserving defensible
niche choices.

### Ability-order evidence

The packet contains 173,798 valid ability records and 30,690 complete paths.
The final selected branch has a median support of 374 records per hero. That
median is only 9.6% of all valid ability records for the hero; the range is
3.1% to 26.9%.

The order is deliberately composed from the most-supported legal choice at
each reached state. It is not necessarily one exact 16-step path that many
players followed from beginning to end. “Common choice at each level” is an
accurate player explanation. “Observed full order” would be too strong.

The current client instantiates its four-icon-and-pip ability-order panel in
both the HUD build editor and the separate build-details view. Its ability
tooltip has a build-annotation container, but the serializer writes the same
path-wide support sentence only on the **first** currency change. The XML has
no always-visible explanation label. Without a native hover test, the safest
interpretation is that the support sentence may be hidden behind one ability
or pip tooltip rather than teaching the 16-step path. Keep path-wide provenance
in build details or diagnostics; if player guidance belongs on an ability
change, attach a short reason to the exact decision it explains and verify that
surface in both panels. Do not make the first unlock carry an unexplained claim
about every later branch.

The complete 419-layout scan also found no declarative text-entry or other
authoring control for an ability annotation. The native ability editor exposes
the icon/pip sequence and reset action, while every public API currency change
in the sample had a null annotation. A native panel could still create a
control internally, so absence from XML is not conclusive. The official
[Map Rework Update][map-rework] also describes ability-build authoring as
clicking ability icons, with no note-authoring step. Treat generated ability
notes as an unproved private extension: verify the exact tooltip, copy/edit/save,
and reload behavior before using that field for essential advice. Until then,
a plain build-level ability summary is more dependable than 16 notes the player
may never see.

A frozen-filter replay at 21:53 UTC on August 17 makes that distinction urgent.
The backend returned 176,849 validated appearances and 31,272 complete-path
appearances, up from 173,798 and 30,690 in the captured packet. Every hero's
decision-support vector changed, but all 38 selected paths remained unchanged.
The summed final-state support rose from 17,367 to 17,673. These replay counts
are stability evidence, not a replacement artifact: the API had backfilled
behind the unchanged cutoff.

Only 36 selected 16-step paths appeared even once. Graves and Paradox appeared
zero times; Drifter and Seven appeared twice each. Six heroes had exact-path
support below 1% of their complete paths. Across the roster, the median exact
path appeared 68.5 times and represented 9.68% of complete paths; the range was
0% to 59.94%.

The displayed `tail support` does not measure that exact sequence. The selector
reduces every prefix to the number of ranks already bought in each ability, so
different earlier orders merge into the same state. It then reports support
for the last choice from that merged state. For heroes whose exact path did
appear, this state support was a median 5.2 times the exact-path count and up to
279 times larger. Calling it “tail support” beside a fully ordered 16-step UI
invites a player to read it as support for the displayed route.

Keep the legal state composition, but state its evidence plainly: “popular
next rank at each ability state.” If exact order support is shown, calculate it
separately and allow zero. Evaluation should report both (1) next-rank coverage
at every state and (2) exact complete-path appearances. Do not replace the
state count with the exact count silently; they answer different questions.
The strongest future design may show a well-supported early order, then label
late upgrades as flexible once exact routes fragment.

Partial games are essential input, but the selector does not account for
whether its locally strongest choice can reach a complete path. In the same
replay, only 31,272 of 176,849 validated appearances, or 17.7%, ended at 16
actions; 145,577 ended earlier. Every hero had partial rows. Discarding them
changed the selected state-composed path for nine heroes, even though all 38
all-row selections still completed and exactly matched the packet.
Filtering to complete games would therefore throw away most reached-state
evidence and favor longer matches.

There is nevertheless a deterministic dead-end case. An in-memory probe gave
the selector a 101-match, one-action row beginning with ability 1 and a
100-match complete legal path beginning with ability 2. The complete row alone
produced its 16-action path. With both rows present, the greedy first step chose
ability 1, found no row that continued from that state, and returned `None`.
This safely skips a hero, but it incorrectly reports that no complete
projection exists. Search the small four-ability state graph for a complete
legal path first, then optimize the existing support objective among
completable choices. Preserve all partial-game contributions at states they
actually reached. Add the two-row probe as a regression fixture and prove the
current 38 selections remain unchanged.

The same row validator has a current Silver-specific alias problem. A fresh
replay of the exact frozen ability query returned 67,785 aggregated rows and
177,283 matching appearances. `_valid_path()` silently rejected 315 rows, all
for Silver, because those rows contained more than four ability IDs. That is
29.6% of Silver's 1,065 path rows and 434 of its 2,216 matching appearances.
The extra IDs are not unknown mechanics: the pinned item assets explicitly
link Go For The Throat to Slam Fire, Mauling Leap to Boot Kick, and Tail Whack
to Entangling Bola with `LinkUpgrades` and `DisplayAsSubAbility`. They are the
transformed forms used during Lycan Curse.

Replacing each linked form with its upgrade-owning base ability before path
validation recovered 308 rows and 427 appearances. The other seven rows each
had one record and still assigned a fifth rank to one base ability, so rejecting
them remained correct. Normalization did not change Silver's selected 16-step
order, but it raised the fresh state cohort from 1,782 to 2,209, complete-path
appearances from 192 to 257, and final-state support from 175 to 238. The saved
packet has the same selected path and final support 175 but an earlier
1,750-appearance cohort; the later numbers reflect endpoint backfill and must
not rewrite that artifact.

The ten current sampled Silver community builds used only the four base IDs in
their ability changes, including the two builds with concatenated 24- and
28-change payloads. The alias defect therefore changes telemetry support, not
the public-build comparison after its existing complete-block filtering.

The current mechanics packet has the inverse omission: it correctly exports
only Silver's four rank-owning base abilities, but it supplies none of the
three linked transformed forms. A roster-wide asset scan found Silver was the
only one of 38 active heroes with `LinkUpgrades`/`DisplayAsSubAbility` links,
so this needs one general linked-form rule rather than a hard-coded hero
exception. Keep Slam Fire, Boot Kick, and Entangling Bola as the four-slot
upgrade identities; attach Go For The Throat, Mauling Leap, and Tail Whack as
closed mechanic variants. That lets tactical prose describe Lycan Curse's
actual form without inventing a fifth rankable ability, and lets `LinkImbues`
use the same canonical target identity.

A broader scan found 24 signature-to-dependent edges across 14 active heroes.
The other 21 edges have no link flags and are mostly triggers, cancel actions,
weapons, or innate helpers; seven nevertheless have recognizable player names
such as Ambush, Close Doors, Hop To Ally, End the Curse, and Lycan Claws.
`MECHANICS_FIELDS` currently omits `dependent_abilities`, so none of those
relationships or child records enters the hero packet. Do not dump all 21
internal helpers into model context. Export the dependency edge and flags
deterministically, classify whether the child is player-visible and
claim-relevant, nest admitted child mechanics under its parent, and keep it
non-rankable unless it owns a real signature slot. Add an audit-only list for
unclassified edges so a patch introducing another `LinkUpgrades` form cannot
silently become Silver's special case again.

Resolve upgrade aliases deterministically from the pinned asset graph before
counting ranks, retain the observed transformed ID for audit, and reject an
alias with zero or multiple upgrade-owning parents. Report rejected rows and
matching appearances per hero rather than dropping them silently. A regression
should include the three Silver aliases, the seven-style fifth-rank corruption,
and an ordinary four-ability hero whose result remains byte-for-byte unchanged.

The same replay shows where that fragmentation starts. Among records that
reached each number of upgrades, the median selected exact-prefix share was
90.3% for step one, 74.1% for two, 56.8% for four, 33.5% for six, 26.2% for
eight, 13.9% for ten, 10.4% for 12, and 9.8% for all 16. Twenty-two of 38 heroes
retained majority support through four steps; only three did through eight.
McGinnis's four-step prefix was already only 13.8%, while one hero still had
60.1% exact support at 16. Use a per-hero confidence boundary. A compact guide
can emphasize the first two to four choices when supported and call the rest
“common later upgrades” instead of drawing false certainty from one roster-wide
cutoff.

The current native ability encoding agrees with the packet, but only by a
duplicated assumption. Across all 608 displayed changes, the validated
mechanics schedule contains 152 unlock-currency spends and 152 each at one,
two, and five Ability Points. The protobuf serializer independently ignores
that schedule, counts prior purchases of each ability, and hard-codes the
upgrade deltas as `-1`, `-2`, and `-5`. Mechanics already reads each current
ability's asset-defined `upgrade_costs`, and its unit test deliberately proves
that a `1, 3, 6` definition can be scheduled. No integration test carries that
non-default schedule through native build encoding.

This is not a malformed current guide. It is a patch hazard: if Valve changes
an ability's costs, evidence generation can correctly validate the new path
while the Steam projection silently writes the old currency sequence. Make the
validated `AbilityTimelineStep` values—or an equivalent game-named currency
change list—part of the presentation boundary. Protobuf should serialize that
closed result rather than own a second rule. A fixture with non-default costs
must decode to those exact deltas.

### Output size

The current projection contains:

| Output | Count |
| --- | ---: |
| Hero builds | 38 |
| Categories | 190 |
| Item cards | 2,005 |
| Optional item cards | 1,518 |
| Explained item or ability actions | 304 |
| Explained actions per hero | 8 |

The 304 final targets comprise 131 Spirit, 95 Vitality, and 78 Weapon items.
By shop tier they comprise five Tier I, 123 Tier II, 118 Tier III, and 58 Tier
IV items. Forty-eight are active items. “Final” therefore means retained in the
selected ending inventory, not necessarily expensive or passive.

The roster is genuinely varied rather than one template repeated 38 times.
Those 304 slots use 91 distinct final items; 33 appear for only one hero, and
no two heroes have the same eight-item set. Median pairwise set overlap is only
6.7%, while the most similar pairs share five of eight items. The most common
final choices are Greater Expansion on 12 heroes, Healbane and Tankbuster on 11
each, and Superior Duration, Trophy Collector, and Boundless Spirit on ten
each. This supports per-hero generation, while also identifying the shared
items whose mechanics, imbue behavior, and patch changes deserve the broadest
regression coverage.

Co-occurrence is more specific than those single-card totals. The 38 final
sets contain 784 distinct item pairs: 598, or 76.3%, occur for only one hero.
The most repeated pairs—Superior Duration with Trophy Collector and Tankbuster
with Boundless Spirit—occur for six heroes each. The most repeated triple,
Suppressor with Healbane and Escalating Exposure, occurs for four. Kelvin is
the only final set containing all three clipped late cards together.
Escalating Exposure plus Boundless Spirit occurs for Kelvin and Holliday;
Escalating Exposure plus Greater Expansion for Kelvin and Victor; and
Boundless Spirit plus Greater Expansion for five heroes. Shared item
validators and prose templates are therefore appropriate, but the actual
package and ability fit still need hero-level evidence.

#### Common stat items pass a basic mechanics-fit check

Structured ability markers can reject an impossible stat item before prose is
generated. They cannot decide which valid item is best. A roster-wide scan of
active, non-sentinel ability properties found:

| Structured marker | Roster coverage | Current matching final choice | Choices with no marker |
| --- | ---: | ---: | ---: |
| Qualifying ability range or radius | 38 of 38 heroes | Greater Expansion on 12 heroes | 0 |
| Qualifying ability duration | 37 of 38 heroes | Superior Duration on 10 heroes | 0 |
| At least one charged ability | 24 of 38 heroes | Rapid Recharge on 9 heroes | 0 |
| Ability cooldown | 38 of 38 heroes | Any general cooldown package | Not discriminating |

This is a useful positive integrity check: none of those 31 selected
hero/item pairs is mechanically unsupported by the supplied ability packet.
It is not evidence that the item caused better outcomes or that the selected
hero needs it more than another qualified hero. Range or radius qualifies the
entire roster and duration all but Vyper, so those flags have almost no power
to rank candidates by themselves. Charged-ability compatibility is more
selective and should be a hard legality rule for Rapid Recharge.

Keep this layer deliberately narrow. For each stat package, emit the exact
ability and property that qualify it, as the Kelvin check above does. Do not
infer that every ability benefits, and do not feed a raw boolean into a model
as if it were a tactical reason. Descriptive adoption, purchase timing, slot
fit, investment breakpoints, and the hero's actual fight job still decide
whether a mechanically valid item belongs in the final eight.

Optional menus overlap more, as expected for a general shop reference: their
median pairwise Jaccard is 23.1% and the maximum is 48.1%. No optional item
appears for all 38 heroes. The menus are broad but not literally generic.

The selection does not explicitly evaluate Deadlock's category-investment
breakpoints. In the pinned hero assets, every hero has the same current table.
At 4,800 souls, Weapon investment jumps from 18 to 46, Vitality from 20 to 38,
and Spirit from 19 to 38. Valve has repeatedly rebalanced these tracks, and the
client highlights 4,800 as an investment spike; it is part of build timing,
not background flavor. See Valve's [April 30 investment update][investment-update].

Using full target value, which already includes component credit, only 20 of
38 selected endings reach at least 4,800 in all three categories. Fifteen are
below 4,800 Weapon investment, five below Vitality, and two below Spirit; seven
have zero Weapon targets and Venator has zero Spirit targets. Specialization
can be exactly right—Kelvin deliberately ends at 0 Weapon, 4,800 Vitality, and
22,400 Spirit. The issue is whether a near-miss was reviewed.

Four heroes have an all-three-spike candidate within 10% of the selected set's
support: Lady Geist at 169 versus 171 records, Grey Talon at 120 versus 123,
Pocket at 491 versus 527, and Celeste at 194 versus 209. These alternatives
also change mechanics, slots, and sometimes total cost, so the breakpoint does
not make them automatically better. Put category spend and crossed spikes in
the candidate comparison, then let support, hero plan, timing, and mechanics
decide together. A phase label such as `4.8K SPIRIT SPIKE` is also more useful
to a player than an internal “cost track.”

The repository already has a validated `CategoryBonusTable`, but production
does not call it; only its unit test does. Either connect this game mechanic to
candidate reports, route annotations, and the stateful recommender, or remove
the dormant abstraction until there is a consumer. The XGBoost experiment sees
owned item counts by category, not souls invested or distance to the next
breakpoint, so it does not fill this gap.

Prerequisite expansion adds 183 component steps, taking the displayed CORE
total from 304 final choices to 487 cards. The extra cards are purchase actions,
not 183 additional strategic decisions. This distinction is why a reliable
native prerequisite queue would simplify the UI without changing the target
inventory.

Replaying those 487 cards through the exported component graph confirmed that
all 38 paths peak at eight simultaneously held items and finish at eight. The
183 extra purchases are exactly balanced by 183 component consumptions. No
default path needs an objective-unlocked Extra Slot, and the clipping defect is
therefore a display problem rather than hidden inventory overflow. One held
detour still fits in the ninth starting universal slot; a second may need a
Walker-earned Extra Slot, an upgrade, or a sale. Valve's current universal
12-slot contract begins with the [Shop Rework Update][shop-rework]; the
installed client localization independently confirms three current Walker
unlock messages and the `Extra Slot` label.

Peak active-item occupancy is also bounded: nine heroes peak at zero active
items, 12 at one, 13 at two, and four at three. CORE alone never reaches the
four-key binding ceiling.

The packet sets no `required_flex_slots` and no `sell_priority` on any of the
2,005 cards. The fields exist, but all current values are empty.

The installed English client defines the missing semantics precisely: sell
priority is a value from 0 to 100, and the **highest** value is sold first to
make room when Quickbuy fires with full slots. The dormant managed projection
therefore reverses a planned multi-sale order.
`_apply_sell_priorities()` walks `SELL` nodes in path order and gives the first
distinct item 1, the second 2, and so on. Native Quickbuy will prefer the
second item while both are held. No current policy reaches this bug because no
card has a sell priority, but the first admitted detour with two exits can.
Assign the earliest intended sale the highest bounded value, validate the
native 0-100 range, define equal-priority behavior, and decode the resulting
protobuf in a two-item fixture. A client acceptance test should fill all slots,
queue the replacement, and verify the intended cheap item is the one sold.

Every eight-item final path fits the current nine starting universal slots,
leaving one slot for a detour. A second held optional item can require unlocked
Extra Slot space or a sale. The guide never says when that capacity is needed,
which cheap item to sell after a detour, or what to do if the queue reaches a
blocked purchase.

Not every optional choice is an extra held item. The component graph exposes
453 direct upgrade relationships between cards already present in the same
hero's optional menus, and every hero has at least one. Counting 40 menu cards
as 40 independent choices therefore exaggerates the menu's breadth. More
importantly, 25 optional cards across 16 heroes upgrade and consume one of the
eight final CORE targets; 24 are direct upgrades and one reaches the target
through a longer chain. The validator forbids the *same item ID* from appearing
in CORE and a tier menu, but does not flag this parent-child relationship.

Kelvin has two examples: optional Juggernaut upgrades Enduring Speed, and
optional Healing Tempo upgrades Healing Booster. Those are slot-preserving
replacements, not detours that consume the ninth starting slot. Mina and Rem each
have three such choices; Apollo, Kelvin, Lash, Paradox, and Victor each have
two. Label these as `UPGRADE CORE` or `LUXURY UPGRADE`, name the consumed item,
and show the resulting eight-item ending. Group related optional cards into one
upgrade chain instead of presenting every tier as an unrelated choice. This is
also part of the queue test: an unintended optional auto-purchase can silently
change the promised final inventory even when it does not overflow slots.

There are also 49 direct `pick one upgrade` forks across 28 heroes: one shown
component feeds two or more shown parents. Examples are Debuff Reducer into
Spellbreaker or Unstoppable, Mystic Expansion into Greater Expansion or
Ballistic Enchantment, and Healing Rite into Rescue Beam or Healing Nova.
These forks account for 103 parent-card positions. Buying both parents may be
possible only after repurchasing or otherwise satisfying the shared component;
they are not one linear chain. The item graph can provide this structure
without a new statistical model. Render the parent choices together and let
the tactical explanation say what match need separates them.

The queued CORE sets contain zero to three active items, below the four-key
binding limit. The optional menus contain 330 active-item cards. Several
optional actives can therefore create a separate binding problem even when
inventory space remains.

That burden is roster-wide. A hero exposes three to 17 distinct optional
actives, with a median of eight. Kelvin exposes 16 and Rem 17. When CORE actives
are included, 37 of 38 heroes have enough available suggestions to exceed the
four-key binding ceiling. This does not mean the menus are mechanically
invalid: optional cards are alternatives. It means their current presentation
does not communicate combination legality. Group actives as `PICK ONE`, say
which existing active they replace once four are bound, and make the fourth
active a visible decision rather than an accidental queue failure.

Imbue targets are a larger current gap. The projection contains 145 cards whose
item mechanics require an ability target, spread across 36 heroes. Forty-nine
are in CORE displays and 18 are final target items. The earlier 128-card count
incorrectly omitted all 17 Duration Extender cards, even though its
`imbue_modifier_value` mechanic also requires an ability choice. All 145
`imbue_target_ability_id` values are empty.

The frozen purchase telemetry can narrow this gap without using outcome rate.
All 145 projected hero/item pairs had recorded purchases with a positive imbued
ability, and every target resolved to one of that hero's four supplied
abilities. The most common target held a 90.2% median share. Ninety-two pairs
had at least 20 targets and 80% or greater agreement; 14 of the 18 final CORE
imbues passed that simple descriptive screen. Wraith's Mercurial Magnum targeted
Card Trick in 6,658 of 6,664 records, and Mina's Quicksilver Reload targeted
Rake in all 3,351.

The leading target identity was also fairly stable: it stayed the same across
train, validation, and test folds for 141 of 145 pairs, and across Emissary,
Oracle, and Phantom groups for 134. Requiring at least 20 records and 80%
agreement in **every** chronological and rank slice leaves 74 pairs, including
the same 14 of 18 final CORE imbues. All 18 final items kept the same leading
ability in every slice; the four failures below are consensus failures, not
target flips. These checks are strong enough for a reviewed candidate list,
while still not proving tactical superiority.

The other cases show why “take the majority” is not a universal rule. Rem's
Compress Cooldown split across all four abilities and put only 36.2% on Pillow
Toss. The four lower-consensus final targets were Paradox Compress Cooldown
(62.6% Kinetic Carbine), Warden Surge of Power (77.8% Willpower), Mina Mystic
Expansion (67.3% Rake), and Graves Echo Shard (64.6% Grasping Hands). Eleven of
all 145 pairs put less than half of targeted purchases on the leading ability.

Use top-target share as a candidate, not the final policy. Require chronological
and rank stability, current item qualifiers, legal ability identity, adequate
support, and a mechanics-backed fit with the named hero plan. A strong stable
choice can be emitted deterministically and explained in prose. A split choice
should show `CHOOSE IMBUE` and name the two real play patterns before Queue
reaches the card. Test whether a component target survives its upgrade,
especially Duration Extender into Superior Duration.

The 22:20 UTC community replay used an imbue target on 796 cards across 303 of
380 builds. All 796 targets were one of the relevant hero's four current
signature abilities, every item carried a current imbue marker, and none of the 63
`imbue_active_non_ult` cards targeted the hero's fourth/ultimate slot. The mode
split was 380 modifier-value, 353 active, and 63 active-non-ultimate targets.
Four rows belonged to the two Street Brawl Tier V items identified above; the
other 792 were normal Tier I–IV cards. This is strong structural evidence for
validating exact item/target compatibility. It does not prove that the public
author chose the best tactical target.

The sell-priority field needs more careful interpretation. The original
snapshot contained a non-null value on 5,207 cards across 322 builds, but a
same-filter replay showed that almost all such values are zero. In the replay,
5,240 cards had a value, 5,073 were zero, and only 167 cards across 64 builds
had an active priority from 1 through 100. Sixty-six of those active priorities
were in optional categories. No sampled card set `required_flex_slots`.

A full scan of 419 current compiled layout files found no control for authoring
that Extra Slot requirement. The item-tooltip style still contains a
`.HasRequiredFlexSlots` selector and installed localization still names
`Required Extra Slots`, so the reader may create the label dynamically; the
field is not proven dead. It is also not proven safe to generate. Keep the
optional field empty until a current native fixture can display, queue,
edit/save, and reload requirements one through three without changing them.
Normalize zero to off and reject four. This is distinct from tracking how many
Extra Slots the player has unlocked in the deterministic recommendation state.

The installed client defines priority as a 0-100 value and says the **highest**
priority is sold first when Quickbuy needs room. The code currently accepts
any positive integer and has no upper bound. Before managed builds use this
field, treat zero as off, constrain active values to 1-100, and add a current
client test that confirms the documented high-to-low behavior. Do not infer
meaningful priority merely because the API emits an explicit zero.

The current in-shop editor adds an awkward boundary: `SellPriorityTextEntry`
has `maxchars="2"`, even though the localization and serialized data allow 100.
The 22:01 UTC public replay contained 167 positive priorities, including three
values of 100 and none above 100. Thus 100 is a current readable serialized
value but may not be manually authorable or safely round-trippable in that
surface. Add exact edit/save probes for 99 and 100. If 100 cannot survive, keep
the schema validator aware of the native 0–100 domain but restrict newly
generated active values to 1–99 and document why.

The managed builds use none of these three fields. An imbue target should never
be guessed: it must match a real hero ability and the build's stated game plan.
But a queued CORE path should either choose and explain it or clearly tell the
player that a purchase needs input. Deterministic plan code should own the
target; model prose should only explain the validated choice.

This field is behavioral, not decorative. A 2025 client report says build
imbue suggestions previously applied the target during Quickbuy, then stopped
doing so after a client change. A separate report says the target editor was
available in a match or training environment but missing from the dashboard
build editor. A February 2026 Rem report describes queued upgrade purchases
stalling when an earlier imbue item had no target. See the
[Quickbuy report][imbue-auto], [editor report][imbue-editor], and
[Rem queue report][rem-imbue].

The current installed localization states the intended behavior directly: a
suggested hero ability is shown in the purchase dialog and is automatically
chosen when the item is purchased through Quickbuy. That makes an empty target
more consequential, not less. The older reports remain useful regression cases
because localized intent does not prove the current purchase path implements
it correctly.

These reports do not prove the current client still has each bug. They do prove
that target presence, editing context, prerequisite expansion, and automated
purchase interact. Before emitting targets, test all four together for every
imbue-capable item family. Before leaving targets empty, test that omission does
not stall or misdirect the current queue.

Kelvin shows why popularity alone is insufficient. Six sampled public builds
included Mystic Expansion. Two targeted Arctic Beam, one targeted Frozen
Shelter, one targeted Frost Grenade, and two left it unset. That is evidence of
multiple play patterns, not one universal imbue choice.

One hundred fifty of the 152 optional tier categories contain the full ten
cards. This maximizes reference coverage, but it also makes nearly every build
visually dense. A future product decision should test whether five or six
well-labeled choices teach more than ten compact cards.

No optional card duplicates any card in the component-expanded CORE path. This
is a meaningful improvement over the older artifact described in the August 13
usage audit and should remain a regression contract.

## Player-visible wording audit

The artifact validator correctly distinguishes player text from audit-only
text, but several internal phrases still reach the actual build description.
Every installed description includes:

- `Ability order: state-composed observed default`;
- `tail support n=...`;
- a full snapshot hash;
- a full policy hash; and
- `Claim limit: observational; no causal item effect.`

Those details are useful for traceability. Full hashes and research labels are
poor build-details text. Keep the managed marker and exact identities in the
cache or at the end of a diagnostic surface; show patch, rank group, and data
date to the player.

The current client does not show this description beside the item grid at all.
Its main shop style sets `.SelectedBuildDescription` to `visibility: collapse`.
The separate build-details view renders the description in a 500-by-130-unit
box with `overflow: squish scroll`; the editor gives its text entry a
600-by-250-unit box. The live Kelvin grid accordingly showed the title and
cards, not the 11-line overview. This makes category headings and item hover
notes the real in-shop teaching surfaces. Description brevity still matters in
the browser/details view, but shortening it cannot fix CORE clipping or put a
tactical instruction beside the item it explains.

The size is measurable: installed descriptions contain 89-127 words, with a
median of 106.5, across 11 nonempty lines plus one separator line. Seven lines
are identical in all 38 builds. The repeated block includes the queue promise,
cohort line, marker,
generator line, patch identity, snapshot hash, and causal disclaimer. This is
excellent audit metadata but a large share of the player-facing surface. A
short four-line player summary plus an explicitly labeled technical footer
would preserve safety without making the build-details read feel like a
manifest.

The first line also has a deterministic punctuation defect in all 38 builds.
The narrative validator requires `primary_role` to be a complete sentence, so
it ends in a period. `build_presentation()` then inserts a colon before the
complete `fight_role` sentence, producing text such as
`uses fire and mobility.: Apply burning...`. Join the two complete sentences
with a space, or normalize the role fragment before adding a colon; do not
silently strip arbitrary model punctuation. The presentation fixture should
assert the exact first line, not only the presence of later metadata.

Every rebuilt patch line has a smaller version of the same boundary defect:
`Patch:  Minor Update - 08-12-2026` contains two spaces after the colon. The
stored API patch title begins with one leading space, and presentation inserts
it verbatim after its own space. Preserve the raw response and title for
evidence hashing, but derive a stripped display title once at the presentation
boundary. Test the exact line so visual cleanup cannot silently rewrite the
patch identity used elsewhere.

The live cache descriptions are 809-1,058 characters, with a 908-character
median. In the current 380-build community replay, the median was 79
characters, the 90th percentile was 249, and the maximum was 514. Community
brevity is not a correctness rule, but the managed median is 3.6 times the
sample's 90th percentile and even exceeds its maximum. `BuildPresentation`
limits the title and card/category text but sets no product budget for the
complete build description.

The current client has two different authoring limits. The dashboard build
selector allows 4,096 description characters, but the in-shop HUD editor sets
`BuildDescriptionTextEntry maxchars="512"`. Both cap the build name at 50.
The [Map Rework Update][map-rework] explicitly introduced dashboard build
creation, so these are two shipped authoring surfaces rather than one obviously
dead layout copy. Use their smaller common limit unless a cross-surface round
trip proves a different contract.
Every live managed description is therefore over the in-shop limit. Rebuilding
the reviewed bundle produced 798–1,047 characters with a 897 median, and all 38
were again over 512. In the fresh 380-build public sample, only one description
exceeded 512, at 514, and none approached 4,096. A managed build may decode and
display today while still being unsafe to edit and save through the stricter
current surface.

Neither editor limit exists at the actual admission boundary.
`BuildPresentation.__post_init__()` enforces the 50-character name limit, tags,
marker, category-description bytes, and item-annotation bytes, but it never
checks complete description length. The generation prompt asks for a
100-character primary role, yet `_validate_complete_sentence()` does not
enforce that request, and the reviewed-artifact loader accepts tactical-profile
strings of any nonzero length. A 5,025-character marked description passed
`BuildPresentation`, protobuf encoding, and metadata decode without loss in a
no-file probe. That proves the project contract permits what the current editor
cannot author; it does not establish how the native reader would display or
truncate it. Use 512 characters as the cross-editor compatibility ceiling on
the fully composed description unless an explicit native edit/save test proves
that longer managed builds round-trip unchanged. Move full hashes to a
diagnostic command or compact technical record. Do not simply delete them:
`_validate_managed_identity()` currently proves that each replacement blob
contains its expected full snapshot and policy IDs by reading those two lines
back from the description. Preserve that binding in a compact machine footer,
or replace it with an equally exact typed field whose native round trip has
been proved. Include multibyte Unicode and exact 511/512/513 fixtures; retain
4,096/4,097 probes as documentation of the other editor rather than the
product target.

There is enough room for both jobs if the copy is disciplined. This five-line
Kelvin-shaped example is 470 characters and 474 UTF-8 bytes when `s…` and `p…`
are full 64-character hashes:

```text
Utility / Spirit. Slow fights with Frost Grenade, Arctic Beam, and Frozen Shelter; protect teammates and keep sustained spirit pressure.
Queue Build: CORE left to right. Tier rows are optional.
Data: Aug 12 patch • through Aug 15 • broad ranked sample.
Buyer stats describe buyers, not item effects.
[deadlock-build-sync:v1] snapshot=ssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss policy=pppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppp
```

This is a proposed compact wire format, not text the current parser accepts:
the validator presently expects separate exact `Snapshot:` and `Policy:`
lines. Change composition and parsing atomically, retain the exact managed
marker, and round-trip full IDs before replacing any installed build.

The exact role line remains hero-specific, so validate the composed result and
shorten at sentence boundaries rather than truncating blindly. Put ability-step
reasons on ability steps and item advice on cards; the main description should
not duplicate them.

Card notes cross a similar boundary. The in-shop `AnnotationTextEntry` sets
`maxchars="200"`, while the project validates only a 240-byte limit after
tactical prose and stats are joined. In the reviewed bundle, 50 of 2,005 notes
exceeded 200 characters and 58 exceeded 200 UTF-8 bytes; the maxima were 227
characters and 229 bytes. Before narrative text was applied, the longest
stats-only note was only 64 characters, so this is a final-composition defect
rather than an analytics-size problem. A 22:01 UTC public replay found one of
5,938 nonempty notes over 200 characters, with a 211 maximum. Enforce the
native character limit on the complete note, then keep a separately named
byte/readability budget if desired. Test 199/200/201 characters and multibyte
text; do not assume the editor counts UTF-8 bytes.

All 50 overlong managed notes are among the 304 cards with tactical prose; the
median final tactical note is 176 characters. The current fallback is also
backwards for a player guide: if tactical text plus the three analytics lines
exceeds 240 bytes, `tactical_item_annotation()` discards the advice and keeps
only purchase window, buyer win rate, and pick rate. It did not fire in this
bundle, but lowering the outer limit without redesigning composition would make
that failure more likely. Preserve the short game instruction first, retain a
coarse typical purchase window when it fits, and move raw adoption/outcome
numbers to preview or diagnostics. Never solve the editor limit by throwing
away the reason the card is in the guide.

The summary also collapses two different counts. Thirty-five of 38 reviewed
summaries call CORE an `eight-item path`, while the actual CORE panel shows
9-17 purchase cards after components are expanded. Thirty-six summaries name
exactly the eight desired ending items and silently omit the prerequisite cards
the player sees and must follow. Shiv instead lists all 11 visible steps, while
Yamato names none. The underlying distinction is sound; the player wording is
not. Say `8 FINAL ITEMS • CORE also includes required components`, and call the
visible row `purchase steps` or `Queue steps`. If the UI changes to final-only
cards, state that the native Queue expands prerequisites and prove it in the
client acceptance test.

The same sample supports some existing conservative limits. Public build names
had a 23-character median and a 54-character maximum; eight exceeded 50. Those
outliers can exist in the API through older clients, imports, or other authoring
paths, but they are not permission for this writer to exceed the current
editor's explicit 50-character contract. Public item annotations topped out at
211 characters, one above the in-shop editor's explicit 200-character limit.
Category descriptions reached 4,053 characters, showing that the project's
240-byte category budget is a readability safeguard, not a decoded client
limit. Document hard client limits separately from product readability budgets
so a future maintainer does not confuse the two.

Category fields are an even clearer case for a project-owned readability rule.
The current in-shop `CategoryNameTextEntry` and
`CategoryDescriptionTextEntry` declare no `maxchars`; the compiled category
style gives their edit controls widths of 200 and 500 pixels. In a 22:20 UTC
replay, the 2,708 category names had a 13-character median and a 29-character
90th percentile, but 87 exceeded 50 characters. Three Viscous names exceeded
2,000 characters by using long runs of spaces and invisible left-to-right
marks to turn the header into a tutorial. Of 1,077 nonempty category
descriptions, the median was 41 characters, 25 exceeded 512, and the maximum
was 4,053; the two longest were copied movie-script text in one Victor build.
These are proof that the API and native editor admit text, not evidence that it
fits or helps a player. Keep managed phase names short, keep the 240-byte
description budget as a plainly labelled product rule, normalize invisible
padding, and reject content that is nonempty only because of formatting.

The padding is precisely measurable. Across 22,166 player-visible strings in
the 22:20 UTC replay, only three contained Unicode format controls; all three
were those Viscous category names. Together they carried 135 `U+200E`
left-to-right marks, and the longest ordinary-space run was 261 characters.
The 2,461 strings in the rebuilt managed bundle contained zero format-control
characters and no ordinary-space run longer than two. Preserve that positive
state. Reject bidirectional and invisible format controls in generated display
text, trim line ends, and cap repeated horizontal whitespace while still
allowing intentional newlines. Keep raw remote text only in quarantined source
evidence; normalization must not silently turn it into trusted tactical prose.

Community prose is useful for verbs, not for factual grounding. Across all
titles, build descriptions, category text, and card annotations in the fresh
380-build replay, 282 builds used a direct action word such as `buy`, `sell`,
`skip`, `choose`, `use`, `imbue`, `replace`, or `save`. But 103 also used
outcome or percentage language, 117 carried a social handle, link, or external
site name, 47 made a rank claim, and 83 advertised a date, patch, version, or
update. These groups overlap, and copied builds make them non-independent.

Every API description field was technically nonempty, yet repeated values
included a lone period, `WIP`, and link-only text. Long category descriptions
also included jokes and copied non-game material. A nonempty-field check is
therefore not a usefulness check. Borrow the short game verbs and clear choice
labels; never treat public prose, author rank, promotional outcome text, or an
`updated` title as item evidence. Deterministic mechanics and frozen match data
must remain the only factual source supplied to generation.

The 38 generated economy lines also mix ability advice with internal analysis
language. Eleven use `reached-state`, eight use `descriptive`, three say
`ability unlock currency`, and two discuss a `winnable conversion`. Other
examples include `default projection`, `cost tracks`, and `supplied legal
ability-point sequence`.

These phrases are defensible in a research document and unnatural in a
Deadlock guide. Prefer direct instructions such as:

- “Level Flame Dash first, then Napalm.”
- “Queue Build adds CORE from left to right.”
- “Tier rows are choices; buy only what this match needs.”
- “This order uses common choices from ranked matches.”
- “Data: Aug 12 patch, Emissary-Eternus ranked games.”

The item hovers have the opposite problem: they are concrete about the item but
rarely connect it to the hero. All 304 final items retain a tactical sentence
within the Steam byte budget, and 299 sentences are textually unique. Yet zero
mention one of that hero's supplied ability names, only one mentions the hero,
and 186 use the word `observed`. The 183 prerequisite cards correctly carry
stats only, because they are purchase steps rather than final tactical choices.

Do not force an ability name into every hover. For each hero, identify the few
items that truly interact with a supplied ability or fight job and explain that
link in game verbs. Let general durability, movement, or economy items stay
plain. An eval should reward a real supported connection, not paraphrase
uniqueness; 299 different sentences are not 299 different tactical reasons.

Sentence length is not the main readability failure. Across 684 generated text
fields, the artifact contains 783 sentences and 13,056 words. The median
sentence is 16 words, the 90th percentile is 24, and only 48 sentences, or
6.1%, exceed 25 words. The problem is template and research-language density:
`observed` appears 190 times, `reference menu` 162 times, `candidate` 134
times, and 228 of 304 item instructions use the same semicolon-shaped
mechanic-summary form. Only 45 instructions contain `when`, `if`, `after`, or
`against`; none says `buy`, `sell`, `replace`, `skip`, `choose`, or `save`.
The next prose eval should measure supported decisions and repeated templates,
not merely sentence completeness and lexical uniqueness.

### Mechanics text needs deterministic unit validation

The first model stage is identity-closed but not mechanics-closed. Kit
admission requires exactly the four supplied ability IDs and names, then checks
only that each `tactical_role` and `scaling_hooks` string is nonempty.
`primary_role`, `combat_pattern`, `economy_tendencies`, `scaling_profile`, and
every synergy or uncertainty are also accepted as nonempty free text. The
second model stage receives this preliminary kit profile but not the full
per-ability mechanics packet, so an invented first-stage statement can become
the source for final prose.

A read-only adversarial admission check used the real Infernus context and
left every identity and ability row intact. It changed one role to claim
exactly `9999` fire damage and wall teleportation, named a nonexistent fifth
ability called `Moon Laser`, and said that ability doubled every supplied
ability. `validate_kit_response()` admitted all three strings. This was an
in-memory validator probe; it did not alter the reviewed kit or narrative
artifacts. A scan of those current artifacts found no unambiguous foreign
ability name, which is reassuring but cannot validate unnamed qualitative
mechanics.

The final synthesis validator has the same problem across its response. A
second in-memory probe changed Kelvin's build summary to say Frost Grenade
teleports through walls and deals `9999` damage, changed a CORE hover to say
Frost Core grants `90` seconds of invulnerability, and changed the CORE
category summary to say the item instantly kills every enemy hero. All three
statements passed `validate_response()`. They preserved the closed action IDs,
mentioned the expected item where required, ended in punctuation, and avoided
the small banned-language regexes. None was checked against
`selected_action_mechanics`, the ability packet, or a permitted numeric-value
set. The CORE hover is an installed player surface. The current build summary
is retained in preview/audit data, while standard category summaries are
replaced by deterministic text before installation; those two examples still
demonstrate validator scope, not three installed strings.

The typed evidence “language ceiling” does not close that gap. All 304 current
explainable CORE actions carry a descriptive claim and the same four allowed
terms: `adopted`, `more common`, `observed`, and `rate`. The generation prompt
receives that list, but `EvidenceClaim.validate_sentence()` is called only by a
unit test. More importantly, that method is not a whitelist: it rejects a
short causal-phrase list for non-causal claims. Production's global prose
validator independently rejects a slightly broader set of explicit causal and
analytics phrases, which is useful. In an in-memory replay, it correctly
rejected “improves win rate” but admitted “Buy Swift Striker when you can; it
boosts your damage.” Thus the metadata and DeepEval label should not be read as
deterministic claim-specific vocabulary enforcement. Bind assertions to
mechanics and claim type; do not merely wire the weaker test-only method into
the runner.

Make each ability role cite one or more supplied ability-mechanic fields. A
synergy should cite the involved ability IDs and the explicit mechanic that
connects them; otherwise it belongs in uncertainty. Reject numbers and ability
names outside those referenced records, retain the full records through final
synthesis, and require every final overview, action, and category claim to cite
the mechanics or policy fact it paraphrases. Add adversarial fixtures for a
fake number, mechanic, ability, item effect, and combo. The model may
paraphrase validated facts, but an echoed source hash and correct ability or
item name do not prove that its prose came from those facts.

### Reviewed narrative admission is weaker than generation

Even a stronger generation check would not protect the exact
`install-artifacts` path today. `load_narrative_catalog()` checks schema and
prompt versions, snapshot/context fingerprints, coverage, action identities,
and nonempty fields. `apply_narrative()` checks the corresponding guide and
context identities, category/action coverage, evidence references, and byte
budgets. Neither calls `validate_response()` or an equivalent semantic prose
validator. The narrative fingerprints describe the **input basis**, not the
output prose, and the artifact has no final-output digest.

A no-file mock of the real catalog reader changed one current entry's primary
role to “Instantly kills every enemy hero” and its first instruction to “This
item guarantees wins and grants 9999 damage.” The catalog loader admitted both.
Applying that catalog to the exact current bundle put the first sentence in the
Steam description and the second in Swift Striker's CORE hover. Building the
final `BuildPresentation` accepted both; its validator checks marker, tag,
title, category-description, and annotation sizes, not mechanics or claim
language. The altered build summary was admitted into review data but, as
expected, did not enter the installed description while a tactical profile was
present. No artifact, cache, or game file was edited during this probe.

The same mock passed the unmodified current strategy context into
`freshness._narrative_stage()`. It returned `CURRENT` with detail `validated`.
That stage calls only `load_narrative_catalog()` and compares the snapshot ID,
so status would affirm the adversarial prose rather than force review or
regeneration. Output identity and semantic validation must therefore be part
of the normal freshness contract, not only the generator command.

This directly contradicts the P0 requirement that malformed narrative entries
fail before preview or install. The current saved narratives pass the existing
generation check and the causal scan; this is a latent admission defect, not a
claim that the installed bundle contains those adversarial sentences.

Move the complete context-bound response validator into the package and call
the same implementation both before writing generated output and when loading
reviewed output. If human review may edit prose, validate the edited result,
then record a `narrative_output_sha256`, validator/schema identity, review
revision, and exact model provenance in the versioned bundle manifest. Bind
that output identity into freshness, projection, preview, and backup records.
Do not make the file immutable merely to preserve a model's first draft; make
every accepted revision explicit and mechanically admissible.

One reviewed Lady Geist hover says an enemy ability within `35mm` stores a
Restoration Stack. That string comes directly from Restorative Locket's pinned
description. The same record's structured cast-range and radius values say
`35m`, so the packet contradicts itself. A second source description says
Victor's Riptide slow lasts `2ss`; that typo did not reach the reviewed Victor
prose, but it was still supplied to the kit-analysis stage.

This is a boundary defect, not evidence that the model invented a mechanic.
`clean_mechanical_text` removes markup, template tokens, and excess whitespace
but preserves malformed units. The synthesis prompt prohibits invented numeric
effects, while response admission checks fingerprints, the closed action set,
item names, conditional contracts, prose limits, and causal language. It does
not parse numeric claims or compare them with the supplied structured
mechanics. The malformed `35mm` therefore passes exactly because it faithfully
copies bad source prose.

The packet contains only those two repeated-unit errors among 699 description
strings, but the structured catalog exposes a broader normalization hazard:
354 property values across 201 asset records already end in the same suffix
also carried in their `postfix` field, almost always meters. For example, the
value `35m` and postfix `m` must not be rendered by concatenation. Normalize
each value into a number plus a declared display unit, reconcile description
numbers against structured fields when the mapping is unambiguous, and reject
unresolved contradictions before fingerprinting or model generation. Add
regressions for `35mm`, `2ss`, and a legitimate value/postfix pair. Do not
weaken narrative validation to admit a malformed source packet.

Unit duplication is part of a wider, measurable source-text cleanup need. Of
the same 699 descriptions, 182 contain a space before punctuation, three expose
long binary-float values such as `25.199999`, and one repeats `Connection`
twice. These are not reasons to rewrite authoritative game meaning. Normalize
only mechanically safe presentation artifacts—spacing, a numeric value proven
equivalent to a structured field, and repeated units—while retaining the raw
source beside the normalized value for review and fingerprints.

The model packets also repeat catalog defaults at a scale that makes mechanic
ownership harder to see. The 38 synthesis calls send 304 final-item records,
representing 91 unique items, and 5,608 property instances. Of those
instances, 3,489, or 62.2%, have a value equal to `0`, `-1`, or null; 2,153
have a value exactly equal to their declared disable value. Exact property
objects repeat heavily too: 5,425 of the 5,608 sent instances belong to an
object that occurs more than once, while the unique-item catalog contains only
555 distinct property objects among 1,728 instances. For example, all 91
unique items carry `AbilityChannelTime` and `AbilityCharges`, and all 91 values
for both fields are sentinel-like. This does **not** prove every zero is
irrelevant: zero can be a meaningful value, and a scale function can give an
otherwise-zero property semantic weight.

The transport cost is measurable. Replaying the actual packet constructors
without contacting a model produced 1,630,245 bytes of kit JSON and 3,315,729
bytes of synthesis JSON across 38 heroes. That is 4,945,974 bytes of context
for one successful 76-call pass before retries, plus 159,182 bytes from
repeating the two prompts. The median hero receives about 42 KB in the kit
stage and 87 KB in synthesis. Cost is secondary to auditability: the important
item effect is buried among identical disabled defaults, while every retry
resends the same ambiguity.

Build a deterministic, typed **mechanic view** for each selected item. Retain
an active zero when the game definition or scale function makes it meaningful;
otherwise mark disabled/default properties explicitly instead of asking the
model to infer that from raw strings. Resolve units and upgrade inheritance,
keep the raw record alongside the view, bind each action to its own view, and
fingerprint both. A fixture must prove that normalization preserves a
meaningful zero as well as removing a genuinely disabled default. Packet size
should be measured after that correctness work, not used as the acceptance
criterion.

There is also no action-to-mechanic ownership check. Every one of the 304 CORE
actions inherits all eight item references from the set-level CORE evidence
claim, and the synthesis packet exposes all eight records together. Admission
requires the correct action name but does not prove that a described effect
belongs to that action instead of one of its seven neighbors. A numeric replay
of the current hovers found no cross-item numeric claim: aside from two queue
position numbers, every numeric token came from the named item's own packet.
That is reassuring output evidence, not a validator guarantee. Keep the
eight-item references on the joint-support claim, add one explicit
`action_mechanics_ref` per hover, and validate structured mechanic assertions
against that one record.

The fixed category descriptions are a good model of the desired brevity, but
the installed client supplies even more exact vocabulary: `Queue Build`,
`Quickbuy`, and `Optional`. Prefer `QUEUE BUILD • Default steps, left→right.`
and `OPTIONAL • Not added to Queue by default.` over the current `AUTO QUEUE`
and `Excluded from Queue`. The newer wording is short, behavioral, and matches
the buttons and tooltip the player already sees. Valve's original
[Quickbuy update][quickbuy-update] uses the same one-word name and separately
describes automatic purchase versus a purchase hotkey; do not collapse either
purchase mode into Queue Build.

### Metric labels need their units

Current item hovers use `PURCHASE WINDOW`, `WIN RATE`, and `PICK RATE`.
`PICK RATE` is especially confusing in a MOBA because it often means hero
selection. The actual unit is the share of eligible hero-player records that
bought the item.

The point-only win number also hides material sampling uncertainty. The frozen
match bootstrap contains 1,520 hero/tier/item cells. Its 95% interval width has
a 5.81-percentage-point median, 11.16-point 90th percentile, and 26.90-point
maximum; 232 cells, or 15.3%, are wider than ten points. These intervals still
do not include repeated-player clustering. A crowded hover should not print
two more endpoints on every card, but the guide should use a clear uncertainty
state: omit `BUYER WINS` or label it `LOW SAMPLE` when the interval is too wide,
and expose support plus the interval in an inspect/report command.

Clearer compact labels would be:

- `USUAL NET WORTH: 18k-29k`
- `BUYER WINS: 58.1%`
- `PLAYERS BOUGHT: 60.6%`

If space permits, “middle half of last observed net worth before purchase” is
clearer than “window.” It should not be called available souls. The build-level
description should say once that buyer wins are not item effects. Repeating the
statistical disclaimer on every card would create more clutter.

### The queue promise needs a client test

Every description currently says `TIER 1-4 never auto-queue`. The categories
are correctly serialized as optional. Valve's Shop Rework notes explicitly say
optional categories are not added to Quickbuy when a build is queued, and the
installed client now says the same: optional items are not included **by
default** when the build is added to the Queue. This is the intended contract
rather than a community guess. However, the later forum bug report says
automatic build loading can add optional items anyway.

Until the current client behavior is tested, “never” is too strong. The guide
can truthfully say “Tier rows are marked optional” and, if the bug reproduces,
tell the player to press Queue Build manually before relying on the queue.

### Archetype tags are valid but repetitive

The 38 builds use 12 archetype pairs. `Utility / Spirit` covers 12 heroes and
`Healing / Spirit` covers ten. Every hero receives `For Intermediate Players`
as the third tag.

The axis split is 24 Spirit, ten Weapon, and four Vitality builds. Functional
tags are 17 Utility, 13 Healing, four Crowd Control, two Mobility, and two
Melee. No build is tagged Damage, Headshots, or Debuff.

Current community data show that protobuf field 11 is used more broadly than
the 14-entry build-tag catalog. Every sampled public build carried exactly
three values. In the 22:20 UTC replay, 428 of the 1,140 slots matched standard
catalog tags, 366 matched current normal items, 318 matched one of the tagged
hero's own four abilities, nine matched Street Brawl items, and 19 were zero
placeholders. All nonzero values resolved to the pinned client. Ninety-two
builds repeated a value, so only 288 had three distinct tags. The current
[SteamTracking protobuf][hero-build-proto] defines only repeated unsigned IDs,
and the [Deadlock API response type][build-api-struct] likewise does not narrow
their meaning.

This mixed encoding is intentional. Valve's Shop Rework notes say a build gets
three tags and may use standard tags, hero ability icons, or icons of included
items. The current compiled tag picker independently exposes `Standard`,
`Abilities`, `Build Items`, and Weapon, Vitality, and Spirit item sections. The
managed selector is therefore too narrow in *choice*, not invalid in format. A
better selector can consider one clear play-style label plus the item or
ability that actually defines the plan, while still pinning and validating the
numeric asset used for the snapshot.

The managed selector currently permits only catalog tags. That is safe but
misses the public convention of featuring a defining item or ability. Test how
those mixed IDs render on a private build. If the current client preserves
them, a plan-specific ability or target item may communicate more than a forced
generic function label. Keep at least one plain taxonomy tag for filtering, and
never emit an asset ID that is absent from the pinned client snapshot. Require
three distinct nonzero tags in managed output even though public history proves
the native schema has admitted duplicate and zero slots.

The axis is sensibly based on final-item spend. The function is weaker: each of
the eight final item assets is assigned to the first matching text-keyword
rule, then spend is summed. The selector does not read the hero's intended
fight role or a validated tactical plan. It is reproducible, but “contains a
healing keyword” is not the same as “this is a healing build.”

The full current catalog exposes the concrete failure. `_asset_text` flattens
every string and key in the raw asset, including generic or disabled property
definitions. As a result, all 156 items match some non-Damage rule and none can
reach the fallback Damage class. Glass Cannon becomes Crowd Control because
the schema contains `slowpercent`; Extra Health becomes Crowd Control through
a dormant `silence` label; Monster Rounds becomes Healing through generic heal
metadata. The item-level distribution is 34 Healing, 32 Utility, 31 Mobility,
23 Crowd Control, 22 Melee, 11 Debuff, three Headshots, and zero Damage.

This explains the installed result—zero Damage tags—rather than proving every
CORE is support-oriented. Share one effective-mechanics view with the threat
classifier: active structured effects and validated descriptions only, never
the raw property dictionary. Then choose a build function from the eight-item
plan and hero role, with negative fixtures for obvious pure-damage and
pure-health items. Until that exists, a defining item or ability icon is more
honest than a forced function tag.

The source data can validate what a role label means, but the current frozen
extract throws those columns away. The current DuckLake `match_player` table
has 154 fields, including time-series player damage, teammate healing,
teammate barriering, self-healing, boss damage, accuracy, deaths, economy
sources, and objective events. The local deidentified `player_matches` table
retains only match/player slot, team, hero, lane, badge, outcome, time,
duration, final net worth, and calibration status. Purchases and team net worth
are retained separately; fight-role evidence is not.

A research-only repeat query illustrates why that gap matters. It used the
same timestamp, rank, ranked/normal, reward, outcome, and team filters against
the **current** DuckLake and normalized final teammate healing plus barriering
by match minutes. Only eight heroes had a nonzero median: Rem `447.5` per
minute, Paige `361.7`, Kelvin `322.3`, Dynamo `161.9`, Ivy `123.2`, McGinnis
`97.2`, Viscous `45.2`, and The Doorman `27.4`. Of the 13 builds tagged
`Healing`, only Rem, Viscous, and The Doorman are in that set. Ten Healing-tag
heroes have a zero median, while five higher team-help heroes are tagged
`Utility`.

That does not prove ten tags are tactically wrong. `Healing` may mean self
sustain, one optional kit effect, or the selected items rather than teammate
healing. The same query makes that distinction concrete: Victor and Lady Geist
had the highest median self-healing rates, about `1,274` and `881` per minute,
yet both are tagged Utility. The defect is that one unexplained keyword label
conflates **team healing**, **self sustain**, and **an item schema that happens
to mention healing**.

These numbers are not part of the frozen build evidence. The repeated source
query returned 169,201 eligible hero-player rows versus the archived extract's
148,338, an increase of 20,863 or 14.1% from late backfill under the same event
cutoff. Do not revise current builds from it. Instead, add a small archived,
per-hero role summary to a future evidence run and define separate game terms:
`TEAM HEALING`, `SELF SUSTAIN`, `DAMAGE`, `OBJECTIVE DAMAGE`, and `CONTROL`.
Check each summary across time and rank slices, then use it to audit a role
already supported by kit and selected-item mechanics. Never feed final-match
role stats into a live next-buy model; that would leak the future into the
decision state.

The fixed Intermediate tag adds no roster-level information. Before creating
multiple variants, define a small deterministic tag contract using final-item
spend, hero mechanics, active burden, and the plan's actual role. Abstain from
a functional or difficulty tag when those sources disagree; do not force all
three slots to look populated.

### Current evals do not measure plainness

The four deterministic DeepEval metrics were run against the current reviewed
artifacts for all ten default heroes. All 40 scores were 1.0: production
contract, closed action coverage, the production forbidden-language check, and
declared surface use all passed. The metric is named “evidence-language
ceiling,” but it delegates to `validate_response()` and therefore does not
enforce each action's supplied language-ceiling set.

That is good evidence that the artifacts are complete and avoid forbidden
causal claims. It also proves those metrics do not detect the wording problems
above. “Projection utilization” checks that a field has a consumer, not that a
player can understand or benefit from it.

Add a separate player-surface check for forbidden internal terms, sentence
length, direct game verbs, and unit labels. Keep it separate from the existing
causal and structural gates so clearer wording never weakens evidence safety.
A rendered-layout check belongs beside it; JSON completeness cannot detect a
clipped card.

## Repository audit

### What is already strong

- Steam mutation is isolated behind validation, backup, temporary write, and
  atomic replacement logic.
- Deadlock-running checks and user-data preservation rules are first-class.
- Analytics, model prose, reviewed artifacts, rendering, and installation have
  distinct stages.
- Frozen data classes and fingerprints make reruns and cache reuse explicit.
- Runtime dependencies are few and purposeful.
- Ruff, ty, pytest, lock checking, package checking, build, and wheel smoke
  testing are present in CI.
- GitHub Actions are pinned by commit SHA.
- The README, MIT license, contribution guide, security policy, changelog, and
  repository `AGENTS.md` are present.
- The current canonical tests are fast: 302 tests complete in about three
  seconds on this workstation.

### The Steam boundary is strong but recovery needs hardening

The out-of-scope fingerprint is stronger than its short name suggests. It
hashes every cache-root field, including unknown future fields, while removing
only managed blobs for the target account and target heroes. This protects
favorites, saved builds, selected-build state, unrelated private builds, and
opaque future data through temporary-file and installed-file validation.

The process guard also passed a live read-only reality check. While Deadlock
was open through Proton, `deadlock_is_running()` returned true. The process tree
carried both a native `steamapps/common/Deadlock` path through its wrappers and
the translated `S:\common\Deadlock` path on the game process, matching both
forms accepted by the guard.

No unit test protects those command shapes: every install/CLI test replaces
`deadlock_is_running()` with a Boolean stub. Split command recognition into a
pure helper and add the two observed Proton forms, a custom Steam-library path,
an unrelated command containing only `deadlock.exe`, NUL-separated arguments,
and a disappearing process. Failure to enumerate `/proc` itself should refuse
a write with a diagnostic rather than return “not running.” A false positive
is inconvenient; a false negative crosses the user-data boundary. This parser
coverage complements the mutation-time rechecks below and does not eliminate
their race.

The guard is not preserved through every error path. Install checks once at
entry and again immediately before its candidate replacement. If Deadlock
starts at that second check, `_install_replacement()` correctly refuses the
swap—but the outer exception handler then unconditionally calls the low-level
restore helper. That helper copies the backup into a temporary file and
replaces the live cache without checking the process. The existing
`test_install_refuses_if_deadlock_starts_at_mutation_boundary` exercises this
exact branch: its logical cache equality assertion passes because the backup
has the same content, while a forbidden filesystem replacement still occurs
after the mocked game state becomes running.

The user-facing restore command has the same time-of-check gap. It checks
Deadlock only at command entry; validation and temporary copying can take place
before `_restore_cache_file()` swaps the destination, and there is no second
guard at that mutation boundary.

Model install as an explicit state machine. Before the candidate has replaced
the cache, a failure must only remove the temporary file; there is nothing to
restore. After replacement, rollback may be required, but it must recheck the
process immediately before its own swap. If Deadlock has started, refuse the
second write and report the validated backup path plus the uncertain installed
state; do not silently violate the stronger “no writes while running”
invariant in the name of automatic recovery. The same guarded replacement
primitive should serve manual restore. Tests should count destination
replacements, not merely compare decoded values: the second-process-check case
must perform zero swaps, and restore must refuse if the process changes from
closed to running before its swap.

Byte preservation currently conflicts with updating a selected managed build.
The live cache contains 38 managed blobs in `Unpublished`, no managed blob among
25 `Favorites`, and three managed blobs among four `SavedLastUsed` entries. All
three saved copies differ byte-for-byte from the current managed copy for the
same hero, and `LastUsedBuilds` points to each saved copy's ID. Two identify an
older snapshot; the third predates the current snapshot line entirely. Updating
only `Unpublished` therefore keeps the selection pointer intact but can make the
client load an older managed guide for that selected hero.

The read-only freshness command is blind to this state. Its installed-cache
stage reads only `Unpublished`, indexes managed descriptions by hero, and
compares those descriptions with the expected snapshot and policy IDs. It does
not inspect `SavedLastUsed`, `Favorites`, or resolve `LastUsedBuilds`. The live
cache can therefore pass the canonical installed-cache check while the build
selected for play is one of the stale copies above. Treat these as two status
dimensions: **canonical managed build** and **selected managed copy**. A status
fixture should make `Unpublished` current, point `LastUsedBuilds` at an older
marker-owned `SavedLastUsed` blob, and require a specific “selected copy stale”
result rather than the current generic “validated.”

This is not permission to rewrite arbitrary saved or favorite builds. Define a
managed copy by the same marker, author account, and hero checks already used
for `Unpublished`. When that exact managed build appears in `SavedLastUsed` or
`Favorites`, refresh its presentation while preserving its existing build ID,
list position, favorite/saved membership, and `LastUsedBuilds` reference. Keep
every unrelated blob byte-identical. The out-of-scope fingerprint can omit only
those marker-owned target blobs from all three build sections, then separately
validate unchanged section shape and IDs. Add a fixture with one stale selected
managed copy beside an unrelated saved build: the selected ID must stay the
same, its managed content must become current, and the unrelated blob must not
move or change.

The canonical installed-cache status also collapses duplicates. Its helper
assigns each marker-owned `Unpublished` description into a dictionary keyed by
hero ID, so the last duplicate silently wins. An in-memory boundary probe put a
stale Kelvin managed blob before a current Kelvin managed blob. The helper
returned only the current description and `_installed_stage()` reported
`CURRENT: validated`, even though the installer would refuse the same two
managed entries as ambiguous. Accumulate entries per hero, require exactly one
canonical managed blob, and report duplicate IDs and list positions. Add both
orders of the stale/current pair as fixtures so list order cannot change
freshness.

Status also erases the reason cache discovery failed. `_run_status()` catches
every `CacheError` from `_location()` and does nothing; it then calls the
freshness layer with no cache path, which reports “Steam cache location was not
supplied.” A missing cache, two accounts, two paths for one account, an account
mismatch, and a malformed explicit location therefore become the same
misleading result. Status should remain read-only, but pass the captured
discovery error into an `UNAVAILABLE` stage and print its safe detail. That lets
the player distinguish “choose an account” from “Steam data is malformed”
without weakening installation discovery.

There is still a compare-before-swap race. `install_guides()` reads the cache,
builds a replacement from that snapshot, and later checks whether Deadlock is
running, but it never verifies that the live cache bytes are still the bytes it
originally read. A Steam Cloud update or another writer between those points
could therefore be overwritten. The backup may contain the newer bytes while
the replacement contains the older state, and the current out-of-scope check
would not notice because it compares the candidate with the old in-memory
snapshot. [Valve's Steam Cloud documentation][steam-cloud] says files are
replicated around application launch and exit, so Deadlock being closed does
not prove the Steam client is idle.

Before replacement, compare the live file's byte digest and stable file
identity with the originally read file. Refuse with a clear “cache changed;
retry” message if either differs. Add a regression test that changes an unknown
field after backup creation and proves the install never swaps the prepared
candidate into place. This is a small boundary hardening, not a reason to
redesign the installer.

An unchanged guide is not currently a no-op. `sync` always supplies the current
wall-clock timestamp, `update_managed_builds()` always re-encodes every managed
entry, counts it as updated, and proceeds through backup and replacement. The
stable build ID makes this idempotent in the narrow sense that it creates no
duplicate, but identical game content still changes bytes and asks Steam Cloud
to reconcile a file. Before any mutation, compare the intended managed
projection with the existing entry while ignoring only the deliberately
volatile timestamp. If every requested hero is byte-equivalent under that
contract, report `0 created, 0 updated`, create no backup, and do not touch the
cache. A real change must still take the full guarded path; this optimization is
valuable because the safest Steam write is the one an unchanged rerun avoids.

There is no interprocess lock around install or restore. Two CLI processes can
both read the same cache, prepare different replacements, and then swap them in
sequence. A timestamp-suffix race may make one backup creation fail safely, but
it is not a transaction lock. If both get past backup creation, the later
replacement can erase the earlier process's managed update. For disjoint hero
subsets, the second process's out-of-scope fingerprint still describes its
stale original, so its internally consistent post-write validation does not
recover the lost update. Hold an advisory lock keyed by the normalized cache
path from the first read through final validation or rollback. The live-byte
digest check remains necessary because Steam Cloud will not honor the CLI's
lock. The same lock should cover restore and backup selection.

The backup also includes `remotecache.vdf`, but `restore_latest()` restores only
`cached_hero_builds.kv3`. Its restore test reads `remotecache.vdf` after the
operation but never changes that file first, so it would pass even if the
restore ignored it—which is exactly the present behavior. All 24 inspected
backup directories contain the metadata file, and its build-cache entry stores
size, times, SHA-1, and sync state. Valve does not publicly document this
per-app `remotecache.vdf` format, so do not start copying it back based only on
its name. First define whether recovery promises payload-only restoration or a
coherent Steam Cloud metadata rollback, test the latter safely with Steam
offline, and make the command and test state the chosen contract. At minimum,
rename or narrow the current test so it does not claim to verify metadata
restoration.

Backup directories are keyed by Steam account ID, not by the exact cache
installation. The manifest records `cache_path`, but `restore_latest()` ignores
it and selects the lexicographically newest directory for the account. A user
who moves between native Steam, Flatpak Steam, or another library can therefore
restore bytes captured from a different installation. All 24 backups on this
workstation name the same native cache path, so no current backup is crossed;
the risk appears after migration.

The manifest also lacks a SHA-256 of the complete cache payload and copied
Steam metadata. `out_of_scope_sha256` is a decoded projection that intentionally
omits managed targets; it is not a backup-integrity digest, and restore does not
check it. `read_cache()` proves only that a chosen payload is structurally
decodable. A well-formed edited or partly stale backup can therefore pass.
Hash the source bytes and durable copy at backup creation, require them to
match, store both payload digests in the manifest, and validate the manifest
and digest before a backup is eligible for restore.

The restore command also checks for Deadlock only once, before selecting and
validating the backup. Unlike install, it does not recheck immediately before
the atomic swap, and it does not create a pre-restore backup of the current
cache. A wrong but well-formed “latest” restore can therefore discard the
current state without a direct undo point.

Validate the selected manifest's account and normalized cache path against the
destination, recheck the process boundary immediately before swap, and back up
the current destination as a separate pre-restore snapshot. Add a read-only
backup list with date, source path, payload hash, and snapshot identity, plus an
explicit selector for migrations. If fallback to the newest valid compatible
backup is desired, define that behavior; silently taking a different older file
would be surprising during recovery.

Backup privacy currently depends on the surrounding directory rather than the
backup operation. This workstation's `$XDG_STATE_HOME` is mode `700`, so the
observed private content is not exposed. Inside it, however, application and
backup directories are `750`, copied cache payloads inherit `750`, and copied
`remotecache.vdf` files inherit `755`; only atomically written manifests are
`600`. A custom state root with group or world traversal could therefore expose
private build text and account-scoped metadata. Create every backup directory
as `700` and payload as `600` independent of umask and source-file mode. At the
live destination, decide explicitly whether atomic install/restore preserves
the original safe mode or normalizes it; test that metadata contract alongside
the byte contract.

### Repository essentials

| Item | Status | Evidence |
| --- | --- | --- |
| README | Pass | Purpose, safety, install, use, development |
| License | Pass | MIT license and package metadata agree |
| Repository `AGENTS.md` | Pass | Safety, architecture, and release gate |
| Root `SKILL.md` | Gap by audit policy | No reusable agent workflow file |
| Contribution guide | Pass | `CONTRIBUTING.md` |
| Security policy | Pass | `SECURITY.md` |
| Changelog | Pass | `CHANGELOG.md` |
| EditorConfig | Gap | No `.editorconfig` |
| Markdown lint config | Gap | No repository Markdown linter config |
| Sonar config | Gap | No reproducible project scan definition |

A root `SKILL.md` is a project-convention opportunity, not a Python ecosystem
requirement. It would be useful only if it captures a repeatable workflow not
already covered by `AGENTS.md`.

### Tooling and automation

| Area | Status | Finding |
| --- | --- | --- |
| Dependency lock | Strong | `uv.lock` is checked and CI uses frozen sync |
| Formatting | Strong | Ruff format check covers the repository |
| Linting | Strong with gaps | Ruff ignores complexity rules |
| Type checking | Strong | ty uses all error rules |
| Tests | Strong with gaps | 302 passing tests; three offline data boundaries lack direct regressions |
| Packaging | Partial | Wheel smoke exists; source archives admit untracked files |
| Python versions | Partial | Metadata names 3.12 and 3.13; CI and release run only 3.12 |
| Release | Strong | Tag-driven release workflow exists |
| Code scanning | Partial | CodeQL exists; Sonar is not reproducible |
| Coverage | Partial | Evaluation coverage JSON is tracked; no code threshold |
| Markdown | Partial | Documents exist; no standard lint job |

An additional frozen, isolated Python 3.13 run built the package and passed all
302 tests in 5.09 seconds. That is useful compatibility evidence, but it does
not replace a CI matrix: future 3.12-only changes can still break an advertised
version unnoticed.

An isolated statement-coverage run measured 73% across the package and runtime
script. The safety boundary is comparatively strong: protobuf and KV3 encoding
were 96%, rendering and service orchestration were 90%, artifacts were 87%, and
cache handling was 84%.

The weakest areas were `offline/report.py` at 10%, offline API and extraction at
19%, `offline/analysis.py` at 27%, and the XGBoost runner at 43%. Coverage is not
correctness, but the result matches the function-size audit: the largest
research functions also have the least executed behavior in the normal suite.

This was an ad hoc `coverage.py` statement run in a temporary copy, not an
existing project quality gate. If coverage becomes a gate, set risk-based
module expectations rather than chasing one repository-wide percentage.

The observed failures also expose two sharper gaps than a statement percentage
can show:

- `tests/offline/test_late_game.py` has one happy-path inventory test. Its
  purchase and removal timestamps are distinct, so it does not exercise the
  equal-time sort, explicit self-removal, rapid upgrade chain, or 12-slot
  postcondition that failed on the production snapshot.
- The offline test suite has no direct test of `extract_cohort` or
  `_cohort_where`. The SQL boundary that admitted winner-only rows is therefore
  covered only indirectly, without a fixture containing a complete match, a
  six-winner/six-`NotScored` match, and a partially eligible match.
- `tests/offline/test_xgb_ranker.py` checks sampling, candidate membership,
  isolated component cost, train-only baseline counts, and the promotion gate,
  but never calls `load_hero_queries` or `_PurchaseSequence`. It therefore
  misses equal-time component expiry and the mixed-time inventory state. Its
  synthetic assets also set uniqueness explicitly instead of exercising the
  real omitted field.

These are ownership tests, not merely more lines to execute. Extraction should
prove that a match is admitted as a valid 12-player unit before any row enters
downstream tables. Inventory replay should prove source-removal and slot-limit
postconditions independently of item-ID order. These fixtures should fail on the
current implementation and pass without changing evidence thresholds. The
ranker needs a timestamp-bucket fixture that asserts one coherent decision
time, component credit, non-component sale behavior, and real asset defaults.

Two read-only security probes found no production-code emergency, but they did
find release and maintenance work:

- Bandit reported 23 findings: 20 possible SQL-injection warnings on local
  DuckDB f-strings and three subprocess warnings. The subprocess calls pass
  fixed Git argument arrays with `shell=False`. The SQL substitutions inspected
  here are validated cohort constants, integer hero IDs, or owned table/path
  values, so they are not remotely supplied query text. Parameterizing values
  and quoting identifiers at one DuckDB helper would still make that trust
  boundary explicit and remove a broad lint exception.
- An offline `zizmor` 1.29.0 pedantic scan reported three low-confidence
  checkout credential-persistence warnings across the workflows: one in CI and
  two in release. Both low-confidence cache-poisoning errors were in the release
  workflow. More importantly, its `verify` job builds and tests one
  distribution, then the privileged `github-release` job checks out again and
  independently runs `uv build`.
  The files uploaded to the release are therefore not the files that passed
  verification. Build once in the unprivileged verification job, record
  digests, transfer that artifact to the release job, disable dependency caches
  in the publishing path, and set checkout `persist-credentials: false` where
  Git credentials are not needed. This follows the cache-poisoning model
  documented by the [Zizmor audit][zizmor-cache].

The same pedantic pass reported five lower-priority workflow hygiene items:
three jobs have no display name, CI has no concurrency limit, and the release
job's `contents: write` permission has no explanatory comment. These are worth
cleaning up, but they do not replace the verified-artifact handoff.

Two independent local `uv build` runs against one unchanged working tree were
byte-identical. The wheel SHA-256 was
`7c1b512a8327e53269d152773688383c5767a2f0076f947c6836dc25edc32632`
and the source archive SHA-256 was
`22cb9abbfe2cfc525ac42fd23874296887ef72b7c47c27d032c041d9e4a23950`
in both runs. That is good fixed-input build-backend determinism, but it does
not close the workflow gap: the privileged job can check out a different ref,
resolve a different tool environment, or publish an unverified replacement.
Transfer the verified bytes anyway.

The source archive has a separate input-boundary defect. A later `uv build`
included this untracked report under `docs/`; its size and SHA-256 changed as
the report grew, while the wheel remained byte-identical. `check-manifest`
independently failed with this file listed as “missing from VCS.” There is no
explicit Hatch source-archive file list or `MANIFEST.in`. This matches Hatch's
[documented default][hatch-sdist]: without file-selection rules, its source
builder includes every file not ignored by version control. A release can
therefore contain local files that are absent from its Git commit. Define an
`only-include` allowlist for the source archive, build from a clean checkout,
and make
`check-manifest` (or an equivalent exact manifest comparison) fail before
publication. This report deliberately does not claim a final source-archive
digest: editing that digest would itself change the included archive.
An independent build from `git archive HEAD` isolates the effect: its wheel was
the same 241,575 bytes with the same SHA-256 as the working-tree wheel, while
its source archive was 541,200 bytes with SHA-256
`1d8d3192889497d721f7f4d2e5675b887166949be611a5096df5f1fdff4e138f`.
The working-tree source archive was 672,701 bytes. The code distribution is
stable; the extra non-versioned source input explains the archive difference.
The current GitHub release job begins with a fresh checkout, which lowers its
immediate exposure; the allowlist still protects local builds and any future
generated files in CI.

Both distributions pass Twine's metadata and long-description checks, and the
`pyproject.toml` structure passes schema validation. One metadata cleanup still
matters before publication: the project emits both `License-Expression: MIT`
and the legacy `License :: OSI Approved :: MIT License` classifier. PyPA's
[current project-metadata specification][pypa-project-metadata] deprecates
license classifiers under PEP 639 and permits build tools to reject this
combination. Keep the SPDX expression and remove only the legacy classifier.
Author and maintainer fields are optional under the same specification, so
their absence is not a release defect and does not justify exposing a personal
email address.

The actions themselves are pinned to full commit hashes and workflow
permissions are narrow, which is a strong baseline. The artifact handoff is the
missing link.

Python packaging metadata is otherwise consistent: the project requires 3.12
or newer, classifies 3.12 and 3.13, and builds a platform-independent wheel.
The clean wheel smoke test covers 3.12, and this workstation's complete gate
passes under 3.13. Put both named versions in the ordinary CI matrix; keep the
release build on the minimum supported version after that matrix passes. Add a
new classifier and job only when that interpreter is deliberately supported,
not merely because the open-ended version specifier allows installation.

That distinction is already observable on current Python 3.14. The exact base
wheel installed, displayed CLI help, and loaded both default schemas in a clean
3.14 environment. A frozen full-suite environment failed before collecting
tests because PyArrow 21 has no matching wheel there; its fallback source build
could not find an Arrow C++ CMake package. This is an analysis-dependency
installation failure, not an application test failure. Do not claim 3.14
analysis support yet. Resolve it through the coordinated PyArrow/scientific
stack upgrade already required above, reproduce the frozen research outputs,
then add the interpreter to CI and metadata together.

### Generated-state growth

The application state directory currently uses about 1.2 GB:

| State area | Current size | What drives it |
| --- | ---: | --- |
| Offline research results | 1.1 GB | Databases, Parquet data, and model files |
| Traces | 80 MB | One capped call-level trace dominates the directory |
| Current artifacts | 30 MB | Evidence and policy JSON |
| Steam backups | 3 MB | 24 recoverable cache snapshots |

Trace cleanup is implemented and intentionally retains the latest three owned
runs. No equivalent lifecycle is documented for offline result directories.
The two complete recent runs occupy about 372 MB and 710 MB; the largest files
are the raw DuckDB databases, purchase tables, and per-hero XGBoost models.

This is not an immediate disk-pressure problem, and Steam backups must remain
recoverable. It is nevertheless an ownership gap: the CLI creates large state
without explaining how to list, archive, or safely retire it. A future cleanup
command should show age, size, patch, and whether each run is referenced by the
current artifact bundle before offering deletion. Backup pruning should be a
separate, explicit workflow with a conservative minimum count; it must never be
coupled to routine synchronization.

The 24 backup manifests also provide a small longitudinal safety audit. They
span July 26 through August 17. Twenty-three of the 24 cache payloads have
distinct hashes, so this is mostly real recovery history rather than one file
copied repeatedly. The managed hero count moved through several partial sets
during early development, then remained at all 38 heroes for the latest 11
identity-rich manifests.

Those latest manifests each record 38 policy IDs, 38 projection fingerprints,
the source snapshot, rank range, and a hash of all out-of-scope Steam data. Two
source snapshots were installed more than once. Within each repeated snapshot,
the managed build-ID map stayed stable, which is good evidence that reruns do
not create another private build per hero. All 38 projection fingerprints did
change between those installs, despite the same source snapshot and policy-ID
map. That can be legitimate when reviewed annotations or the renderer change,
but the manifest has no explicit generation/review revision explaining it.

The fingerprint is also not complete enough to answer that question.
`projection_fingerprint()` hashes tags, category labels/options/descriptions,
item annotations and optional fields, plus snapshot and policy IDs. It omits
the tactical profile used in the first and third description lines,
presentation-owned wording, and protobuf-owned category dimensions. An
in-memory probe changed all three Infernus tactical-profile sentences: the
installed description changed while the projection fingerprint remained
identical. A Kelvin layout-only change to `STANDARD_CATEGORY_SIZES` would have
the same invisible identity. Serializer changes can also alter native bytes
without entering the hash.

Define one typed `BuildPresentation` that includes resolved width, height,
title, full description, ability changes, tags, categories, and item fields.
Hash that complete semantic value with an explicit renderer/schema version,
then encode it. Record both that stable presentation hash and the installed
wrapped-protobuf SHA-256 in the backup manifest. Use the semantic hash for
no-op detection and the byte hash for exact forensic comparison. A regression
must change only tactical prose, only a category dimension, and only ability
annotation, and require all three to change the presentation identity.

Across the full 24-manifest history, ten heroes changed local build ID during
three transitions. The manifests cannot distinguish a user deletion, client
rewrite, migration, or installer defect, so this is not evidence of corruption.
It is evidence that future safety reporting should state *why* a managed ID was
allocated or replaced and should compare the before/after managed set. A small
`created`, `updated`, `missing-before`, and `ID-reallocated` change ledger would
make the existing backup stronger without retaining personal gameplay data.

The whole generated bundle needs a visible lifecycle. `sync` atomically
replaces canonical `strategy-context.json` and `policies.json` **before** it
starts Codex. Each successful worker then rewrites canonical
`kit-profiles.json` and `narratives.json` before all requested heroes finish. A
preserved real aborted run has 38 requested hero IDs, 25 narrative entries, no
exclusions, and no field saying it is partial. The ordinary narrative and
bundle loaders correctly reject that coverage, so it cannot reach Steam; the
failure is retention and recoverability. A failed refresh can leave new
context and policy files beside partial kit/narrative files after destroying
the last complete review bundle.

Stage the generated context, policy, kit, and narrative files in a versioned
candidate directory, together with the exact content-addressed
`build-evidence.json` they reference. `refresh-evidence` currently replaces
that canonical evidence file on its own, which also makes the prior bundle
unloadable even though its other files remain. Write
resumable model state to an explicitly named partial file with requested,
completed, failed, prompt, model, and source identities. When exact coverage
and the full artifact-bundle loader pass, promote the directory through one
atomic `current` pointer or equivalent versioned-directory selection. Keep the
previous complete directory until retention policy removes it. Reuse may read
the partial candidate deliberately, but a reviewer and `status` should never
infer “checkpoint” from a coverage error. A fault-injection test should fail
after context write, after the first model result, and immediately before
promotion; every case must leave the prior `current` bundle loadable and
byte-identical.

Coverage validation has one smaller but concrete inconsistency. Build evidence
rejects duplicate requested hero IDs, but strategy context, policy, and
narrative loaders convert their coverage lists to sets or dictionaries before
checking uniqueness. An in-memory probe appended the same requested hero ID to
all three current documents, recomputed the context hash, and updated the
narrative header. All three validators accepted the duplicate. The bundle's
cross-file equality check would also accept it when each list contains the same
extra row, then expose only a set of expected heroes.

Excluded heroes have the same structural risk: context coverage uses a set,
while policy and narrative decoders assign rows into a dictionary, so a later
duplicate reason silently wins. The current artifacts contain no duplicate
requested or excluded IDs, and this cannot install a second guide because the
eventual hero maps are unique. It can make coverage and exclusion provenance
ambiguous, which conflicts with the stated malformed-artifact rejection rule.
Require unique positive requested IDs, unique excluded IDs, and canonical
ordering at every producer and loader. Add one duplicate-request and one
conflicting-duplicate-exclusion fixture to each artifact boundary.

Model-output reuse has a separate provenance defect. The README says reuse
requires an exactly compatible model contract, and the artifact headers record
the requested kit and synthesis models. The reuse functions, however, receive
only per-hero entries. Those entries carry a prompt version plus source/policy
hashes but no model identity. Loading an artifact therefore discards the old
header's model before deciding reuse.

If a user changes `--kit-model` or `--model` without `--force-narratives`, all
compatible per-hero outputs can be reused. The checkpoint writer then creates a
new header containing the newly requested model names, even though no request
to those models produced the reused prose. The result is not just hidden
cross-model reuse; it is a false artifact-level provenance statement.

Load and validate reuse from the complete prior artifact, including its model
contract. If cross-model reuse is intentionally permitted, preserve the actual
generating model per entry and report the newly requested model separately; do
not relabel old bytes. Otherwise invalidate the relevant stage when its model
changes. Add a two-run fixture in which model A creates the entries and model B
is requested: the test must either invoke B or retain explicit A provenance.
`--force-narratives` remains a useful override, but it cannot substitute for
the documented default contract.

Prompt identity has the same weakness. `prompt_version` is a manually updated
integer; neither the kit nor synthesis prompt bytes, the output-schema bytes,
nor the narrative runner source enter the reusable-entry identity. Changing a
prompt or schema without remembering to bump the constant can therefore reuse
old prose under the new run. The artifact header says only `codex exec` and the
requested model names. It does not record the Codex CLI version, resolved model
revision, output-schema hash, service tier, or runner hash. The locally
installed CLI was 0.147.0 during this audit, but the completed artifact cannot
prove that version generated it.

Hash the exact prompt templates and schemas and bind those hashes to each stage
entry. Record the runner commit or source hash and Codex CLI version at the
header, and preserve any model/request metadata the transport actually returns.
Keep the human version number as a release label, not the sole compatibility
key. A fixture should change one prompt byte and one schema byte without
changing the version constant and require reuse to stop in both cases.

### Read-only Codex is not an input-isolation boundary

The narrative runner already has several strong precautions. It launches
`codex exec` in a newly created empty temporary directory, selects the
`read-only` sandbox, uses an output schema, disables user configuration and
exec-policy rules, and makes the session ephemeral. The model remains outside
the deterministic Steam mutation boundary, and public community-build prose is
not included in its packet.

Those flags mean less than “the model can see only this JSON.” Official OpenAI
documentation describes `read-only` as allowing file inspection while denying
edits and unapproved commands. It also says `--ephemeral` only prevents session
rollout files from being persisted, `--ignore-user-config` still uses
`CODEX_HOME` for authentication, and `--ignore-rules` discards user and project
exec-policy rules. The output schema validates shape, not the factual source of
free-text fields. See the [official Codex sandbox documentation][codex-sandbox]
and [Codex CLI command reference][codex-cli-reference].

The subprocess inherits the parent's complete environment because no explicit
`env` is supplied. The empty working directory reduces accidental repository
discovery, but a read-only agent is still not a no-tool transformer and the
host filesystem is not a declared input allowlist. Game descriptions and item
text arrive from a remote API. They are benign in the retained pinned packet,
and the current client-data conformance check is reassuring, but the snapshot
does not yet bind the API origin or reject cross-origin redirects. A compromised
source string therefore has a plausible prompt-injection path to ask an agent
to inspect local files or environment state. The weak prose validator could
then admit arbitrary text under a valid item ID. This audit found no malicious
asset text or evidence that such access occurred; it is a missing containment
contract, not a reported breach.

Prefer a structured model call with no shell, file, search, or connector tools.
If the CLI remains the transport, run it inside an OS-level container or named
permission profile whose readable filesystem contains only the exact input and
schema, and pass a minimal allowlisted environment rather than the whole parent
environment. Do not describe `read-only` or `ephemeral` as confidentiality
controls. Bind source origin first, treat every remote string as untrusted data,
and add an adversarial fake ability description that asks for a local secret;
the test must prove no file is read and no injected instruction reaches an
accepted narrative. Mechanics-reference validation is still required because
tool isolation prevents local disclosure but does not make generated facts
true.

### Documentation needs an authority map

The completed `docs` directory uses about 620 KiB on disk. This report is about
338 KB, or 332 KiB of allocated space; the earlier documents use about 288 KiB
of allocated space. Most prose is concentrated in the policy requirements, the
August 8 strategy research, the August 13 usage audit, and this dated report.
Length is not the issue by itself. The problem is that a reader cannot reliably
tell which recommendations remain current.

There is now a concrete conflict:

- `deadlock-build-usage-audit.md` says to keep the fixed geometry, describes
  CORE as a `6+2` layout, and repeats that optional tiers never auto-queue.
- The August 17 live client displayed 12 complete cards in that same rectangle,
  then clipped Kelvin's cards 13-15. The fixed-size recommendation is no longer
  safe.
- The forum evidence also makes “never auto-queue” too strong until current
  client behavior is tested.

The README also contradicts itself about model execution. Its normal workflow
correctly says `sync` generates kit and policy explanations with Codex. The
lower-level walkthrough later says the separate narrative script invokes
`codex exec` and “the sync/install process never does.” Current `sync` imports
and calls that script's `main()`, which launches `codex exec`; only the
artifact-only install path avoids it. Replace the ambiguous sentence with
“`install-artifacts` never invokes Codex; `sync` may do so before the Steam
mutation boundary.”

The older strategy report already warns that historical defect lists must be
checked against current code, but the same treatment is not consistently
applied to later design decisions. Adding more prose without an authority map
will make this worse.

Use a short `docs/README.md` or equivalent index with these roles:

| Document kind | Authority |
| --- | --- |
| Requirements | Normative behavior and acceptance criteria |
| Backlog | Current work order and owner |
| Monitoring runbook | Operational response contract |
| Dated research | Evidence and decisions as of one commit or snapshot |
| Phase notes | Implementation history, not current product truth |

Every dated audit should record `as_of`, commit, artifact snapshot, status, and
what supersedes it. Do not rewrite historical measurements in place. Mark the
specific geometry and queue conclusions as superseded, then link to the current
decision. This report is also dated research; it should inform a requirements
change, not silently become a second normative specification.

### Architecture map

The main production flow is coherent:

```text
Deadlock API and offline evidence
              |
              v
     deterministic build plan
              |
              v
       exported game context
              |
              v
  model-written, validated explanations
              |
              v
      reviewed artifact bundle
              |
              v
 render -> validate -> backup -> atomic Steam install
```

The high-risk Steam boundary is appropriately deterministic. The main cleanup
work is inside the analytical and orchestration stages, not at the safety
boundary.

### Evaluation contracts are not production monitoring

A static import-graph walk from the CLI reached 39 of the 43 package modules.
The only substantive unreachable modules were `telemetry.py` at 753 lines and
`evaluation.py` at 906 lines; the other two were package `__init__` files. No
production command imports either module. Repository-wide search found no
runtime writer for `RecommendationEvent`, no producer or admission gate for
`EvaluationReport`, no monitoring command, and no caller of
`evaluate_monitoring()` or `off_policy_evaluation()`. The wheel nevertheless
ships both modules.

This conflicts with document status more than with the current CLI. The
requirements mark the evaluation, decision-log, monitoring, and OPE contracts
`Verified`, and the monitoring runbook is labeled `implementation-contract`.
Their proof is unit tests and a coverage JSON map. That proves deterministic
library behavior; it does not prove an operational signal exists, is retained,
or can select a compatible rollback artifact. The older strategy document more
accurately leaves logging, OPE, and monitoring as unchecked future phases.

The dormant contracts also need hardening before wiring. An in-memory probe
constructed `LoggedDecision` with behavior propensity 2.0; it was accepted and
reported a supported OPE result. Passing a clipping threshold of -1 then
produced negative inverse-propensity value. `RecommendationEvent` correctly
bounds its optional propensity at 1, so the two representations disagree. The
support check also asks whether each target action appears anywhere in the log,
not whether the behavior policy has support in the relevant decision-state
strata.

Choose one honest boundary. If this is near-term research infrastructure, move
it under an explicitly experimental package, label requirements
`library-implemented / not operational`, validate propensities and positive
clip values, and build one end-to-end deidentified log-to-report command before
claiming monitoring. If it is not on the near roadmap, remove the 1,659 shipped
lines and retain the requirements as design notes. Do not connect a synthetic
monitoring result directly to automatic Steam rollback; operational recovery
first needs the guarded, installation-scoped restore work above.

### Concentrated modules and functions

Largest production modules by source lines:

| Module | Lines |
| --- | ---: |
| `offline/analysis.py` | 1,865 |
| `offline/xgb_ranker.py` | 1,605 |
| `offline/report.py` | 1,103 |
| `mechanics.py` | 1,088 |
| `cli.py` | 1,037 |
| `build_evidence.py` | 990 |
| `policy.py` | 971 |
| `service.py` | 939 |
| `evaluation.py` | 906 |
| `artifact_bundle.py` | 836 |

The largest function is `offline.report.render_report`: 827 lines, about 120
statements, and 107 local variables. Other large functions include the
248-line cohort extractor, the 226-line sequence-model evaluator, the 188-line
hero context builder, and the 186-line CLI parser builder.

This does not prove those functions are incorrect. It does mean reviewers must
hold too much state at once, small report changes can disturb unrelated
sections, and focused unit tests are harder to write.

Revision churn does not yet provide a trustworthy second ranking signal. The
local Git history contains only six commits, all carrying the same author
timestamp. Within that shallow history, `api.py` appears in all six commits and
`service.py`, `strategy_context.py`, `cli.py`, and `narratives.py` appear in
five. The biggest raw line churn is in `offline/analysis.py`,
`offline/xgb_ranker.py`, `policy.py`, and `service.py`. Those results agree
loosely with the size audit, but six imported or rebased snapshots cannot show
long-term defect density. Preserve more granular history going forward; do not
justify a large refactor with these churn counts alone.

### Complexity checks hidden by configuration

Ruff's normal configured run passes. A read-only audit enabled the currently
ignored complexity families and found 33 findings:

| Rule family | Count |
| --- | ---: |
| Function complexity | 3 |
| Too many return statements | 1 |
| Too many arguments | 14 |
| Too many local variables | 10 |
| Too many statements | 3 |
| Too many positional arguments | 2 |

They cluster in `offline/xgb_ranker.py` (6), `offline/analysis.py` (5),
`offline/report.py` (4), `build_evidence.py` (3), and `service.py` (3).

Some ignores are justified. Binary encoding and atomic cache mutation often
need explicit linear code. The 827-line report renderer is not such a boundary
and should not receive the same exception without review.

These 33 findings are not reported as current Sonar issues. They are a local
maintainability probe using Ruff rules that the project intentionally ignores.

Three additional read-only probes put that result in proportion:

- Radon rated the codebase's average branch complexity `A` at about 4.4. Nine
  blocks rated `D`; none rated `E` or `F`.
- Vulture reported no unused code at its 80% confidence threshold.
- A `jscpd` token clone scan at a 10-line, 80-token floor found seven exact
  clone groups and 95 duplicated lines, or 0.38%.

The corrected Radon inventory contained 1,070 blocks: 994 scored 10 or lower,
46 scored 11-14, 21 scored 15-20, and only nine scored 21-26. The high-water
marks were narrative response binding at 26; build-evidence loading and CORE
annotation at 24; narrative packet assembly and policy-to-guide projection at
23; conditional-instruction validation, strategy-context assembly, and report
rendering at 22; and offline source capture at 21. This is the same small set
of ownership boundaries identified by the manual audit, not evidence for a
whole-project rewrite.

Clone counts are threshold-sensitive. A five-line sensitivity pass found 21
small groups and 205 duplicated lines, or 0.82%; a 10-line, 50-token pass found
ten groups and 129 lines, or 0.51%. Even the deliberately aggressive setting
does not show broad copy-and-paste architecture. Use the named component and
serialization duplicates as cleanup targets instead of chasing every tiny
structural echo.

At the stricter threshold, five of seven pairs are within
`offline/analysis.py`, one repeats patch-content normalization between the
online and offline API paths, and one repeats CLI orchestration. None touches
protobuf, KV3, cache replacement, or restore. Do not force a shared helper
across a user-data boundary merely to lower a clone score.

A second Vulture 2.16 pass at its deliberately noisy 60% threshold returned
101 candidates. Most were expected false positives: enum members, serialized
dataclass fields, and `NARRATIVE_FIELD_SURFACES`, which the eval package imports
indirectly. Manual call-site checks did confirm the larger test-only islands
described below. They also found two small unclaimed surfaces:
`canonical_artifact_digest()` has no repository caller, and
`TraceSession.write_failed` is never read even though the trace writer can
swallow a mid-stream I/O failure. Remove the unused digest. For tracing, either
warn after the context closes when writing failed or remove the unread property
and document that only `trace-summary` exposes an incomplete trace; leaving a
diagnostic bit that no command observes is not error handling.

The probes are not exhaustive. Manual control-flow review found an identical
second `return FreshnessStage("policies", ...)` immediately after the first in
`freshness._policy_stage()`. It is unreachable and has no behavior, but neither
the configured Ruff gate nor the Vulture threshold reported it. Remove the
line during the next implementation pass and add a pinned unreachable-code
check rather than using this one example to justify a broad cleanup.

This is not a broadly tangled codebase. The actionable complexity is
concentrated in evidence loading, strategy-context construction, narrative
binding, policy projection, source capture, and report generation.

### Sonar status

[Pull request 9][sonar-pr] reported that it eliminated all 108 findings from a
local Sonar scan over 90 Python files. The merged commit is the current
baseline, and its CI and CodeQL checks passed.

The GitHub record adds important limits. The pull request contains one commit,
no review, no inline discussion, and no issue-by-issue Sonar export. Its four
completed checks are the Linux gate and CodeQL for Python and Actions; none is
a Sonar check. The `108 → 0` result appears only in the author's pull-request
description. No Sonar scanner or retained scanner work directory is present on
this workstation either.

That refactor touched 49 files and added 4,701 lines while removing 2,596, a
net increase of 2,105 lines. Much of the growth made operations explicit and
added bounded concurrency. The size increase is still a reason to measure
module ownership and review cost rather than treating a zero-issue scan as the
end of maintainability work.

The result cannot be reproduced from a fresh checkout because the repository
does not contain:

- `sonar-project.properties` or equivalent scanner arguments;
- a pinned SonarQube or SonarCloud target;
- the quality profile and rule versions;
- exclusions and coverage import settings;
- an issue export; or
- a Sonar CI job and quality gate.

“Zero findings” should therefore be recorded as a point-in-time external scan,
not a repository guarantee. The next Sonar task is reproducibility, not another
blind cleanup pass.

### Consolidation opportunities

#### One component-upgrade expander

Component expansion exists in:

- `build_evidence._expand_component_path`;
- `offline.production_evidence._expanded_default_path`; and
- `offline.xgb_ranker._expand_component_path`.

Upgrade lineage is game mechanics and should have one owner, ideally the
mechanics layer. Offline training, evidence export, and projection should call
the same pure function. This reduces the chance that training evaluates one
path while Steam displays another.

#### One layout contract

Category names, item-count rules, expanded-path semantics, and serialized
dimensions currently live in different modules. A single typed layout result
should state:

- category purpose;
- automatic or optional behavior;
- items in display and queue order;
- visible card count;
- width and height; and
- capacity validation result.

The serializer should encode that result, not independently choose dimensions
from a category name.

#### One item-asset normalizer

The current asset response omits `is_unique` on all 156 standard-shop items.
`mechanics.ItemGraph` and the DuckDB extractor interpret absence as true, while
`offline.xgb_ranker._assets` calls `bool(item.get("is_unique"))` and interprets
the same absence as false. Consequently the experiment's `candidate_unique`
feature is false for every item and carries no information, even though its
candidate generator separately forbids buying an already owned item.

Normalize one typed item record at the API boundary, including defaults for
uniqueness, maximum count, category, active status, cost, tier, and component
IDs. Make mechanics, extraction, evidence, and experiments consume that record.
Current XGBoost tests set `is_unique=true` explicitly, so add a fixture using
the real omitted-field shape; synthetic fixtures should not hide source-default
behavior.

#### Remove the old aggregate guide path

The normal service calls `build_purchase_guide_from_evidence()` and never calls
`DeadlockApi.item_stats()` or `purchase_guide.build_purchase_guide()`. A
function-level call graph found the latter only in its unit test. The bucket
grouping, adaptive increment, horizon, aggregate-window, API-row conversion,
and tier-ranking helpers behind it call only one another. They are roughly 300
lines of a previous aggregate-API design that now looks authoritative because
it remains tested and public-looking.

That ambiguity conflicts with the repository's explicit rule to reject rather
than substitute aggregate purchase-event data for the player-match evidence
artifact. Remove the unused endpoint wrapper, aggregate builder, private helper
island, and tests during an implementation pass. Keep the small
`PurchaseWindow` representation and formatter used by current artifacts.
`wilson_score_interval()` is also used by the dormant telemetry module; if that
module is retained as experimental work, move the generic interval function to
one plainly named statistics utility rather than preserving the old guide
branch around it. If external consumers are intentionally supported, document
and deprecate this path first; the package currently declares no such API.

#### Do not keep a third purchase-decision engine in tests

The actual `recommend` command evaluates `SequencePolicy` and
`SituationalPolicy` from build evidence against `DecisionState`. Separately,
`policy.py` contains `EvaluationState`, `PolicyDecision`, four traversal
helpers, and `next_policy_decision()` for walking a `BuildPolicy` graph. No
production module calls that evaluator; only `test_policy.py` does. The two
state models and engines already disagree in scope: the real recommender knows
souls, purchase history, slots, active-item keys, IDs, and build-evidence
identity, while the test-only walker sees a generic observable dictionary,
owned IDs, learned abilities, and clock time.

Keeping both invites a future command to choose the simpler but incomplete
engine because `next_policy_decision()` sounds authoritative. Preserve
`BuildPolicy` as the validated static plan used by projection and narrative,
but remove its unused runtime evaluator unless there is a funded decision to
make it the one recommender and close every state/legality gap first. The
nearby `SpikeCard` type is likewise used only by its unit test and is not stored
in a build plan; the production breakpoint report should own a real
game-facing spike result if that feature is implemented.

#### Remove unclaimed compatibility helpers

Three generic artifact APIs—`ArtifactCompatibility`,
`validate_hero_document()`, and `load_fingerprinted_json()`—are referenced only
by `test_artifacts.py`. The live artifact chain instead has specific strategy,
policy, narrative, build-evidence, and bundle validators. Notably,
`ArtifactCompatibility` includes a model field even though the real narrative
reuse bug above does not consult it. Passing tests for the unused abstraction
can therefore suggest a model-compatibility guarantee the workflow lacks.

Delete these helpers and their isolated tests unless an external API contract
is declared. Also remove the test-only `summarize_duration_curve()`
compatibility alias and update its tests to the correctly named
`summarize_ending_duration_profile()`. Compatibility shims need a consumer,
version, and removal date; otherwise they are duplicate names inside a pre-1.0
application, not compatibility. The same function-level scan found
`offline.models.prior_snapshot_value()` and `phase_for_time()` only in their
unit tests; delete those two small abandoned helpers rather than treating test
coverage as production use.

The lower-threshold dead-code pass adds `ItemGraph.total_tree_investment()` to
that list: its only caller is a unit test and it simply returns the item's
catalog cost. `purchase_guide.calculate_tier_horizons()` has no caller at all
and belongs to the obsolete aggregate-guide island above. Treat
`EvidenceClaim.validate_sentence()` differently: its intended safety property
matters, but its implementation neither has a production caller nor enforces
the supplied language set. Replace it with the mechanics- and claim-bound
admission contract described above instead of preserving a reassuring name.

#### Split narrative generation by responsibility

[`scripts/generate_narratives.py`](../scripts/generate_narratives.py) is 1,903
lines and is imported at runtime by `cli.py`. The wheel explicitly packages the
generic top-level `scripts` directory.

Its two default schema paths depend on that same layout: the code walks to the
parent of installed `scripts` and opens sibling files under a generic top-level
`schemas` directory. Hatch force-includes all four repository schemas at that
wheel root. This works in the inspected wheel, but it couples runtime lookup to
the source-tree shape, gives two common directory names to the global
site-packages namespace, and ships the decision-state/log schemas even though
runtime code does not open them. The CI clean-wheel smoke invokes only
`--help`, which never checks either default response-schema path.

An audit-only clean Python 3.12 probe installed the wheel with runtime
dependencies, changed its working directory to `/tmp`, resolved the installed
default narrative and hero-kit schemas, read 3,137 and 2,061 bytes
respectively, and JSON-decoded both successfully. The current wheel therefore
works in this scenario; the concern is global namespace ownership and a
missing regression check, not a demonstrated missing-file defect.

`check-wheel-contents` independently flags the same shape: W005 for the common
top-level library name `scripts/`, W009 for multiple top-level library entries
(`deadlock_build_sync/`, `scripts/`, and `schemas/`), and W010 because the
top-level `schemas/` directory contains no Python module. These are packaging
warnings, not an import failure, but they provide a standard regression check
for the proposed namespace cleanup.

Move runtime code into `deadlock_build_sync` and divide it into game-named
parts: prompt construction, response validation, Codex process execution,
retry/concurrency control, and checkpoint reuse. Keep a thin script only as a
developer entry point if one is still useful. Put the kit and narrative
response schemas under a namespaced package-resource directory and resolve
them with `importlib.resources`, while retaining explicit path overrides for
development. Keep documentation-only schemas in the source archive unless a
supported installed workflow consumes them. The wheel smoke should load and
JSON-decode both default runtime schemas from `/tmp`, then run the existing
deterministic response validators on minimal fixtures without invoking a
model.

This removes the surprising package boundary without adding a dependency.

#### Split report data from report text

`offline.report.render_report` should first build small typed section results,
then render those results. Suggested game-facing sections include sample,
items, purchase order, abilities, matchups, and validation. The split should
preserve current output and begin with characterization tests.

#### Remove the policy serialization back-edge

`policy.py` lazily imports `policy_codec.py`, while `policy_codec.py` imports
policy types at module load. This is a two-way source dependency, not a
module-initialization cycle: an independent `pydeps --show-cycles` pass reports
none because the lazy calls occur only after `policy.py` has loaded. It is
still the repository's only observed production back-edge of this form and
makes serialization ownership harder to follow.

Choose one direction: game plan types remain free of serialization, and the
codec owns conversion; or move the codec beside the types behind one public
module. Lazy imports avoid a runtime crash but do not make ownership clear.

#### One state-directory helper

XDG state-home resolution is repeated in `cache.py`, `cli.py`, `tracing.py`,
and `offline/cli.py`. A tiny internal helper is enough. Adding `platformdirs`
for four simple Linux-first call sites would cost more than it removes.

#### One canonical JSON and hash helper

`snapshot.py` and `offline/config.py` both define canonical JSON and JSON hash
helpers. Atomic JSON output also has separate implementations in `artifacts.py`
and `offline/production_evidence.py`, while offline source capture has a plain
JSON writer.

Share the byte-for-byte canonical encoding and digest logic. Keep Steam cache
replacement separate because it has stronger backup and validation duties.
Offline files that are reusable after interruption should use the shared atomic
writer; disposable raw downloads may remain simpler if their owner explicitly
refetches malformed output.

That shared boundary should also be **strict JSON**, not merely deterministic
Python JSON. Python documents that its default encoder and decoder accept and
emit `NaN`, `Infinity`, and `-Infinity`, even though those tokens are not valid
JSON; it also keeps only the last value when an object repeats a key.
[RFC 8259][rfc-8259] excludes non-finite numbers and says object names should
be unique, while [Python's `json` documentation][python-json] exposes
`allow_nan`, `parse_constant`, and `object_pairs_hook` as the relevant control
points.

This is an observable admission defect, not only a theoretical library
default. An in-memory adversarial probe changed a real policy claim's estimate
to `NaN`; `EvidenceClaim.from_dict()` admitted it and the normal encoder wrote
the literal token. A complete policy with an infinite estimate likewise passed
`validate_policy_artifact()` after its policy ID was recomputed. A strategy
context with a `NaN` duration also passed after its documented hashes were
recomputed. `build-evidence.json` is stronger: its typed numeric decoders
explicitly require finite values. A digest proves which bytes or values were
seen; it cannot make an invalid numeric domain valid.

The retained state is currently clean at the application boundary. A strict
scan found zero non-finite values and zero duplicate keys in the five current
production artifacts. Across all 331 saved `.json` files, the only exceptions
were 67 literal `-Infinity` split thresholds in 28 of 38 XGBoost model files.
All 38 models loaded successfully with XGBoost 3.3.0. Those files belong to
XGBoost's stable model format and should be hashed and loaded as opaque vendor
artifacts, not passed through the application's strict JSON codec.

Make the shared app-owned encoder use `allow_nan=False`; make reusable-artifact
decoders reject `parse_constant` values and repeated names; and require finite
floats in the policy codec and semantic context checks. Add one fixture for
each of `NaN`, positive and negative infinity, and a conflicting duplicate key
at every reusable app-owned boundary. Apply the same strict decoder to remote
evidence before semantic parsing; hashing ambiguous raw bytes does not make
last-key-wins or non-finite interpretation safe. Keep a separate byte-oriented
model loader and content digest for XGBoost files. This both closes the
malformed artifact gap and avoids misclassifying valid vendor models by
filename alone.

#### Normalize artifact ownership without weakening identity

All 38 policy objects in `policies.json` are exactly duplicated inside
`strategy-context.json`. Their compact form occupies about 2.64 MB; the
pretty-printed policy artifact is 4.42 MB, and the complete strategy context is
8.04 MB. Within the policy objects, evidence claims account for about 2.20 MB
because cohort and snapshot fields repeat on every claim.

The full `build-evidence.json` is 18.74 MB. Its largest compact hero sections
are purchase-order rules at about 5.09 MB, rejected situational-policy audits
at 3.90 MB, and item summaries at 1.55 MB. These data are valuable for audit,
but every downstream stage does not need every byte.

Keep the full build-evidence file as the authoritative research record. Let the
policy artifact own executable plans and claim records. Let strategy context
carry the policy ID, small policy summary, explainable actions, and Steam
projection. The synthesis function already reduces the full policy to variant,
kit ID, strategic role, and abstentions before calling the model.

At bundle admission, deterministic code should join the exact policy artifact
by policy ID and verify its hash. Do not replace content with an unchecked file
path or let the model resolve references. This reduces duplicate parsing while
preserving closed, fail-closed identity checks.

#### Bind projected behavior back to policy and game assets

`load_artifact_guide_bundle()` verifies CORE and option item IDs against build
evidence and the policy, but it does not compare the projected cards'
`required_flex_slots`, `sell_priority`, or `imbue_target_ability_id` back to
the policy nodes. `_optional_int()` accepts any nonnegative Python integer,
including values outside the game's domains. The build-tag check similarly
requires three positive IDs and the expected class positions, but it cannot
prove that an ID, class, and label are one record from the hashed source
catalog because that catalog body is not retained.

An in-memory probe changed final CORE Torment Pulse from no sell priority to
100, recomputed every documented context and narrative-basis hash, and loaded
the complete current four-file bundle. The resulting Kelvin guide carried the
priority while its policy node still carried `None` and its policy ID was
unchanged. Separate probes admitted `required_flex_slots=999`,
`sell_priority=101`, unknown imbue ability `999999`, and arbitrary build-tag ID
`999999`. These values would reach `BuildPresentation`; its checks do not
validate their game domains. No saved artifact or Steam file was changed.
The current production projection has no Extra Slot requirement, sell
priority, or imbue target on any card, and its resolved tags match the current
catalog, so this is a latent boundary defect. A complete positive replay found
zero discrepancies: all 38 selected ending records and shares matched
`build-evidence.json`; all 304 policy-backed final-card occurrences matched
their policy behavior fields; and the other 1,701 component or reference-menu
card occurrences carried none of the three behavior fields.

The same trust gap affects displayed support. A re-fingerprinted Kelvin context
changed the selected ending from 109 records to one record and loaded while the
unchanged `build-evidence.json` still contained the 109-record candidate.
Another changed final-branch and every decision-support value to one; after
updating the documented kit/context hashes, the same policy ID loaded and the
player description would report tail support `n=1`. CORE support can be
recomputed from the retained build evidence. Ability support cannot currently
be reconstructed offline because only response hashes, not the source bodies,
were archived; this is a concrete consequence of the evidence-retention gap
described below.

Self-consistent hashes make accidental crossing detectable; they do not prove
semantic equivalence between independently represented fields. Reconstruct one
typed projection at admission from policy, build evidence, mechanics, and the
resolved build-tag catalog, then compare the complete value before narrative
text is applied. Require the Extra Slot field to be empty until the native
contract above passes; afterward allow one through three and normalize zero to
off. Require sell priority off or 1-100, and an imbue target drawn from that
hero's exact ability set and allowed by the item. Expanded prerequisite cards
have no final policy node, and current reference-menu cards have no admitted
conditional node, so
derive behavior from the item graph or a closed rule and otherwise require it
to be empty; do not inherit an unreviewed field from context. Archive the small
resolved tag records used by each build, not just the standard-catalog hash, so
ID/kind/label agreement is checkable offline. The current managed contract may
require all three to be standard tags; a future icon tag must instead resolve
to the hero's ability or a pinned current item, as the native picker allows.
Recompute ending support from
`build-evidence.json` and rebuild ability support from archived API rows. The
final typed presentation and byte digest recommended above should become the
only values allowed across the Steam boundary.

#### Move audit-only matchup rows out of normal sync

Normal generation makes separate same-lane and whole-team hero-counter API
calls and embeds 2,812 hero-pair rows—74 per hero and about 1.18 MB in compact
JSON—into strategy context. These rows contain wins and broad combat, farm,
net-worth, and objective totals. They are hero-versus-hero aggregates, not
evidence that a particular item counters that opponent.

No current build choice, policy action, renderer, or prose stage consumes the
rows. `synthesis_context()` deliberately omits `matchups`, and a unit test
asserts that omission. The current zero-rule counter result comes from the
separate offline item-opportunity analysis. Nevertheless, direct matchup rows
remain in the narrative and full-context fingerprints, so a large audit-only
payload participates in regeneration identity without supplying a fact the
model can explain.

Keep these rows in the offline research report if their role remains audit and
hero context. If a later feature uses them, derive a small, validated reference
with a named question and uncertainty, then supply only the referenced rows to
the relevant deterministic decision. Do not feed all pairwise aggregates to
the model or call them item-counter evidence. Until then, removing their two
live calls and 1.18 MB projection from normal sync is cleaner than preserving a
future-looking field with no consumer.

#### Make a completed offline run actually frozen

The offline CLI freezes its query bounds, but not the files behind a run ID.
`RunPaths.create()` opens an existing directory, `_manifest()` reuses its
original cohort, and `extract` or `all` then overwrites the raw asset JSON,
DuckDB tables, and Parquet exports in place. `capture_sources()` always selects
the latest client version, not a client pinned in the existing manifest. A
rerun can therefore combine the old as-of cutoff with newer assets while also
destroying the bytes that produced the earlier report. The original
`generated_at` remains while `completed_at`, source hashes, and stage fields are
replaced, so the manifest is not an append-only history either.

The retained workstation evidence illustrates why names matter: completed runs
`20260814T141412Z` and `20260815T150504Z` are pinned to clients 6677 and 6679,
respectively, while an earlier run directory is a partial manifest with no
sources or completion timestamp. There is no evidence that either completed
run was overwritten; the code path simply permits it.

Refuse writes to any completed run ID. Resuming a failed run should admit only
missing stages after verifying hashes of every prerequisite; replacing any
stage should require a new run ID derived from the frozen cohort and resolved
source identities. Include raw assets, API bodies, the analysis database,
tables, and reports in a final content manifest, then seal it before export.
The current `frozen_data_sha256` covers only `data/*.parquet`, despite the
production export also reading raw assets, the DuckDB database, and tables.

The producer-source check has a related false guarantee. In a checkout,
`_repo_identity()` hashes `git ls-files -s`, which describes the **index**, and
stores `git status --short --branch`, which describes dirty paths but not their
contents. An isolated Git probe modified the same tracked Python file twice:
before and after status were both `M producer.py`, and the index hashes were
identical even though the executed bytes changed. The producer would report
`producer_source_unchanged: true`. Untracked importable code has the same
problem. In an installed wheel it hashes package Python files, but still omits
the package version, lock/dependency environment, and native library versions
used by DuckDB, Polars, XGBoost, and PyArrow.

The cleanest rule is to refuse a dirty checkout for a production evidence run,
record commit and lockfile identities, and hash the actual imported package
files before and after. If dirty research runs remain useful, hash their exact
worktree bytes and label them non-promotable. Record Python and relevant
package versions so “same producer” means the computation that ran, not the
staged Git snapshot.

#### Archive the online evidence that selects abilities

The snapshot manifest records exact request parameters, response SHA-256, byte
count, and semantics for every generation input. That is strong identity
evidence, but not a replay source. The current manifest describes 44.74 MB of
responses: 18.74 MB is the embedded build-evidence artifact, 19.12 MB is live
ability, duration, and matchup analytics, and the rest is assets, patch data,
and a Steam profile response. Only the item-side build evidence has its full
raw source chain archived in the offline run.

The effect is visible in this audit. At 21:53 UTC, repeating the same ability
filters and frozen upper timestamp returned 31,272 complete paths instead of
the artifact's 30,690. All 38 selected orders remained stable, which is a good
result, but every decision-support vector changed. The original hashes prove
that the response changed; they cannot reconstruct the alternatives that
produced the admitted ability order. `strategy-context.json` preserves the
selected result, so installation remains deterministic; analytical review and
exact regeneration do not.

This is 54 remote response bodies in the current all-hero run. Thirty-eight
per-hero ability-order bodies contribute 17.95 MB by themselves; their observed
fetch window was about 4.6 seconds. The current
[machine-readable API contract][deadlock-openapi] requires one `hero_id` for
that route, so the 38-request shape is not a missed client-side batch option.
Do not add concurrency machinery merely to hide a few seconds. Preserve those
volatile bytes first; if the producer later offers a real multi-hero evidence
route, compare its row semantics and hashes before switching.

Archive compressed response bodies for deidentified analytical and asset
routes, or extend the offline producer so the guide service consumes one
content-addressed evidence bundle. Retain request, semantics, and hash beside
each body. Do not archive the Steam profile response with research evidence.
This adds modest storage compared with the 1.1 GB offline run and turns
“frozen” from a parameter promise into a replayable source promise.

#### Make patch and asset discovery one coherent boundary

The run freezes analytics at one upper timestamp, but discovery of the game
state is sequential rather than atomic. `generate_guides()` resolves the newest
client version, then fetches ranks, heroes, items, and build tags, and only then
fetches the newest patch-feed entry. The chosen client version is cached after
the first call. If a client or patch update lands during those requests, the
manifest can faithfully hash every response while still describing a mixture
that never existed as one resolved boundary.

This is not a reason to substitute an older patch or silently retry with a
different cohort. Treat discovery as an optimistic transaction: resolve the
patch and client at the start, fetch all version-pinned assets, then query both
discovery endpoints again before admitting the snapshot. If either identity
changed, discard the candidate run and restart from a new cutoff or fail with a
clear “game data changed during collection” message. Record both checks. A
fixture should move the patch or latest client between the two reads and prove
that no mixed snapshot reaches guide generation.

The explicit `--as-of-timestamp` remains an analytics cutoff, not a complete
historical-replay switch. More importantly, the online and offline pipelines
currently disagree about even the patch side of that contract. The offline
producer's `_patch_at()` discards feed entries published after the frozen
cutoff. The online client's `current_patch()` does not inspect
`as_of_timestamp`; it always selects the feed's newest publication. With the
default epochs that usually fails later because the future patch boundary is
after the analytics cutoff. With explicitly configured older epochs it can
instead create a manifest whose patch was published after its claimed as-of
time. Filter online patch candidates by the cutoff and reject a feed with no
eligible entry. Add both default-epoch and configured-epoch regression
fixtures.

Selecting only by publication time is also wrong when the feed mirrors an old
post. The live `/v2/patches` response inspected on August 17 contains the
official “Minor Update - 06-30-2026” Steam entry at June 30 17:22 UTC and a
forum entry titled “06-30-2026 Update” at July 28 20:28 UTC. The forum body is
an unfurl of that same June 30 Steam URL. Four minutes earlier, at July 28
20:24 UTC, Valve published the actual July 28 minor patch. `current_patch()`
would therefore have selected the mirrored June 30 notes as the new current
patch, reset the analytics boundary to July 28 20:28, and hidden the real July
28 update until another later entry arrived. The current August 12 selection
is not affected because it is newer than both entries; the feed still proves
the selection rule is unsafe.

Canonicalize entries before taking the maximum. When a forum post embeds or
links an already known official Steam announcement, retain it as mirror
provenance but give the patch the original Valve identity and publication
time. For genuinely independent forum-only notes, retain the forum identity.
Record why two records were merged, and fail on ambiguous
same-title/different-content cases rather than guessing. The feed also contains
a “Matchmaking Update,” so decide explicitly which source classes start
gameplay, asset, rank, or matchmaking epochs; do not make a title substring the
hidden policy.

Even after that correction, reproducing an older run requires the matching
explicit client version and archived patch/evidence bundle. State that
distinction in CLI help so “as-of” is not read as “resolve every dependency as
it existed then.”

Source identity also stops at the route path. `JsonHttpClient` follows
redirects and returns the final absolute response URL, but `DeadlockApi`
discards that URL when it records evidence. The manifest therefore carries
`/v1/...`, parameters, content hash, and semantics without the configured API
origin or any redirect target. Two mirrors returning the same bytes receive the
same snapshot identity, and an upstream cross-origin redirect is not visible to
a reviewer.

Record the requested absolute URL and final URL, or at minimum their normalized
origins, beside every response. Reject a cross-origin redirect by default;
allow a reviewed mirror only through an explicit source setting that
participates in the snapshot identity. Exact response bytes remain necessary,
but they do not answer where those bytes came from.

The shared client also has no response-size boundary. `httpx.Client.send()`
buffers the complete decompressed body, `response.json()` creates the decoded
object, and only then does the recorder retain a hash and byte count. A timeout
limits elapsed waits, not bytes or decompression growth. Malformed JSON remains
retryable, so one oversized invalid response can be downloaded and parsed up
to three times.

The current complete online snapshot fetched 25,995,225 HTTP response bytes;
the local 18,743,261-byte `build-evidence.json` record is excluded from that
number. Items were the largest single response at 5,771,301 bytes. The 38
ability-order calls totaled 17,947,662 bytes, with a 421,684-byte median and
981,119-byte maximum; hero assets were 971,345 bytes and each counter response
was about 0.52 MB. Those are healthy baselines, not safe maxima.

Give each declared route a generous reviewed decompressed-byte ceiling, stream
chunks into that bound, and reject before JSON decoding when either declared or
actual size exceeds it. Record the rejection without retaining a partial
artifact. Test missing and dishonest `Content-Length`, compressed expansion,
an exact-limit response, a one-byte overflow, and a truncated retry. Keep
limits separate from semantic row-count checks: a tiny malformed response and
a legitimate growing roster can both fit under a byte cap.

#### Remove the Steam persona from analytical identity

`generate_guides()` uses `account_id` only to call `/v1/players/steam`. The
profile response and account parameter then enter the snapshot fingerprint.
The returned persona is passed into `install_guides()`, where it is explicitly
discarded, and protobuf author identity uses the numeric account ID instead.
`install-artifacts` likewise refuses when it cannot resolve a local persona,
even though the installer never consumes that string. Preview is the only
meaningful display use.

A profile-name or avatar change can therefore invalidate every snapshot while
changing no game evidence, and the same generic guide research gets a different
identity for each Steam account. Remove the profile route from snapshot
records and remove `persona` from the cache API. Keep numeric author account ID
strictly inside the Steam encoding boundary. If preview should greet the user,
resolve the display name after snapshot construction and treat failure as a
cosmetic warning, not a build or restore blocker.

The unused dependency also makes read-only commands less composable.
`preview` and `export-context` unconditionally discover a local Steam cache to
obtain its account ID before generation. That prevents a clean checkout, CI
runner, or analyst without Steam from producing or reviewing the same generic
context. `generate_guides()` needs the number only for the persona call above;
the preview path additionally passes it through protobuf solely to exercise
structural encoding. Use a documented synthetic author ID for that read-only
serializer check, or accept an explicit optional ID when exact preview bytes
matter. Discover the real account only for installed-cache status,
installation, backup, and restore.

The privacy boundary is otherwise working as intended. A read-only catalog of
the 710 MB analysis database found only its local `main` database and nine
derived tables; no remote attachment survived. It contains no raw account,
Steam, persona, email, or IP column. `hero_account_counts.unique_accounts` is
only the per-hero aggregate used for breadth checks. By contrast, the local
numeric Steam account ID appears as the profile-request parameter in three
current analytical artifacts and one aborted narrative artifact. It also
appears, appropriately, in the account-scoped backup directory and manifests.
Removing the unused profile request would narrow analytical artifacts without
weakening the account ownership needed for Steam backup and encoding.

#### Split CLI parser construction

The ten subcommands are a reasonable Unix-style interface, but the 186-line
parser builder and 1,037-line module make unrelated command changes collide.
Use one builder per game action while keeping the zero-argument `sync` flow
obvious.

### Dependency assessment

Current runtime dependencies are sensible:

- `httpx` centralizes connection pooling, retries, timeouts, and testable JSON
  requests.
- `keyvalues3` replaces risky custom handling for the KV3 boundary.
- `cattrs` gives strict typed conversion for policies, though its current use
  is isolated.

A direct installed-license inventory found only permissive licenses across the
declared runtime, analysis, test, and development packages: MIT, BSD, Apache,
and PSF-family terms. `keyvalues3` is the one metadata wrinkle. Its 0.7 wheel
does not declare `License` or `License-Expression`, so automated inventory
reports `UNKNOWN`, but the wheel contains the full MIT license file. This is not
a reason to replace a useful boundary package. Configure any future SBOM or
license gate to inspect packaged license files, and ask upstream to publish a
machine-readable expression so the exception does not become permanent.

The large scientific stack is correctly optional. NumPy, Polars, PyArrow,
SciPy, scikit-learn, XGBoost, DuckDB, and Matplotlib belong to offline research,
not the normal install path.

Static imports initially made PyArrow and pytz look unused: neither name
appears in repository imports. Isolated removal experiments showed that both
are real integration dependencies. Without PyArrow, the offline suite fails
when DuckDB registers a Polars frame because Polars converts it through Arrow.
With PyArrow present and pytz absent, all 39 offline unit tests pass, but a real
query that materializes `player_matches.start_time` fails because DuckDB needs
pytz for its time-zone-aware Python value. Keep both explicit. Add a small
timestamp materialization test so a future static cleanup does not remove pytz
again; the Polars-to-DuckDB test already protects PyArrow.

A scoped `deptry` pass found no remaining dependency issue after declaring
`deadlock_build_sync` and the currently shipped `scripts` package as
first-party, mapping the `scikit-learn` distribution to its `sklearn` import,
and excepting PyArrow and pytz from only the unused-import rule. Those two
exceptions are supported by the execution probes above, not by convenience.
If dependency lint becomes CI, commit that mapping and group configuration;
the unconfigured scan otherwise reports 21 mostly false findings and would
encourage exactly the unsafe removals those probes disproved.

`pip-audit` found no known vulnerabilities in the locked runtime dependency
export on 2026-08-17. This is a time-specific database result, not a permanent
guarantee and not a reason to add packages casually.

The all-extras development export did produce one advisory: locked PyArrow
21.0.0 is in the affected package range for PYSEC-2026-113, fixed in 23.0.1.
The upstream advisory says the use-after-free requires Arrow C++ IPC-file
pre-buffering and that this functionality is not exposed by the Python
bindings, so the repository's Python workflow is not known to exercise the
vulnerable path. Nevertheless, the project's explicit `<22` range prevents
installing the fixed release and makes dependency scanning fail. Test a
coordinated PyArrow/Polars/DuckDB upgrade to at least 23.0.1, regenerate the
same frozen offline run, and compare all exported tables before widening the
constraint. See the [PyArrow advisory][pyarrow-advisory].

A current `uv tree --outdated` check found no newer release marker for any of
the three direct runtime packages. Version drift is concentrated in the
reproducibility-pinned research and development environment:

| Direct package | Locked | Newest reported | Recommendation |
| --- | ---: | ---: | --- |
| Polars | 1.33.1 | 1.43.2 | Test in a separate research lane |
| PyArrow | 21.0.0 | 25.0.1 | Expect storage compatibility work |
| NumPy | 2.3.5 | 2.5.2 | Upgrade with SciPy and models |
| SciPy | 1.16.3 | 1.18.0 | Upgrade with NumPy and scikit-learn |
| scikit-learn | 1.7.2 | 1.9.0 | Refit and compare saved outputs |
| XGBoost | 3.3.0 | 3.4.1 | Refit and compare ranking metrics |
| Matplotlib | 3.10.9 | 3.11.1 | Low-risk report compatibility check |
| DeepEval | 4.1.1 | 4.1.8 | Review patch notes, then run evals |
| Ruff | 0.16.0 | 0.16.3 | Routine tool-only update |
| ty | 0.0.64 | 0.0.72 | Run full type check before merging |

Do not widen all ranges at once. Create one lockfile update branch, regenerate
the offline report from the same frozen inputs, and compare tables, model
metrics, serialized artifacts, and charts before accepting it. Scientific
version freshness is less important here than proving the same input retains
the same meaning.

| Package idea | Recommendation | Reason |
| --- | --- | --- |
| Broader `cattrs` use | Conditional | Only for one full data boundary |
| Pydantic | Do not add now | Duplicates models and custom errors |
| msgspec | Do not add now | Speed is not the demonstrated problem |
| jsonschema runtime | Do not add now | Cannot replace game rules |
| Click or Typer | Do not add now | Parser structure is the issue |
| Tenacity | Do not add now | Existing retries include project-specific limits |
| platformdirs | Do not add now | One internal Linux-first helper is smaller |
| Rich | Do not add now | Output clarity needs vocabulary, not decoration |
| portalocker or filelock | Do not add now | Linux-first cache mutation can use stdlib `fcntl.flock` |
| orjson | Do not add now | Strict domains and duplicate-key rejection matter more than JSON speed |
| Google protobuf | Test as an oracle first | A tracked schema now exists |
| ValveResourceFormat | Test oracle only | Current .NET tool writes binary KV3 v4 |

`cattrs` currently reduces some manual parsing but also participates in the
policy serialization back-edge. Either broaden it behind a single codec
boundary or remove
the isolated use; do not add a second model framework.

The current Python `keyvalues3` 0.7 package is still the right small runtime
reader, but its own support table says Source 2 `3VK` versions 1-5 are read-only.
It cannot replace this project's binary-v4 encoder. ValveResourceFormat added
binary KV3 v4 serialization in its current .NET releases, but pulling a .NET 10
toolchain into a small Python CLI would be a poor runtime trade. Pin it in an
optional fixture/conformance job and require it to parse the produced cache;
use disagreements to improve fixtures before considering any boundary swap.
See [ValveResourceFormat releases][vrf-releases].

SteamTracking's current extracted `CMsgHeroBuild` schema confirms the manual
field numbers used here: item entry fields 1-5, category fields 1-6, build
details field 10, tags field 11, and publish time field 13. That is useful new
evidence, but it is not a Valve compatibility promise.

Pin the tracked schema commit and generate a decoder in a test-only experiment.
Require it to decode current fixtures and the project's encoded output, then
compare a generated round trip with the manual codec. Adopt a protobuf runtime
at the production boundary only if it reduces code and preserves unknown-field,
fixture, package-size, and failure behavior. “Generated” is not automatically
safer than the boundary already covered by 96% statement coverage.

### Language rewrite decision

Do not rewrite the project.

Python fits the actual work:

- API and JSON orchestration;
- optional data-science libraries;
- model process control;
- protobuf/KV3 boundary code with a strong test suite;
- Linux file operations; and
- fast iteration while Deadlock changes.

Rust or Go would add migration risk at the user-data boundary, split the
analytics ecosystem, and require new packaging and cross-language fixtures.
TypeScript offers no advantage for a Linux CLI whose UI lives inside Deadlock.

The expensive analysis already uses native implementations through XGBoost,
NumPy, Polars, PyArrow, DuckDB, and SciPy. If profiling later identifies one
pure CPU loop, benchmark and replace only that loop. No current measurement
justifies a whole-program rewrite.

The local command baseline is already interactive. Across 20 warm Hyperfine
runs, `uv run deadlock-build-sync --help` averaged 240.5 ms with a 7.6 ms
standard deviation. Importing `deadlock_build_sync.cli` through the same runner
averaged 235.1 ms, so almost the entire local cost is interpreter and import
startup rather than argument handling. The complete 302-test suite takes about
three seconds. Preserve these as simple baselines and profile a demonstrated
bottleneck before moving any isolated loop.

Existing value-free traces make that conclusion stronger:

- A full 38-hero sync took 2,543.4 seconds. Deterministic guide generation took
  41.0 seconds, Steam projection 0.73 seconds, installation 0.93 seconds, and
  all 38 protobuf serializations together took 0.09 seconds.
- About 2,500 seconds sit outside the named in-package stages at the point where
  the CLI invokes external Codex narrative generation. That attribution is an
  inference from the stage boundaries because the script package is not traced,
  but it matches the command flow.
- An all-hero context export took 7.6 seconds: 6.46 seconds for guide generation,
  1.10 seconds for evidence admission, 82 ms for context export, and about 4 ms
  for artifact writes.
- A call-level preview trace points to parsing 33,821 purchase-order transitions
  as the largest local CPU block. Call tracing itself adds substantial overhead,
  so its absolute 20-second runtime is not a benchmark.

The high-value performance work is fingerprint reuse, bounded model concurrency,
and a named narrative-generation stage. If deterministic preview latency matters,
profile evidence parsing without call tracing and consider a compact indexed
representation. None of those changes requires abandoning Python.

### Naming and player vocabulary

The code can keep exact research terms where statisticians need them. CLI help,
status, guide text, and ordinary module APIs should speak Deadlock.

| Current term | Prefer in player-facing text |
| --- | --- |
| artifact | saved build data or saved snapshot |
| cohort | match group or ranked match sample |
| projection | Steam build layout |
| policy | build plan or purchase plan |
| admission | validation or acceptance |
| abstention | skipped recommendation |
| epoch | patch boundary or data reset boundary |
| evidence regime | patch and data period |
| invariant role | hero's usual job |
| sidecar | review JSON or audit file |
| canonical | standard or default |
| estimand | what this stat measures |
| acquisition | purchase |
| terminal inventory | final inventory |
| flex slot | Extra Slot |
| joint support | matches ending with all eight targets |
| state-composed ability path | common next rank at each ability state |
| sequence policy | next-purchase rules or default CORE route; choose one |

`estimand`, `counterfactual`, and similar terms are appropriate in offline
statistical code and research reports. They should not appear in a normal
`sync --help` path without a plain explanation.

The documentation density confirms the problem. In the 2,423-word README,
`artifact(s)` appears 29 times, `policy/policies` 25, `projection(s)` eight,
`cohort(s)` five, abstention variants three, `sidecar(s)` twice, and
`admission` and `estimand` once each: 74 research-term occurrences in the main
entry document. These words are not individually wrong, but their cumulative
cost arrives before a player has learned what the tool does. Make the first
README path about `sync`, preview, status, backup, restore, Queue, build files,
patch, and skipped heroes. Move exact identity graphs, model review files, and
statistical definitions under a clearly linked `Research and reproducibility`
section where their precise names remain useful.

Current examples that need simpler help include “immutable analytics upper
cutoff” and “independent evidence-regime boundary.” Suggested meanings are
“latest match time included” and “override the patch/data reset for this data
source.”

The complete help inventory found several consistency gaps:

- `sync`, `preview`, `install`, and `export-context` expose four advanced
  `IDENTITY@UNIX_TIMESTAMP` reset overrides in their normal option list.
- `refresh-evidence` uses unexplained numeric `--min-badge` and `--max-badge`
  inputs while normal commands accept a named `TIER-DIVISION` rank.
- `recommend` supplies no help text for its state file, match-data file, or
  saved-data directory.
- `export-context --output` and `restore --latest` also lack explanations.
- `artifact`, `policy sidecar`, `narrative artifact`, and `evidence` appear in
  player help without a one-line description of the file's job.

Keep all ten commands, but present two levels. The normal path is `sync`,
`status`, a hero preview, and backup restore. Research and support paths are
evidence refresh, context export, read-only recommendation, reviewed-file
installation, and trace summary. Put patch-reset overrides in an explicitly
advanced group. Every required file argument should say who creates it, whether
it is read-only, and show one safe example.

The `recommend` command also exposes `--state`, `--build-evidence`, and
`--artifacts` without explaining the expected files. That command is the most
context-sensitive product surface and should have the clearest game-language
examples.

Its four machine actions can keep stable JSON values for compatibility while
the terminal explains them in game language:

| JSON action | Player-facing result |
| --- | --- |
| `buy` | `BUY <item>` |
| `save` | `SAVE SOULS FOR <item>` |
| `end` | `DEFAULT BUILD COMPLETE` |
| `abstain` | `NO SAFE CHOICE FROM CURRENT DATA` |

Do not show “abstention” as if the player should know an evaluation term. Give
the reason—unknown state, no supported counter, incompatible snapshot, or no
legal item—then name the next safe action.

Internal names can also improve when their owner is already being changed:

| Current code name | Clear game-oriented name |
| --- | --- |
| `BuildPolicy` | `BuildPlan` |
| `PolicyNode` | `BuildStep` |
| `SequencePolicy` | `PurchaseOrderModel` |
| `SituationalPolicy` | `ConditionalItemRules` |
| `strategy_context.py` | `build_context.py` |
| `power_curve.py` | `ending_duration_stats.py` |
| `production_evidence.py` | `build_evidence_export.py` |
| `unlocked_flex_slots` | `extra_slots_unlocked` |
| `_shopable_assets` | `_purchasable_items` after normalizing the upstream key |
| projection category | Steam build category |
| policy admission | build-plan validation |

`power_curve.py` is the clearest misleading name: it summarizes win rate by
the duration at which matches ended. The code correctly warns that this is not
a live power curve, but the filename invites that exact mistake.

“Flex Slot” is old Deadlock vocabulary. The current client, objective text,
and this report use **Extra Slot**, but `mechanics.py`, `policy.py`,
`recommendation.py`, the state JSON contract, and the offline report still use
`flex_slots`. Change player-facing errors and examples immediately when the
state contract is revised. Because `flex_slots` is a serialized input key, keep
it as an explicitly deprecated alias for one schema version or provide a small
state-file migration; do not make a naming cleanup look like a malformed-state
failure. In mechanics code, `extra_slots_unlocked` says both what the number is
and that it is current team state.

Several short names are worse than the long ones because they have multiple
game meanings:

| Ambiguous name | Meaning here | Prefer |
| --- | --- | --- |
| item `slot` | Weapon, Vitality, or Spirit | `item_category` or `investment_track` |
| `open_slots` | empty inventory capacity | `open_inventory_slots` |
| active slot | one of four bound item keys | `active_item_key` |
| `player_slot` | participant index in match data | keep internal as `player_slot` |
| item `tier` | 800/1,600/3,200/6,400 shop level | `item_tier` |
| rank `tier` | Emissary, Oracle, Phantom, and so on | `rank_family` |
| statistical `support` | matching record count | `sample_count` or `matching_records` |
| tactical support | healing or protecting teammates | `team_support` |
| `adopter_matches` | hero-player records that bought an item | `buyer_records` |
| CORE `items` | eight desired ending items | `final_targets` |
| expanded CORE | queue including prerequisites | `core_purchase_queue` |

This distinction matters in errors and type signatures. “Active slot burden
exceeds slots” is hard to parse; “five active items need four keys” is not.
Likewise, `eligible_player_matches` sounds like unique matches or people even
though its unit is eligible hero-player records. Keep the exact upstream name
at an API decoder if needed, then translate once into the domain model.

Do not perform a repository-wide rename only for style. JSON field names,
fingerprints, schemas, tests, and cached files are compatibility surfaces.
Rename player text immediately; rename persisted internal terms only alongside
a schema version and migration test.

### Design-principle review

#### Unix-style composition

The repository does well here. Read-only `status`, `preview`, `recommend`, and
`export-context` commands expose useful stages, while `sync` remains the simple
main path. JSON artifacts make stages inspectable.

The main weakness is naming: users must understand internal pipeline terms to
compose some lower-level commands.

#### DRY

The component expander and XDG path logic are concrete duplication. Similar
validation in JSON schemas and Python is not automatically waste: structural
and game-semantic validation have different jobs. Consolidate only when the
same rule has the same owner and failure meaning.

#### SOLID and ownership

The Steam boundary has strong single-purpose modules. Offline report and
narrative generation have too many reasons to change. The `policy` and
`policy_codec` cycle weakens dependency direction. Splitting by game
responsibility is more useful than introducing abstract framework layers.

#### Dynamic programming and model choice

There is no demonstrated dynamic-programming problem that the repository is
missing. Legal item upgrade planning and ability order are constrained paths,
but current deterministic rules are understandable and testable. Introduce a
new optimizer only when an objective, state definition, transition rule, and
chronological evaluation are explicit.

The same rule applies to model changes: promote a challenger because it wins a
Deadlock evaluation and can be exported safely, not because it is newer.

## Proposed test and research backlog

No code was implemented, but the following order would reduce the most risk.

### First: harden Steam writes and accepted build data

1. Add one interprocess lock per exact Steam cache, capture the live file
   identity under that lock, and refuse if it changes before replacement.
2. Recheck that Deadlock is stopped immediately before every cache replacement,
   including rollback after a failed post-write validation.
3. Bind each backup manifest to the exact Steam root and cache path. Before
   restore, preserve the current cache as a separate recovery copy and reject a
   different installation.
4. Skip a byte-equivalent managed result, refresh every marker-owned selected
   copy when an update is needed, and report duplicate or stale copies instead
   of silently choosing one.
5. Rebuild one typed final Steam layout from the build plan, evidence, current
   game assets, and reviewed text. Validate all item, ability, slot, sell, and
   imbue fields in their game domains before comparing that result with the
   saved layout.
6. Run generated and reviewed text through the same mechanic-reference,
   fake-number, causal-language, length, and identity checks. Bind the accepted
   bytes to the actual model, prompt, schema, runner, and CLI versions.
7. Add fault-injection tests for Deadlock starting before the first swap,
   starting after the swap, cache changes by another process, failed validation,
   wrong-install restore, and an identical no-op run.

### Second: repair the evidence boundary

1. Admit player rows only from a match that satisfies the declared 12-player
   eligibility contract; quarantine every other match as one unit.
2. Add complete, winner-only, and partially eligible DuckDB extraction
   fixtures, then rebuild every table and artifact from the frozen raw source.
3. Make explicit removal win an equal-time replay tie and assert that no
   source-removed item remains in the ending inventory.
4. Add rapid-upgrade, self-removal, opposite item-ID order, rebuy, and 12-slot
   inventory fixtures.
5. Define one XGBoost decision timestamp, replay mechanics-aware time buckets,
   and distinguish an owned component from an immediately previous component.
6. Refit all challengers and compare model choice, held-out metrics, candidate
   sets, and full-path support with both recorded sensitivity runs.
7. Compare rebuilt hero menus, candidate support, and outcome summaries with
   the recorded sensitivity results before publishing new guides.

### Third: repair the next-buy helper

1. Reject an already owned unique target before expanding its prerequisites.
2. Traverse only missing component branches and test all six three-level trees
   plus a legitimate shared-component rebuy.
3. Define completion from the intended ending inventory and check it before
   unconditional popularity fallbacks.
4. Run the 38 completed real routes as characterization fixtures.
5. Replace dormant-property text matching with reviewed active mechanics before
   enabling any counter branch or functional tag.
6. Derive duplicated inventory counts and add one-field context-change tests
   for every signal the command claims to use.

### Fourth: make the visible layout a contract

1. Capture current Kelvin and Viscous layouts as fixtures.
2. Test native prerequisite and optional queue behavior without starting a
   match.
3. Choose final-only or dynamically sized CORE cards.
4. Add a count-capacity validator before serialization.
5. Add viewport screenshots or deterministic layout snapshots.
6. Verify category round trips in the real client.

### Fifth: make quality claims reproducible

1. Record the exact Sonar server, scanner, profile, exclusions, and version.
2. Add a pinned CI scan or clearly document a local container command.
3. Export the quality-gate result as CI evidence.
4. Review complexity ignores by boundary instead of applying one broad policy.
5. Add repository Markdown lint configuration and CI coverage.
6. Run the standard gate on both advertised Python versions, 3.12 and 3.13.
7. Allowlist source-archive contents and reject files absent from the commit.
8. Remove the deprecated license classifier and retain the SPDX expression.

### Sixth: simplify ownership

1. Centralize component upgrade expansion.
2. Move runtime narrative code out of the generic `scripts` package.
3. Break report calculation into typed game sections.
4. Remove the policy serialization back-edge.
5. Centralize XDG state paths.
6. Split CLI builders and rewrite help in Deadlock vocabulary.
7. Add read-only state inventory and explicit offline-run archival guidance.
8. Index documentation and mark superseded layout and queue decisions.

### Seventh: improve build usefulness honestly

1. Separate ability-state support from exact-order support in text and tests.
2. Relabel tier menus as popular optional choices.
3. Reduce dense ten-card menus if user testing supports it.
4. Add live state to the read-only recommendation input.
5. Evaluate purchase sequences by patch and narrower rank groups.
6. Keep counter recommendations disabled until stable rules pass.
7. Show sample size, patch, soul range, and uncertainty near any claimed
   recommendation.
8. Run narrative generation with no host-file or shell access and an
   allowlisted environment.
9. Add fake-number, fake-mechanic, and prompt-injection fixtures to both model
   stages.

## Verification record

The repository was clean before this report was added. The current commit and
branch were inspected without modifying source code.

The standard local checks passed before report drafting:

```text
uv lock --check                         passed
uv run ruff format --check .           107 files already formatted
uv run ruff check .                    passed
uv run ty check                        passed
uv run pytest                          302 passed in 3.03 seconds
uv pip check                           95 packages compatible
```

The read-only `deadlock-build-sync status` command reported client 6679 and all
six freshness stages current, with 38 reviewed guides. No live sync was run.
A final 22:53 UTC API check still ended the client-version feed at 6679, kept
the August 12 patch as the newest patch-feed entry, and returned the same 38
active hero IDs. The pinned packet did not become stale during the audit.

A final read-only process check found both Deadlock and Hyprlock still running.
The live `cached_hero_builds.kv3` remained 86,589 bytes with an mtime of
2026-08-16 20:25:25 PDT, before this audit, and SHA-256
`c3c4ba4d8275cce27661eb6ed07d66fe145d68a4fcf6d7df7a536be3cffd6868`.
No desktop input or Steam cache write was performed after the visual pass.

The final standard gate passed all seven required commands: the lock was
current, Ruff reported 108 files formatted and no lint errors—the added report
accounts for the increase from 107—ty reported no type errors, all 302 tests
passed, all 95 installed packages were compatible, and both distribution
formats built. The 242 KB wheel kept
SHA-256
`7c1b512a8327e53269d152773688383c5767a2f0076f947c6836dc25edc32632`.
An additional warnings-as-errors run passed all 302 tests in 2.00 seconds, and
randomized order with seed `1787008634` passed all 302 in 1.97 seconds.

That exact wheel installed with only its runtime dependencies into clean
Python 3.12 and 3.13 environments. From a temporary directory outside the
source checkout, the installed CLI displayed help and both default runtime
schemas resolved and JSON-decoded successfully under each version. The
narrative schema was 3,137 bytes and the hero-kit schema was 2,061 bytes.
The same runtime-only probe passed on Python 3.14, while the full analysis/test
environment stopped during the PyArrow 21 dependency build as documented in
the tooling section; no 3.14 application test ran.

The report passed `markdownlint-cli2` 0.23.2 with zero issues, all links passed
`markdown-link-check` 3.14.2, and `codespell` passed with the correct game names
`Dota` and `Holliday` explicitly allowlisted.

Twine accepted the wheel and source archive metadata and long description.
`validate-pyproject` accepted the project file; `check-manifest` deliberately
failed on the untracked report documented above, and `check-wheel-contents`
reproduced only W005, W009, and W010 for the top-level `scripts` and `schemas`
layout.

Wheel inspection also confirmed that `scripts/generate_narratives.py` ships as
a top-level runtime package. The deterministic DeepEval metrics passed all four
checks for each of the ten default current-artifact cases. Model-backed
generation and reliability evals were not run because no prompt, model response
validator, or production code changed.

## Sources

Primary and direct sources:

- [Deadlock API documentation][deadlock-api]
- [Deadlock API machine-readable contract][deadlock-openapi]
- [Deadlock API patch feed][deadlock-patch-feed]
- [Deadlock API public-build query contract][build-api-query]
- [Deadlock API public-build response type][build-api-struct]
- [Deadlock patch used by the current snapshot][deadlock-patch]
- [Current tracked Deadlock hero-build protobuf][hero-build-proto]
- [SteamTracking client-6677 item data][game-tracking-deadlock-6677]
- [Deadlock Shop Rework Update][shop-rework]
- [Deadlock Map Rework Update][map-rework]
- [Deadlock June 30 objective rework][objective-rework]
- [Deadlock July 9 objective tuning][objective-tuning]
- [Deadlock April 30 investment update][investment-update]
- [Steam Cloud documentation][steam-cloud]
- [Steam News API response used for patch verification][steam-news-api]
- [Street Brawl Legendary item report][street-brawl-legendary]
- [Proposal to add Legendary items to normal mode][legendary-normal-proposal]
- [Dota Plus assistant][dota-plus]
- [Dota streamlined new-player shop][dota-streamlined]
- [Dota 2 hero build workshop][dota-builds]
- [League of Legends item shop design][riot-shop]
- [Sequential Item Recommendation in Dota 2][sequence-paper]
- [Contextual Team-aware Item Recommendation][team-paper]
- [DuckLake time-travel documentation][ducklake-time-travel]
- [Hatch source-distribution file selection][hatch-sdist]
- [PyPA project-metadata specification][pypa-project-metadata]
- [PyArrow PYSEC-2026-113 advisory][pyarrow-advisory]
- [Zizmor cache-poisoning audit][zizmor-cache]
- [ValveResourceFormat releases][vrf-releases]
- [XGBoost reproducibility guidance][xgboost-reproducibility]
- [XGBoost model I/O guidance][xgboost-model-io]
- [Repository Sonar cleanup pull request][sonar-pr]
- [Official Codex sandbox documentation][codex-sandbox]
- [Official Codex CLI command reference][codex-cli-reference]
- [Python JSON encoder and decoder documentation][python-json]
- [RFC 8259 JSON standard][rfc-8259]

Community and client-behavior sources:

- [Deadlock optional-item auto-queue bug report][auto-queue]
- [Deadlock 2560-by-1440 build clipping report][build-1440-clipping]
- [Deadlock cross-resolution build report][build-resolution-scaling]
- [Deadlock manual category resize report][manual-category-resize]
- [Deadlock category-description clipping report][category-description-clipping]
- [Deadlock Flex Pick category proposal][flex-pick]
- [Deadlock Quickbuy imbue-target report][imbue-auto]
- [Deadlock dashboard imbue-editor report][imbue-editor]
- [Deadlock Rem queued-imbue report][rem-imbue]
- [Valve Quickbuy introduction][quickbuy-update]

Repository-local background:

- [`deadlock-build-usage-audit.md`](deadlock-build-usage-audit.md)
- [`deadlock-strategy-description-research.md`](deadlock-strategy-description-research.md)
- [`AGENTS.md`](../AGENTS.md)

[auto-queue]: https://forums.playdeadlock.com/threads/optional-items-bug-in-auto-queue-build.102805/
[build-1440-clipping]: https://forums.playdeadlock.com/threads/2560x1440p-resolution-cuts-off-build-items.126228/
[build-resolution-scaling]: https://forums.playdeadlock.com/threads/build-ui-problems-with-different-resolutions.82200/
[build-api-query]: https://github.com/deadlock-api/deadlock-api/blob/master/api/src/routes/v1/builds/query.rs
[build-api-struct]: https://github.com/deadlock-api/deadlock-api/blob/master/api/src/routes/v1/builds/structs.rs
[category-description-clipping]: https://forums.playdeadlock.com/threads/guide-description-content-being-too-long-can-cause-items-in-the-category-to-be-hidden.24210/
[codex-cli-reference]: https://learn.chatgpt.com/docs/developer-commands?surface=cli
[codex-sandbox]: https://learn.chatgpt.com/docs/sandboxing
[deadlock-api]: https://api.deadlock-api.com/docs
[deadlock-openapi]: https://api.deadlock-api.com/openapi.json
[deadlock-patch-feed]: https://api.deadlock-api.com/v2/patches
[deadlock-patch]: https://store.steampowered.com/news/app/1422450/view/708906085669405228
[dota-builds]: https://www.dota2.com/workshop/builds/overview?l=english
[dota-plus]: https://www.dota2.com/plus
[dota-streamlined]: https://steamcommunity.com/games/dota2/announcements/detail/2995430596679058278
[ducklake-time-travel]: https://ducklake.select/docs/stable/duckdb/usage/time_travel
[flex-pick]: https://forums.playdeadlock.com/threads/new-build-feature-flex-pick-categories-dynamic-shop-logic.119788/
[game-tracking-deadlock-6677]: https://github.com/SteamTracking/GameTracking-Deadlock/blob/746408aad188b2c48986275c682e7717fa85eefe/game/citadel/pak01_dir/scripts/abilities.vdata
[hatch-sdist]: https://hatch.pypa.io/dev/plugins/builder/sdist/
[imbue-auto]: https://forums.playdeadlock.com/threads/imbue-suggestions-in-builds-no-longer-automatically-apply-when-queued-items-are-auto-purchased.79707/
[imbue-editor]: https://forums.playdeadlock.com/threads/suggested-imbuement-option-not-available-outside-game.66212/
[investment-update]: https://forums.playdeadlock.com/threads/04-30-2026-update.129989/
[legendary-normal-proposal]: https://forums.playdeadlock.com/threads/legendary-items-and-enhanced-items-for-the-main-game.110765/
[manual-category-resize]: https://forums.playdeadlock.com/threads/edit-not-a-bug-category-boxes-in-a-custom-build-dont-resize-to-fit-more-than-one-row-of-cards.76814/
[hero-build-proto]: https://github.com/SteamTracking/Protobufs/blob/master/deadlock/citadel_gcmessages_common.proto
[map-rework]: https://store.steampowered.com/news/app/1422450/view/530965072572320687
[objective-rework]: https://store.steampowered.com/news/app/1422450/view/688635449342692003
[objective-tuning]: https://store.steampowered.com/news/app/1422450/view/688635449342696590
[pyarrow-advisory]: https://osv.dev/vulnerability/PYSEC-2026-113
[pypa-project-metadata]: https://packaging.python.org/en/latest/specifications/declaring-project-metadata/
[python-json]: https://docs.python.org/3/library/json.html
[quickbuy-update]: https://forums.playdeadlock.com/threads/11-07-2024-update.44786/
[rem-imbue]: https://forums.playdeadlock.com/threads/rem-minions-cant-buy-certain-items.112563/
[rfc-8259]: https://www.rfc-editor.org/info/rfc8259/
[riot-shop]: https://www.leagueoflegends.com/en-us/news/dev/preseason-item-shop-update/
[sequence-paper]: https://arxiv.org/abs/2201.08724
[shop-rework]: https://steamcommunity.com/games/1422450/announcements/detail/524216645064852903
[sonar-pr]: https://github.com/sxndmxn/deadlock-build-sync/pull/9
[street-brawl-legendary]: https://forums.playdeadlock.com/threads/street-brawl-omnicharge-signet-disappeared.100758/
[steam-cloud]: https://partner.steamgames.com/doc/features/cloud
[steam-news-api]: https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=1422450&count=100&maxlength=0&format=json
[team-paper]: https://arxiv.org/abs/2007.15236
[vrf-releases]: https://github.com/ValveResourceFormat/ValveResourceFormat/releases
[xgboost-model-io]: https://xgboost.readthedocs.io/en/stable/tutorials/saving_model.html
[xgboost-reproducibility]: https://xgboost.readthedocs.io/en/stable/tutorials/dask.html#reproducible-result
[zizmor-cache]: https://docs.zizmor.sh/audits/#cache-poisoning
