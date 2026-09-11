# Complete build verification

The optimized SQL produced 142 build groups with 787 supported variants across all 38 heroes.
The complete build check found an artifact reconstruction defect.
The correction retains ability names when it reconstructs beam purchase guidance.
All generated build groups now pass artifact reconstruction, purchase validation, and protobuf serialization.

## Inputs and method

This verification uses the captured 89,979-match database from `20260909T001949Z`.
The data cutoff is `2026-09-09T00:19:49Z`.
The rank cohort is 71 through 115.
The optional production beam generator uses width 16 and the 20-minute ownership checkpoint.
The 30-minute experiment remains separate.

The run performs fresh beam nomination and validation with the optimized SQL.
It retains the captured current-generator groups and supported fallback builds.
It freezes the full candidate family before validation.
Source fingerprints match before and after generation.

The normal guide service generates purchase guidance, policies, and strategy context from captured API responses.
The normal CLI artifact writer generates descriptions, full Markdown guides, detailed guides, and JSON.
The verification transport rejects requests without a captured response.
No new network response or Steam installation supplies a result.

## Results

| Hero | Build groups | Supported variants | Beam defaults | Current-guide defaults |
| --- | ---: | ---: | ---: | ---: |
| Lash | 4 | 39 | 1 | 3 |
| Viscous | 4 | 14 | 1 | 3 |
| Infernus | 6 | 24 | 1 | 5 |
| Kelvin | 3 | 11 | 0 | 3 |
| All 38 heroes | **142** | **787** | **39** | **103** |

Variant counts include each group default.
Each group is one build entry.
Fallback defaults retain the supported current-guide core when no complete even-state beam guide passes admission.
No requested hero was excluded.

Fresh nomination and evidence validation took 123.9 seconds with one worker.
Artifact reconstruction, purchase replay, and serialization verification took 22.3 seconds.
These durations cover different stages and do not measure a live evidence refresh.

### SQL result comparison

All hero identities, group identities, cores, purchase paths, scores, support statistics, and tier pools match the earlier beam evidence.
Item metrics also match when records are compared by `item_id`.
The SQL changed the unordered item-metric array order in 184 variants.
The comparison preserves order for purchase paths and tier pools.

The new implementation fingerprints produce a new evidence identity.
The comparison found no other evidence differences after matching unordered metric records.

### Complete purchase validation

| Check | Result |
| --- | --- |
| Artifact bundle reconstruction | 142 groups passed |
| Markdown, category, and group-record comparison after reconstruction | All generated records matched |
| Default and variant purchase replay | 787 paths passed |
| Optional purchase plans | 25,610 plans matched stored actions, inventory, and costs |
| Optional choices with unknown timing | 1,288 retained unknown timing |
| Blocked optional choices | 13 retained the correct planner rejection |
| Tier coverage in complete guides | All 787 variants retained Tier 1–4 coverage through their core or optional pools |
| Protobuf serialization and decoding | 142 builds passed |

The protobuf check compares hero identity, build name, description, tags, categories, dimensions, item annotations, imbue targets, and ability order.
The purchase check verifies component consumption, final inventory, core retention, and incremental costs.

## Reconstruction correction

Initial generation completed, but the artifact loader rejected the generated beam bundle.
Generated purchase guidance contained `ability_names`; reconstructed purchase guidance omitted this field.
The strict fingerprint comparison correctly detected the difference.

Generation and reconstruction now use the same ability-name projection from the supplied hero mechanics.
The correction changes no validation rule, timestamp, source artifact, purchase path, or displayed tier selection.
The original generated files pass reconstruction after the correction.

Two regression cases cover effective beam guides and current-guide fallbacks within beam evidence.
Both reproduced the original rejection before the correction.
Both pass after the correction.

## Remaining limits

The compact native display still omits optional content because of its current size limits.
This run reports omitted tier items in 138 groups, with 3,352 omitted default-pool item entries and 160 omitted alternative variants.
These counts concern display entries, not unique items or discarded statistical records.
Full Markdown and JSON retain all supported variants and tier pools.
This measurement precedes the display correction.
The [Steam layout verification](steam-build-layout-2026-09-11.md) records the correction and complete output.

The unresolved input and statistical issues in the [SQL audit](sql-query-audit-2026-09-11.md) remain unchanged.
This verification establishes generation and serialization behavior on captured data.
It does not certify live freshness, in-game layout, or a win-rate benefit.
No live Steam sync ran.

## Artifacts

Local generated files remain outside Git:

```text
generated/sql-build-verification/
  evidence-generation.json
  evidence-comparison.json
  reconstruction-failure.json
  build-verification.json
  quality-gates.log
  beam/builds.json
  beam/builds/07d9927c014442376d0e3344cf5c1907967397956b4cb3e975cedd8ce81f768b/INDEX.md
  beam/protobuf/
```

The source evidence identity is `5b03daf3a827ec65aabfc0bddee43983fda3103e89c53d9612bdc2daf13a4352`.
Each indexed build has complete Markdown, detailed Markdown, and a record in `guides.json`.

## Repository verification

The complete [fast local gate](quality-gates.md#fast-local-gate) passed after the reconstruction correction.
All 1,541 tests passed with warnings treated as errors.
Statement coverage is 97.08%; branch coverage is 91.87%.
Ruff, SQLFluff, Ty, Deptry, Tach, Complexipy, Vulture, Pylint, and the numeric quality gate passed.
The lock check, frozen environment, dependency check, and distribution build passed.

Wheel and source-distribution inspection found all 53 product SQL files with bytes identical to the source.
The installed wheel passed SQL parsing, ownership-checkpoint fixtures, beam fixtures, and both CLI help commands outside the checkout.
It also reconstructed the same 142 build groups and 787 variants, with exact Markdown and group-record matches.
The wheel SHA-256 is `f22e225d68f319d53661fa14d710aadd51f2c22cd3cb110b29ea84c2adfcbcc1`.
Wheel results are in `generated/sql-build-verification/wheel-smoke.json` and `wheel-bundle-validation.json` in that directory.

The slower mutation gate did not run.
The Steam storage modules did not change.
