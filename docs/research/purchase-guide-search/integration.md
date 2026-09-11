# Optional state-aware beam generator

The optional `beam` generator preserves current ECLAT and Leiden guide groups.
The default generator remains `current`.
Beam can select different cores and purchase orders inside each preserved group.
The group identifier remains stable when its default core changes.

## Commands

Use a separate directory for each generator.

```bash
deadlock-build-sync refresh-evidence --generator beam --artifacts artifacts/beam
deadlock-build-sync build --generator beam --artifacts artifacts/beam
```

The build command writes review artifacts.
It does not install Steam builds.
The existing `sync` command also accepts `--generator beam`.
No live Steam sync formed part of this verification.

`build` and `sync` reject evidence from a different generator.
Beam artifacts use schema 13 and record exact settings.
Current artifacts retain schema 12.
Beam resume requests require matching settings, implementation hashes, and source identity.

## Search and admission

The producer runs width-16 searches for each group and each wealth state.
Behind means personal net worth below 90% of the lobby average.
Even means 90% through 110%.
Ahead means above 110%.
Missing wealth has no state.

Search branches select target items.
The production purchase planner expands each target into its required components.
The search updates inventory, cash requirements, cost, and net worth after each component purchase.
It permits component repurchases after consumption.
It does not enumerate every possible interleaving of components from different targets.

The initial planning state has 800 souls and an empty inventory.
Cash increases only enough to fund the next purchase.
These are guide-planning assumptions, not a prediction of a player's farm rate.
Each searched route keeps one relative-wealth state.
State labels do not authorize an automatic core switch during a match.

The model uses discovery purchase records with a known prior purchase state.
Both teams need six observed players and snapshots from the preceding 120 seconds.
Same-second purchases and repeat item purchases do not enter the item estimator.
Legal component repurchases still use that estimator during planning.

Win-rate estimates use a Bayesian prior strength of 1,000.
The prior uses the purchase-event baseline within the same wealth and state cell.
That baseline is not a unique-player hero win rate.
The score subtracts half a posterior standard deviation.
It applies cost exponent 0.5 and purchase-step discount 0.97.
The score is a search heuristic, not a build win rate.

Each action needs 30 observations in its item, net-worth, and state cell.
Each complete beam core needs 200 matched discovery owners strictly before 20 minutes.
Core cost cannot exceed 19,200 souls.
The search retains current core-size rules and production inventory constraints.
It searches supported hero items beyond the retained 50-core candidate list.

Existing cores retain their original groups.
A new core needs two shared final items and Jaccard similarity of at least 0.5 with every group member.
Exactly one group must qualify.
Diagnostics count unmatched and ambiguous complete routes.

The producer applies current core, order, component, pool, and imbue checks.
It does not require a win rate above the hero baseline.
It records validation outcomes after freezing the proposal family.
It generates fresh core-specific pools and timing evidence.
The runtime requests fresh ability evidence for each selected core.
The existing ability fallback remains explicit when conditioned support is insufficient.

The highest-scoring admitted even-state core becomes the group default.
Behind-state and ahead-state cores remain optional complete variants.
A group without an admitted even-state replacement retains its current guides.
Fallbacks carry a reason and do not count as beam successes.

## Display

The native build retains one automatic default Queue.
Shared final items appear as a reference when space permits.
Complete variant instructions specify the full component purchase order.
The shared final-item set is not an ordered purchase prefix.

The compact layout targets 900 by 650 logical units.
It retains the default Queue first, complete variants second, and optional default-tier content third.
It records omitted variants, omitted tier items, and overflow.
Tier categories identify the default core as their scope.
Detailed Markdown and JSON retain every admitted variant and its own full item pool.
Native client layout remains unverified.

Displayed core rates count matches with all final core items owned strictly before 20 minutes.
Additional items are permitted.
Variant samples can overlap.
Each state has separate owner counts, wins, intervals, and a matched hero baseline.
Core state labels use the last complete lobby snapshots strictly before 20 minutes.
Those checkpoint snapshots can be up to five minutes old under the existing discovery rules.
The item-scoring model instead requires purchase-state snapshots from the preceding two minutes.
Item hover rates remain item-buyer statistics.
They do not represent the complete core rate.

## Comparison protocol

The comparison uses master commit `0ecad50cbf5500763d6dbd235c13a0263db7180b` and the same captured source run.
It includes 38 heroes, 142 groups, and all current variants.
The source cutoff is September 9, 2026, at 00:19:49 UTC.
The patch starts August 22, 2026, at 21:40:46 UTC.
The client version is 6686.
Starting rank badges are 71 through 115, with existing per-hero expansion rules.

Three runs separate core selection from order selection:

1. Unchanged master supplies the baseline.
2. The ordering control preserves every current core, default, and group.
3. Full beam can select new cores inside preserved groups.

All complete guides use the production policy, ability, narrative, and artifact pipeline.
The comparison transport reuses captured assets and exact API responses.
Uncached analytics requests retain the same patch, rank, and time constraints.
The transport records response hashes.
The comparison checks those hashes before reusing a cached response.

The report measures group coverage, core agreement, component-path agreement, order support, core outcomes, display omissions, and runtime.
The order-support count refers to final-core items.
It does not establish full component-path agreement.
Search diagnostics separately record expansion counts and search time.

These data informed earlier research.
The comparison is exploratory, even where a partition is named validation.
No untouched later cohort has established a win-rate benefit.
The generator remains optional.

## Reproduction

The comparison root is `generated/beam-integration`.
Its `source/results/master-0ecad50` directory holds the captured source snapshot.
Its `current/build-evidence.json` contains the isolated master export.

```bash
uv run python -m tools.beam_comparison.nominate --root generated/beam-integration --mode beam --workers 1
uv run python -m tools.beam_comparison.nominate --root generated/beam-integration --mode beam-order --workers 1
uv run python -m tools.beam_comparison.generate --root generated/beam-integration --mode current
uv run python -m tools.beam_comparison.generate --root generated/beam-integration --mode beam-order
uv run python -m tools.beam_comparison.generate --root generated/beam-integration --mode beam
uv run python -m tools.beam_comparison.state_statistics --root generated/beam-integration
uv run python -m tools.beam_comparison.report --root generated/beam-integration
```

The recorded master guide run loads the isolated master checkout through `PYTHONPATH`.
Use that checkout for an exact historical runtime comparison.
Run API-dependent comparisons sequentially to retain the request rate limit.

The earlier algorithm reports remain separate from this integration comparison.
Their original settings, code hashes, and result files remain available.
