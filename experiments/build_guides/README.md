# Discovered builds: purchase guidance and item pools

The tier lists are the **item pool**. A build includes the discovered core, its
component purchases, and choices from that pool placed along the purchase path.
The full preview now assembles these together. It does not change or refit the
frozen Eclat/Leiden/PrefixSpan comparison.

This implements the existing [pool requirement](../../docs/roadmap/phase-1-discovery-and-space.md),
[component timing and recovery requirement](../../docs/roadmap/phase-3-sequence-and-deviation.md),
and [documented upgrade/fork guidance](../../docs/repository-and-deadlock-build-research-2026-08-17.md).
The [conditional policy gates](../../docs/roadmap/phase-4-situational-policies.md)
still apply: a mechanics-based choice is not an admitted outcome-based counter.

## Generate and inspect

From the repository root, using the existing identity experiment environment:

```bash
uv run --project experiments/identity_paths python -m experiments.identity_paths.run preview \
  --output generated/identity-paths/trial-v1 \
  --preview-output generated/build-guides/review-v4
```

Use the documented uv version `>=0.12,<0.13`; on an older host, prefix with
`uv tool run --from 'uv>=0.12,<0.13' uv`. An optional `--heroes 6 12` restricts
the preview to Abrams and Kelvin. Use a new output path for each generation.

Print a guide as Markdown for a phone terminal:

```bash
uv run --project experiments/identity_paths python -m experiments.build_guides.run show \
  --guide generated/build-guides/review-v4/12-8c4e6b175aa94f55.json \
  --format markdown
```

Add `--details` to include each complete optional path, ending inventory, and evidence limits.
The default view shows the core, purchase decisions, upgrade routes, and full tiered pool.
Every matching option is visible. There is no shortlist limit.
HTML files use the same decisions. Select an item to inspect its complete path.
A hero without sufficient core evidence has no admitted default.
The user does not need to invent a build identity.

Each identity has JSON, Markdown, detailed Markdown, and HTML files. `INDEX.md` lists them.
`manifest.json` records source hashes, frozen evaluation, producer hashes,
generated files and automatic default identities.

## Recalculate after buying something

Supply a state file using item IDs from that guide's catalog:

```json
{
  "owned_items": [],
  "selected_items": [],
  "liquid_souls": 800,
  "unlocked_flex_slots": 0
}
```

```bash
uv run --project experiments/identity_paths python -m experiments.build_guides.run plan \
  --guide generated/build-guides/review-v4/12-8c4e6b175aa94f55.json \
  --state /path/to/state.json
```

`selected_items` contains optional purchases to include; an empty list follows
the default. The command recomputes the remaining path from actual ownership,
skips consumed components already represented by upgrades, credits owned direct
components, and reports the next purchase or the cash shortfall. Multiple
choices are recomputed together. Position and component dependencies come before observed time.
Current inventory may contain a previously upgraded item and a newly rebought
component. Unknown choices, ownership violations, slot overflow and more than
four active items fail explicitly. The planner does not invent a sale or flex slot.
The HTML preview shows one optional choice at a time; combining choices uses
this command. Net worth or an ahead/behind label never substitutes for cash.

## Guide schema and explicit purchase positions

New guides use schema version 2. Checkpoints contain typed decisions:

- `optional`: one optional item.
- `pick_one`: alternative routes for the next purchase.
- `upgrade`: one component route. You can stop at an eligible intermediate item.

Each option records its target, component route, eligible stages, and stage costs.
Shared-component forks identify the extra component cost for both routes.
Need groups use the main documented active or passive effect.
Stat-only items require an elevated or important tooltip property.
Unclassified effects remain general utility and do not form a PICK ONE group.

Unsupported timing has a null `placement.after_step` and appears in `unplaced_choices`.
It does not create an after-core branch. To select such an item, add `placement_overrides`
to the state. This object maps string item IDs to integer positions.
Position 0 is before the first core-path purchase. Position N is after purchase N.
Overrides must refer to selected items and remain within the default path.
An override cannot precede a required core item unless that item is already owned.
A selected component cannot follow its selected upgrade.
The result labels each override as an explicit choice, not observed timing evidence.

For example, `"placement_overrides": {"ITEM_ID": 2}` inserts the selected item after
core-path purchase 2. Replace `ITEM_ID` with an item ID from the guide.
An override does not validate the default path or its expected outcome.

The loader verifies guide and catalog fingerprints before reading either schema.
Version 1 guides are adapted in memory. Unsupported legacy positions become unknown.
The adapter updates purpose groups and recomputes branches. Historical files remain unchanged.
Unknown schema versions fail explicitly.

## Assembly contract and evidence limits

- Keep the exact frozen core nomination, order and rejection status. Full
  rendering does not turn a failed Kelvin core into a validated one.
- Schedule necessary components using discovery first-ownership net-worth
  priorities; preserve the frozen core order and require legal, nondecreasing
  observed wealth intervals. Missing reliable timing stays unknown. Repeated
  component cards invalidate the static default; explicit optional fork rebuys
  remain visible in the branch that requires them.
- Select each pool within discovery owners of that exact core. Require 20
  distinct buyers; take up to ten per tier by adoption, then display by observed
  first-purchase time. Exclude core items and all required core components.
  No old build identity or old item pool is an assembly input.
- Use whole-match purchase histories for those discovery owners, including
  openings, temporary items that may have been sold, and late upgrades. Do not
  read test-fold purchases, outcomes, final wealth or enemy labels to rank choices.
- Insert choices at their most supported strict adjacent first-purchase
  checkpoint (20 buyers and 10% of item buyers). Missing/tied anchors do not
  establish order. Unsupported placement remains unknown. An upgrade cannot
  precede its required core item. Mechanical prerequisites do not prove purchase timing.
- Show the entire pool, need-based choice groups, upgrade chains, shared-component
  forks, replacement/consumption, incremental costs and the resulting path.
  A checkpoint means choose the next optional purchase, not buy every card or
  permanently limit the completed build to one optional item.
- Reuse pinned item mechanics for reasons to consider choices. These rules
  describe mechanics; they do not establish conditional win-rate improvements.
  Enemy-specific and ahead/behind outcome preferences remain unadmitted. The
  original core win rate is never attached to its optional branch.

The data describe survivors owning a particular core at 20 minutes, span balance
changes, and include a previously inspected validation period. Purchase timing
is retrospective. A complete **presentation** is not a validated full-match
policy. `core_path_supported`, `passes_conditional_outcome_gate`, and
`full_policy_validated` remain separate. No output is installed or promoted.

## Verification

```bash
uv run --project experiments/identity_paths python -m pytest experiments/build_guides -W error
uv run --project experiments/identity_paths python -m experiments.build_guides.audit \
  --directory generated/build-guides/review-v4 \
  --baseline generated/build-guides/review-v2
```

Also run the repository fast gates in `docs/quality-gates.md`. Regression cases
cover missing pools, early component placement, rare items, core upgrades,
shared-component rebuys, combined choices, recovery, cash, slots, active limits,
fold isolation and preservation of candidate status.

The baseline comparison must preserve all 23 identities, 849 pool entries, exact
core paths, and evidence flags. The audit checks every decision, unknown position,
blocked choice, component route, and emitted purchase cost.
Run the affected identity-path and core-discovery tests with the guide tests.
Do not refit the frozen experiments or read the test fold for this change.
