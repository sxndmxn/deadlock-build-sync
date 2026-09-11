# Complete Steam build layout

Each alternative core now has its own optional VARIANT category within the same Steam build.
CORE ITEMS contains the complete default purchase path.
ALTERNATIVE CORE contains the final items common to the default and every alternative.
The default purchase Queue and all four tier panels remain complete.
The main Markdown and JSON use the same presentation as Steam serialization.

## Official output contract

| Order | Panel | Contents | Optional |
| ---: | --- | --- | --- |
| 1 | CORE ITEMS | Exact default purchase path, including components and required rebuys | No |
| 2 | ALTERNATIVE CORE | Final items common to every core, when a common set exists | Yes |
| Next | VARIANT 1–N | One complete alternative combination per category | Yes |
| Next | CORE CONDITIONAL | Admitted conditional core items, when needed | Yes |
| Last | TIER 1–4 | Supported item pools and required variant component purchases | Yes |

A panel marked `ALTERNATIVE CORE +` needs the shared items and every item in that panel.
Together, those items reconstruct one exact supported final core.
This combination replaces CORE ITEMS. It does not specify a purchase order.
The build description retains each variant's complete purchase order, including components and required rebuys.
When no shared items exist, each VARIANT panel displays its complete final core.
A variant with no additional final items also displays its full core.
These panel descriptions start with `Full core.`
The shared set is the strict intersection. The renderer does not substitute the most common items.

Items can repeat between variant panels because each combination must remain complete.
Each variant card retains its own item statistics and imbue target.
Shared card notes identify the source of their displayed statistics.
Conflicting shared imbue targets remain explicit and have no guessed binding.
The build description retains each complete purchase order and the separate core outcome estimates.
Only CORE ITEMS enters the default Queue.

Each variant's category notes show its recorded wealth states and complete-core win counts.
The full build notes use labels such as `V1 (Behind)` and `V2 (Even, Ahead)`.
Only declared states with nonempty validation samples receive labels.
Missing data produces `State evidence unavailable.` in the category and `State unknown` in the full notes.
The renderer does not infer a state from cost, items, or the default core's evidence.
State labels describe observed complete cores. They do not establish when to change a partly purchased core.

Wealth states compare personal net worth with the lobby average.
Behind means below 90%. Even means 90% through 110%. Ahead means above 110%.
The captured Viscous alternatives have Even-state evidence only.

All four tier panels remain present, including empty panels.
Tier numbers identify price tiers. They do not specify purchase order.
Tier pools exclude items already visible in CORE ITEMS or CORE CONDITIONAL.
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
| 1 | CORE ITEMS | 6 | 516 | 164 |
| 2 | ALTERNATIVE CORE | 2 | 180 | 164 |
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
CORE ITEMS
  Extra Spirit
  Extra Regen
  Healing Booster
  Healbane
  Improved Spirit
  Mystic Vulnerability

ALTERNATIVE CORE
  Healing Booster
  Healbane

VARIANT 1
  ALTERNATIVE CORE +
  Even: 54.3% | 51/94 wins
  Enchanter's Emblem
  Radiant Regeneration

VARIANT 2
  ALTERNATIVE CORE +
  Even: 56.2% | 63/112 wins
  Radiant Regeneration
  Mystic Vulnerability

VARIANT 3
  ALTERNATIVE CORE +
  Even: 61.2% | 49/80 wins
  Opening Rounds
  Enchanter's Emblem

VARIANT 4
  ALTERNATIVE CORE +
  Even: 59.2% | 87/147 wins
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
Every alternative uses Healing Booster and Healbane from ALTERNATIVE CORE.
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
| ALTERNATIVE CORE categories | 105 |
| Serialized item cards | 9,036 |
| Missing supported item IDs | 0 |
| Changed default purchase paths | 0 |

The comparison reconstructs every complete variant from its shared items and category items.
It compares the result with that variant's original final core.
The earlier comparison checked each canonical variant against the original SQL verification record.
The new comparison confirms that only category labels and description text changed.
Items, purchase paths, statistics, tags, identities, dimensions, and ability orders remain unchanged.
The protobuf comparison checks titles, descriptions, tags, every category, item annotation, dimension, optional flag, imbue target, and ability purchase.
Every main Markdown file matches the current presentation renderer.

The variant notes contain 36 Behind labels, 556 Even labels, and 70 Ahead labels.
Some variants have evidence for more than one state.
The longest category description contains 101 bytes; the native limit is 240 bytes.
The production writer also verified all four Viscous builds and Kelvin build 1.

Artifacts: `generated/core-variant-label-verification/verification.json` and `generated/core-variant-label-verification/presentations/`.
Production writer files: `generated/core-variant-label-verification/selected/`.
The `.preview.pb` files use account ID 0, build ID 1, and timestamp 0.
They are serializer test payloads, not installed Steam records.

The earlier correction, `f925aad`, restored 333 tier panels and 4,250 missing item entries.
Its flat CORE OPTIONAL panel is now replaced by the separate variant categories documented here.
The earlier verification remains in `generated/steam-display-verification/`.

## Local checks

All documented fast local gates passed.
All 1,560 tests passed with warnings treated as errors.
Statement coverage was 97.13%. Branch coverage was 92.04%.
Formatting, Ruff, SQLFluff, type checks, dependency checks, architecture checks, and complexity checks passed.
Coverage, dead-code checks, duplicate-code checks, package consistency, and package builds also passed.
The slower mutation gate did not run. Steam storage modules did not change.
Check records: `generated/core-variant-label-verification/quality-gates.json`.

## Installed-wheel checks

The wheel and source distribution contain all 226 expected Python and SQL source files with matching bytes.
The installed wheel reconstructed all 142 groups and 787 variants outside the source checkout.
Its presentation and protobuf content matched the saved records with renamed categories and variant state notes.
The build writer produced the same Kelvin Markdown and JSON.
An in-memory cache test retained unrelated entries and produced identical content after a repeated update.
Both CLI help commands and the installed package consistency check passed.
Wheel SHA-256: `ef8cf91515f585e0bc16fae333f10a672c5f33d44fc0687c6b7d4a0b7b7647a2`.
Check record: `generated/core-variant-label-verification/wheel-verification.json`.

## Verification limits

No live Steam sync or client layout check ran.
Captured-data verification does not certify current patch freshness or a win-rate improvement.
Native placement, screen fit, and description visibility remain unverified.
The Kelvin description contains 10,728 characters. The JSON preserves that complete text.
The client can display less text than the serialized payload contains.
This report verifies export completeness. It does not certify the complete in-game presentation.
