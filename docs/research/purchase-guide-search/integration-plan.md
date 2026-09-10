# Optional beam search integration

## Accepted decisions

Add optional state-aware beam search at width 16.
Keep the current generator as the default.
Preserve master build groups and their ordering.
Allow new supported cores inside those groups.
Use an even-state default with behind-state and ahead-state options in the same build.
Do not implement a win-rate-above-hero admission rule.
Do not perform a live Steam sync.
Make at most one commit for this work.

## Baseline and source

Use master commit `0ecad50cbf5500763d6dbd235c13a0263db7180b`, which contains PR #26.
Continue implementation on `experiment/purchase-guide-search`.
Preserve the existing experiment files and unrelated user changes.
The original research goal is complete.
This integration requires a separate direct production comparison.

The saved source run is:

```text
/Users/sandmac/.local/state/deadlock-build-sync/offline/results/20260909T001949Z
```

Saved consolidated guide artifacts are available in:

```text
/Users/sandmac/code/deadlock-build-sync-qdfm/generated/consolidated-hero-coverage/artifacts
```

Reproduce master in an isolated checkout with the same source snapshot used for beam.
Record source hashes, patch, catalog, rank cohort, partitions, settings, and code revision.
Compare all eligible heroes and every published group.
Give Infernus, Viscous, Lash, Abrams, and Kelvin detailed comparisons.
Preserve master ordering when identifying each hero's first build.
Report identical cores as a result; do not force agreement.

## Search contract

Run a separate width-16 search for each existing group and relative-wealth state.
Keep ECLAT and Leiden for the initial frozen group definitions.
Search supported hero items and required components beyond the retained core candidate list.
Preserve current core cost limits and item-count rules.
Existing cores retain their original group assignments.
A new core must share two items and Jaccard similarity of at least 0.5 with every frozen group member.
Exactly one group must qualify.
Keep ambiguous and unmatched proposals in diagnostics.

Use prior strength 1,000, uncertainty multiplier 0.5, cost exponent 0.5, and purchase-step discount 0.97.
Require 30 item-state observations and 200 matched discovery owners for new beam cores.
Use the score only as an observational search heuristic.
Do not label the score as a build win rate.

Remove the six-purchase limit for complete guide generation.
Bound search depth through the maximum core size and component expansion.
Update inventory, consumed components, incremental cost, cash requirements, and net worth after each purchase.
Allow legal component repurchases after consumption.
Validate complete paths with production mechanics.
Keep final owned cores separate from purchase actions.
Do not concatenate independent budget scenarios.
Retain distinct supported terminal cores reached by the bounded search.
Different orders alone do not define different core variants.

Choose the highest-scoring admitted even-state candidate as the default.
Resolve equal scores through the existing default, greater support, then item identifiers.
Apply current core, order, component, pool, and ability-evidence validators.
Keep an identified current-guide fallback when a group has no complete admitted beam guide.
Do not count fallback guides as beam successes.

## Interfaces and complete guides

Add `--generator current|beam` to evidence generation, build generation, and sync.
The default is `current`.
Keep search inside the offline producer.
Build generation and sync consume validated frozen evidence.

Record generator identity, version, settings, stable group identity, explicit default variant, state, and fallback provenance.
Separate the stable group identifier from the selected default-core identifier.
Preserve managed build identifiers when defaults change.
Version beam artifacts and preserve legacy current-artifact validation.
Reject stale fingerprints, incompatible generator selections, and incompatible resume requests.
Use separate current and beam artifact directories.

Generate complete core queues, supported variants, Tier 1 through Tier 4 options, costs, purchase windows, and ability instructions.
Recalculate evidence for new cores.
Do not copy another core's tier statistics or ability evidence.
Keep description generation deterministic.

## State and display

Use personal net worth relative to mean lobby net worth.
Do not convert missing wealth to the even state.
Keep state-specific alternatives inside the original build group.
Show a mid-match switch only with supported entry conditions and a valid remaining purchase path.
Do not imply automatic native-client queue switching.

Keep one default queue and complete optional branch definitions.
Factor final-core intersections separately from identical ordered purchase prefixes.
Use CORE OPTIONS for alternative complete recipes.
Use PICK ONE only for an explicit guide choice, without claiming co-ownership is invalid.
Keep all admitted variants in detailed Markdown and JSON.
Use a 900-by-650 logical compact layout target.
Preserve the default queue, then complete variant instructions, then optional tier content.
Report overflow and omitted optional content.
Do not claim live-client layout verification.

## Comparison and statistics

Compare unchanged master, beam ordering of existing cores, and full beam selection within preserved groups.
Use the same captured input data and strictly-before-20-minute core ownership definition.
Keep other checkpoints separate.
Report cores, purchase actions, costs, additions, removals, upgrades, variants, tiers, and ability instructions.
Report complete-core wins, owner counts, observed rates, 95% intervals, and matched-state and whole-hero baselines.
Report exact-order support, rejected proposals, fallback reasons, search time, evidence time, and total runtime.
Measure validity, coverage, statistical support, action agreement, and build diversity independently of search utility.
Do not sum overlapping variant samples.

Earlier test data has already informed development.
Label comparisons on those data as exploratory.
Freeze new settings before evaluating a later untouched compatible cohort.
Report unavailable independent evaluation without claiming stronger builds.
Keep beam optional.
Write consecutive current and beam Markdown builds for phone use.
Include short change lists instead of wide tables.

## Verification and completion

Test group identity, ordering, new-core assignment, default replacement, and repeated generation.
Test components, repurchases, costs, capacity, full paths, wealth boundaries, and missing data.
Test core support, order support, fallback provenance, variant reconstruction, statistics, and artifact compatibility.
Require zero mechanical failures and no lost baseline groups.
Run the complete fast gate in `docs/quality-gates.md`.
Inspect the built wheel and run its smoke test outside the checkout.
Deliver complete comparison artifacts and a self-contained phone-readable summary.

## Implementation status

Implementation is complete.
All 1,528 tests and the complete fast gate pass.
All three comparisons produced 142 complete groups across 38 heroes.
The [verification report](integration-verification.md) records results and limits.
The [group comparison](integration-comparison.md) contains consecutive current and beam defaults.
No integration commit or live Steam sync occurred.
