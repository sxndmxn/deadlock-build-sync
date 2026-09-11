# Default build system

`uv run build` and `deadlock-build-sync sync` use the admitted discovery builds.
`deadlock-build-sync refresh-evidence` produces the evidence. The producer requests
the full current hero roster. It does not access Steam files.

## Discovery and admission

Eclat finds exact cores. Leiden groups related cores. Pairwise purchase ordering
supplies the core order. Components are added with their required purchase and
consumption order. Normal generation has no old clustering or core-completion
fallback. PrefixSpan and the old methods are [archived in Git history](../tools/comparisons/README.md).

The first search uses four-to-six-item cores with a maximum catalog cost of
19,200 souls. If none has a supported legal path, it uses existing three-item
seeds. It does not add guessed items. Each core needs at least 100 exact owners in
discovery and 100 in selection. Purchase orders are tried by pairwise score until
one is legal and has 20 followers and 10% share in both folds. Complete component
purchase records, costs, ownership, slots, and active-item limits are mandatory.

Availability is separate from evidence of a win advantage. `outcome_supported`
requires at least 52% observed wins, joint ownership lift of 1.1, 100 comparable
owners, 80% comparable-state coverage, and the positive selection lower bounds.
Validation uses correction across the frozen comparison family and checks order
support. Other supported builds receive `observed` status with evidence limits.
A missing mechanic text match adds a limit; it does not reject a legal build.

`--rank-expansion auto|off` is available on refresh and generation commands.
The default is `auto`, starting at Emissary I through Eternus V. `--min-rank`
sets the starting cutoff. One shared loop lowers the cutoff one tier at a time
only for a hero without a supported legal build. It stops when a build is
available, including when only one identity is available. It never expands to
improve outcomes. Exhaustion of all ranked data is an explicit error. The hero's
effective range, support counts, and each attempted range are stored in evidence.

The source snapshot, patch, mechanics, and requested time range stay fixed.
Whole matches are admitted without duplicates. Time boundaries come from the
starting range before expansion. Matches never move between splits. The original
training split is divided into discovery and selection. Candidates, identity ranking, core order, component path,
item pools, and possible branch conditions are frozen before validation. The
reserved test split remains outside selection and admission. A frozen nomination
file records the complete comparison family before validation starts.

Candidates with an adjusted selection estimate come first, ordered by lower bound,
owner count, then item IDs. Candidates without an estimate follow, ordered by owner
count and item IDs. The search checks every candidate and keeps the first usable
build from each identity group. There is no build-count limit per hero. Failed
candidates do not prevent later candidates in the same group from being checked.
The first usable identity is the default. Validation changes evidence status; it
does not change frozen identities, order, paths, pools, or branch candidates.
Missing requested heroes and malformed artifacts cause generation to fail. The
producer records reasons and preserves the existing evidence file. Generation
stages the complete review bundle and preserves the current bundle on failure.

Each pool uses discovery buyers who owned that exact core. Pool items need at
least 20 buyers, with up to ten items per tier. All matching options are shown.
There is no second shortlist. All four pool tiers follow the purchase path. Empty
tiers explicitly show that no supported options are available. Conflicting timing
estimates are uncertain and retain the legal order. Missing economy and enemy
observations disable affected estimates and choices, while complete purchase
histories remain available.

## Guide groups and variants

Publication groups the frozen exact-core nominations using their shared item IDs.
An edge requires at least two common items and an item Jaccard score of at least
0.5. The existing Leiden routine uses that score as its edge weight, resolution 1,
ten iterations, and seeds 42, 43, and 44. Deterministic complete-link merging
requires agreement from at least two seeds for every pair in a group. Members do
not need a direct item edge between every pair. Canonical item ordering keeps the
result stable when input rows change order.

The member with the best frozen selection rank supplies the default Queue and
group ID. Group names use the two most common core items, with item IDs breaking
ties. Grouping does not read validation results or combine support counts.
The producer saves the groups before validation. No group or variant count limit
applies. Each exact core retains its original path, costs, support, evidence
status, ability order, and discovery-buyer pools.

Steam and the main Markdown display each alternative core in its own VARIANT category.
CORE ITEMS keeps the exact default component purchase order.
ALTERNATIVE CORE contains the intersection of all final cores, including the default.
Each VARIANT category shows the remaining items for that complete combination.
Its description starts with `ALTERNATIVE CORE +`.
When no shared items exist, each VARIANT category shows its complete final core.
A variant with no additional final items also shows its full core.
Its description starts with `Full core.`.

Variant category notes show recorded Behind, Even, and Ahead states with complete-core win counts.
The full build description also identifies each variant's states before its purchase order.
Only declared states with a nonempty validation sample receive labels.
Missing state evidence remains explicit. The renderer does not infer a state from item cost or the default core.
State labels describe observed matches. They do not establish when to change a partly purchased core.
ALTERNATIVE CORE and VARIANT define final item combinations. Their items can occur at different purchase steps.

Items can repeat between VARIANT categories because each category must preserve its complete combination.
Each variant card retains its own item statistics and imbue target.
Shared item notes identify the source variant for their statistics.
Conflicting shared imbue targets remain explicit and do not receive a guessed binding.

CORE CONDITIONAL contains admitted conditional core items when needed.
The four tier panels combine supported pools and required variant component purchases.
They exclude items already visible in CORE ITEMS or CORE CONDITIONAL.
An item can appear in a tier panel and a variant combination when both roles have support.
Component purchases retain their variant scope in the item notes.
Detailed Markdown and JSON retain every complete variant.

Both generators use this complete layout.
The renderer does not remove panels or items to meet a fixed screen height.
Before serialization, validation checks each complete variant category, all four tier panels, every supported item, and the exact default Queue.
Only CORE ITEMS is required; all other panels remain optional.

The main Markdown file now renders the actual Steam presentation, including item notes and panel dimensions.
Each `.steam.json` file contains its title, tags, description, ordered panels, item fields, and ability order.
The `steam_build` record in CLI JSON and guide indexes contains the same content.
The `.details.md` file provides additional variant evidence and purchase instructions.
It does not define a separate Steam layout.

See the [Steam layout verification](steam-build-layout-2026-09-11.md) for exact Kelvin output and verification limits.

Each source pool still has at most ten items per tier; its displayed union can
contain more. Empty tiers remain explicit. Select one full variant before
purchase. Automatic changes during a match still require the existing branch
and core-substitution evidence.

Evidence schema 12, purchase-guide schema 3, and decision-state schema 3 are
required. Method `eclat-leiden-pairwise-v3` adds frozen publication groups.
Guide indexes use schema 2 and contain group records with schema 1. Each group
record retains all canonical purchase guides. Evidence from earlier methods is
rejected with a refresh instruction.
Old or incompatible evidence must be refreshed and rebuilt:

```bash
deadlock-build-sync refresh-evidence
uv run build
```

Markdown, JSON, Steam rows, recommendations, and artifact installation use the
same typed guide and planner. The automatic Queue contains only core component
steps, in their validated order. Full purchase instructions stay in the detailed
guide and Steam build description. They give the trigger, checkpoint, route,
extra cost, core resume point, and required component rebuy. Long instructions
do not create more Steam categories. Item notes remain within 240 UTF-8 bytes;
large scope lists refer to the complete variant details.

Compact dimensions use the recorded 84-by-129-unit outer card footprint and
12 units of horizontal space for panel edges. Sections use up to six columns,
or twelve when more than eighteen items need space. A single-item section is
128 units wide. Empty tiers are 256 by 48 units. Height includes 35 units for the
header plus every card row. Short section headers keep text out of the card area.
These dimensions preserve readable card sizes. Screen fit still depends on the
client scale and available viewport; no live Steam visual check is implied.

The stored canonical projection remains unchanged. Installation validates it
before constructing the compact display, so current schema-12 evidence and
reviewed bundles remain usable without another analytics fetch.

Timing requires 20 adjacent first-purchase observations and 10% of that item's
discovery buyers. Unsupported timing remains explicit. The item stays in the pool
and needs a player-supplied checkpoint before it can be selected.

The planner starts from actual inventory. It credits owned components, recognizes
upgrades that satisfy core requirements, and adds required component rebuys.
Combined selections are evaluated together. Item slots and active-item limits are
checked after each purchase. Net worth never pays a liquid-soul shortfall.

Installation reconstructs the guide from the evidence and pinned mechanics. It
checks category text, repeated item references, optional flags, costs, and Queue
order against the canonical guide before it can write a Steam cache.

## Match state

Extend a complete state file as follows. IDs below are examples; use IDs and a
`path_id` from the selected guide.

```json
{
  "schema_version": 3,
  "path_id": "hero-core-identity",
  "selected_optional_items": [123, 456],
  "placement_overrides": {"123": 2, "456": 4},
  "enemy_observed_at_s": 599,
  "economy": {
    "personal_net_worth": 8000,
    "lobby_net_worths": [10000, 10000, 10000, 10000, 10000, 10000,
                         10000, 10000, 10000, 10000, 10000, 10000],
    "observed_at_s": 599
  }
}
```

Use the complete [state schema](../schemas/decision-state.schema.json) for required
inventory, match, hero, and evidence fields. Then run:

```bash
deadlock-build-sync recommend --state state.json --format markdown
```

The result includes the next purchase, cash shortfall, remaining route and cost,
selected placements, and every available pool choice. Each choice also reports its
cost or blocked reason after the other selections are applied.

Relative wealth is personal net worth divided by mean lobby net worth. Below 0.90
is behind; above 1.10 is ahead. Both boundary values are even. All 12 lobby values
are required. Missing or incomplete wealth data disables wealth conditions.
Observations must be strictly before the decision and no more than 300 seconds
old. Enemy hero and item conditions also need a fresh prior observation. Offline
comparison states reconstruct enemy items at that observation time.

Explicit player selections take priority. Next, an admitted matching branch can
apply at the current checkpoint. Otherwise the default path applies. Competing
branches are ordered by validated lower bound, support, then item ID. Automatic
branches need support, overlap, balance, uncertainty, temporal stability, corrected
outcome, legal-path, and pre-decision cohort checks. A failed check keeps manual
options available. Decision cohorts never require an item purchased later.

The selected identity stays fixed during recalculation. A core substitution needs
its own core admission and branch evidence. An explicit substitution uses
`core_substitution_item_id` together with `selected_optional_items`. Steam shows
static conditional instructions. This work adds no live game-state capture.

## Verification records

See [the September 7 full-roster run](full-hero-verification-2026-09-07.md) for
112 builds across all 38 heroes, package checks, and temporary-cache results.
The [September 6 run](default-build-verification-2026-09-06.md) records the earlier
admission rules and their exclusions.
Historical comparison reports retain their original source references. The
`experiments` paths in those reports refer to commit `56debec` and earlier code.
