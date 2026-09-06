# Default build system

`uv run build` and `deadlock-build-sync sync` use the admitted discovery builds.
`deadlock-build-sync refresh-evidence` produces the evidence. The producer requests
the full current hero roster. It does not access Steam files.

## Discovery and admission

Eclat finds exact cores. Leiden groups related cores. Pairwise purchase ordering
supplies the core order. Components are added with their required purchase and
consumption order. Normal generation has no old clustering or core-completion
fallback. PrefixSpan and the old methods remain in `tools/comparisons`.

The discovery rules remain fixed: cores have four to six items, at least 100
owners, and a maximum catalog cost of 19,200 souls. Selection needs at least 52%
observed wins, joint ownership lift of 1.1, at least 100 comparable owners, and
80% comparable-state coverage. Selection lower bounds must pass. Validation uses
family correction across all frozen nominees. The purchase order needs at least
20 ordered owners and 10% order share in discovery, selection, and validation.
Documented hero mechanics and legal component execution must also pass.

Whole matches are split by time. The original training split is divided into
discovery and selection. Candidates, identity ranking, core order, component path,
item pools, and possible branch conditions are frozen before validation. The
reserved test split remains outside selection and admission. A frozen nomination
file records the complete comparison family before validation starts.

Each hero can have up to three distinct admitted identities. The default is the
admitted identity with the lowest frozen selection rank. Validation does not
reorder candidates. Every requested hero must have admitted builds or an explicit
exclusion with observations and rejection reasons. Missing hero data and malformed
artifacts are errors. If no builds pass, the producer writes an exclusion report
and preserves the existing evidence file. Generation also checks coverage before
it writes the review bundle. Installation preserves builds for excluded heroes.

Each pool uses discovery buyers who owned that exact core. Pool items need at
least 20 buyers, with up to ten items per tier. All matching options are shown.
There is no second shortlist. All four pool tiers follow the purchase path.

## One purchase guide

Evidence schema 10, purchase-guide schema 2, and decision-state schema 3 are
required. Old or incompatible evidence must be refreshed and rebuilt:

```bash
deadlock-build-sync refresh-evidence
uv run build
```

Markdown, JSON, Steam rows, recommendations, and artifact installation use the
same typed guide and planner. The automatic Queue contains only core component
steps, in their validated order. Optional instructions appear between these steps
with `OPTIONAL`, `PICK ONE`, or `UPGRADE` labels. Instructions give the trigger,
checkpoint, route, extra cost, core resume point, and any required component rebuy.
Rows are split at the 240-byte UTF-8 limit without removing text or options. The
item hover remains the two-line statistics card.

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

See [the September 6 integration run](default-build-verification-2026-09-06.md) for
fresh admissions, exclusions, package checks, and temporary-cache results.
Historical comparison reports retain their original source references. The
`experiments` paths in those reports refer to commit `56debec` and earlier code.
