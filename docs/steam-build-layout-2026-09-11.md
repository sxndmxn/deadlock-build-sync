# Complete Steam build layout

Each alternative core now has its own optional VARIANT category within the same Steam build.
SHARED CORE contains the final items common to the default and every alternative.
The default purchase Queue and all four tier panels remain complete.
The main Markdown and JSON use the same presentation as Steam serialization.

## Official output contract

| Order | Panel | Contents | Optional |
| ---: | --- | --- | --- |
| 1 | CORE | Exact default purchase path, including components and required rebuys | No |
| 2 | SHARED CORE | Final items common to every core, when a common set exists | Yes |
| Next | VARIANT 1–N | One complete alternative combination per category | Yes |
| Next | CORE CONDITIONAL | Admitted conditional core items, when needed | Yes |
| Last | TIER 1–4 | Supported item pools and required variant component purchases | Yes |

A panel marked `SHARED CORE +` needs the shared items and every item in that panel.
Together, those items reconstruct one exact supported final core.
When no shared items exist, each VARIANT panel displays its complete final core.
A variant with no additional final items also displays its full core.
These panels use the description `Full core.`
The shared set is the strict intersection. The renderer does not substitute the most common items.

Items can repeat between variant panels because each combination must remain complete.
Each variant card retains its own item statistics and imbue target.
Shared card notes identify the source of their displayed statistics.
Conflicting shared imbue targets remain explicit and have no guessed binding.
The build description retains each complete purchase order and the separate core outcome estimates.
Only CORE enters the default Queue.

All four tier panels remain present, including empty panels.
Tier numbers identify price tiers. They do not specify purchase order.
Tier pools exclude items already visible in CORE or CORE CONDITIONAL.
An item can appear in a tier panel and a variant combination when both roles have support.
Required variant components appear in their price tier, with notes that identify the applicable variants.
The renderer does not delete content to meet a fixed screen height.

Before serialization, validation checks category order, optional flags, each exact variant category, all supported items, and the default Queue.
A missing variant category fails validation even when its items appear elsewhere.
An incomplete combination also fails validation.

The main `.md` file contains the title, ordered panels, dimensions, item notes, ability order, and build description.
The `.steam.json` file contains the corresponding structured presentation.
CLI JSON and guide indexes expose this content as `steam_build`.
The `.details.md` file supplies additional evidence and purchase instructions.
It does not define a separate Steam layout.

## Exact Kelvin build 1

The following files come from the production presentation writer:

- [Complete Steam Markdown](examples/kelvin-steam-build.md).
- [Complete Steam presentation JSON](examples/kelvin-steam-build.json).

Build path: `12-2cf175b992d56d8a`.
Title: `Build Preview | Healing Booster | 0822 / 0822–0909`.
The captured-data build uses the `Build Preview` persona.
Installation uses the selected account persona and assigns the account ID, local build ID, and timestamp.

| Order | Panel | Cards | Width | Height |
| ---: | --- | ---: | ---: | ---: |
| 1 | CORE | 6 | 516 | 164 |
| 2 | SHARED CORE | 2 | 180 | 164 |
| 3 | VARIANT 1 | 2 | 180 | 164 |
| 4 | VARIANT 2 | 2 | 180 | 164 |
| 5 | VARIANT 3 | 2 | 180 | 164 |
| 6 | VARIANT 4 | 2 | 180 | 164 |
| 7 | TIER 1 | 10 | 516 | 293 |
| 8 | TIER 2 | 12 | 516 | 293 |
| 9 | TIER 3 | 13 | 516 | 422 |
| 10 | TIER 4 | 12 | 516 | 293 |

Dimensions use native layout units.
The protobuf stores category order, width, and height. It does not store absolute panel coordinates.

```text
CORE
  Extra Spirit
  Extra Regen
  Healing Booster
  Healbane
  Improved Spirit
  Mystic Vulnerability

SHARED CORE
  Healing Booster
  Healbane

VARIANT 1
  Enchanter's Emblem
  Radiant Regeneration

VARIANT 2
  Radiant Regeneration
  Mystic Vulnerability

VARIANT 3
  Opening Rounds
  Enchanter's Emblem

VARIANT 4
  Radiant Regeneration
  Improved Spirit

TIER 1
  Golden Goose Egg
  High-Velocity Rounds
  Extra Charge
  Extra Stamina
  Sprint Boots
  Mystic Burst
  Mystic Regeneration
  Healing Rite
  Mystic Expansion
  Grit

TIER 2
  Arcane Surge
  Opening Rounds
  Trophy Collector
  Enchanter's Emblem
  Enduring Speed
  Mystic Slow
  Slowing Hex
  Spirit Lifesteal
  Compress Cooldown
  Duration Extender
  Suppressor
  Debuff Reducer

TIER 3
  Torment Pulse
  Radiant Regeneration
  Rapid Recharge
  Rescue Beam
  Tankbuster
  Knockdown
  Superior Cooldown
  Dispel Magic
  Greater Expansion
  Superior Duration
  Decay
  Counterspell
  Alchemical Fire

TIER 4
  Escalating Exposure
  Boundless Spirit
  Spirit Burn
  Cursed Relic
  Unstoppable
  Healing Tempo
  Transcendent Cooldown
  Infuser
  Mystic Reverb
  Juggernaut
  Divine Barrier
  Refresher

```

Kelvin has 63 cards across ten panels.
Every alternative uses Healing Booster and Healbane from SHARED CORE.
VARIANT 1 adds Enchanter's Emblem and Radiant Regeneration.
VARIANT 2 adds Radiant Regeneration and Mystic Vulnerability.
VARIANT 3 adds Opening Rounds and Enchanter's Emblem.
VARIANT 4 adds Radiant Regeneration and Improved Spirit.
Mystic Regeneration and High-Velocity Rounds remain in TIER 1 as component purchases and supported pool options.

## Captured-data verification

The verification reconstructs the existing bundle through the normal artifact loader.
The data cutoff remains `2026-09-09T00:19:49Z`.
The snapshot remains `07d9927c014442376d0e3344cf5c1907967397956b4cb3e975cedd8ce81f768b`.
No timestamp, fingerprint, core, purchase path, support count, or source pool changed.

| Check | Result |
| --- | ---: |
| Heroes | 38 |
| Build groups | 142 |
| Supported variants, including defaults | 787 |
| Separate alternative categories | 645 |
| Shared core categories | 105 |
| Serialized item cards | 9,036 |
| Missing supported item IDs | 0 |
| Changed default purchase paths | 0 |

The comparison reconstructs every complete variant from its shared items and category items.
It compares the result with that variant's original final core.
The comparison also checks each reconstructed canonical variant against the earlier generated record.
Only the obsolete display-omission metadata differs from the original SQL verification bundle.
The protobuf comparison checks titles, descriptions, tags, every category, item annotation, dimension, optional flag, imbue target, and ability purchase.
Every main Markdown file matches the current presentation renderer.

Artifacts: `generated/variant-panel-verification/verification.json` and `generated/variant-panel-verification/builds/`.
The `.preview.pb` files use account ID 0, build ID 1, and timestamp 0.
They are serializer test payloads, not installed Steam records.

The earlier correction, `f925aad`, restored 333 tier panels and 4,250 missing item entries.
Its flat CORE OPTIONAL panel is now replaced by the separate variant categories documented here.
The earlier verification remains in `generated/steam-display-verification/`.

## Local checks

All documented fast local gates passed.
All 1,553 tests passed with warnings treated as errors.
Statement coverage was 97.12%. Branch coverage was 92.02%.
Formatting, Ruff, SQLFluff, type checks, dependency checks, architecture checks, and complexity checks passed.
Coverage, dead-code checks, duplicate-code checks, package consistency, and package builds also passed.
The slower mutation gate did not run. Steam storage modules did not change.
Check records: `generated/variant-panel-verification/quality-gates.json`.

## Installed-wheel checks

The wheel and source distribution contain all 226 expected Python and SQL source files with matching bytes.
The installed wheel reconstructed all 142 groups and 787 variants outside the source checkout.
Its presentation and protobuf content matched the saved records with separate variant categories.
The build writer produced the same Kelvin Markdown and JSON.
An in-memory cache test retained unrelated entries and produced identical content after a repeated update.
Both CLI help commands and the installed package consistency check passed.
Wheel SHA-256: `ae264173093f2d8bf81cc06adde5c1ecb0d18190a77aba33962fbcf71a55b354`.
Check record: `generated/variant-panel-verification/wheel-verification.json`.

## Verification limits

No live Steam sync or client layout check ran.
Captured-data verification does not certify current patch freshness or a win-rate improvement.
Native placement, screen fit, and description visibility remain unverified.
The Kelvin description contains 10,526 characters. The JSON preserves that complete text.
The client can display less text than the serialized payload contains.
This report verifies export completeness. It does not certify the complete in-game presentation.
