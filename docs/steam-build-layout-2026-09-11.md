# Complete Steam build layout

The Steam exporter now retains all four tier panels and every supported item in each build group.
The main Markdown and JSON use the same presentation as Steam serialization.
The correction does not change build groups, core paths, variant evidence, or item pools.

## Official output contract

| Order | Panel | Contents | Optional |
| ---: | --- | --- | --- |
| 1 | CORE | Exact default purchase path, including components and required rebuys | No |
| 2 | CORE OPTIONAL | Additional variant path items and admitted conditional core items | Yes |
| 3–6 | TIER 1–4 | Complete union of supported variant pools, excluding cards already visible in the core panels | Yes |

CORE OPTIONAL appears only when the group needs additional items.
All four tier panels remain present, including empty panels.
Tier numbers identify item price tiers. They do not specify purchase order.
Item notes identify the applicable variants and the source of displayed statistics.
Each item appears once outside the default path. Required component rebuys remain in the default path.
Variant purchase paths remain in the build description. Variant counts and outcome estimates remain separate.
The renderer no longer deletes content to fit a 900-by-650-unit area.

Before serialization, validation checks panel order, optional flags, the default Queue, and complete item coverage.
A missing tier panel, missing supported item, or changed default Queue causes rejection.

The main `.md` file contains the title, ordered panels, dimensions, item notes, ability order, and build description.
The `.steam.json` file contains the corresponding structured presentation.
CLI JSON and guide indexes also expose this content as `steam_build`.
The `.details.md` file supplies additional evidence and purchase instructions.
It does not define another native build layout.

The CLI build writer now uses the existing CLI preview presentation helper.
This dependency stays within the entrypoint layer. Runtime presentation code does not import Steam storage code.

## Exact Kelvin build 1

The following files come from the production presentation writer:

- [Complete Steam Markdown](examples/kelvin-steam-build.md).
- [Complete Steam presentation JSON](examples/kelvin-steam-build.json).

Build path: `12-2cf175b992d56d8a`.
Title: `Build Preview | Healing Booster | 0822 / 0822–0909`.
The captured-data build uses the `Build Preview` persona.
Installation uses the selected account persona and assigns the account ID, local build ID, and timestamp.
The JSON describes content before those installation identity fields are assigned.

| Order | Panel | Cards | Width | Height |
| ---: | --- | ---: | ---: | ---: |
| 1 | CORE | 6 | 516 | 164 |
| 2 | CORE OPTIONAL | 5 | 432 | 164 |
| 3 | TIER 1 | 8 | 516 | 293 |
| 4 | TIER 2 | 10 | 516 | 293 |
| 5 | TIER 3 | 12 | 516 | 293 |
| 6 | TIER 4 | 12 | 516 | 293 |

Dimensions use native layout units.
The protobuf stores category order, width, and height. It does not store absolute panel coordinates.
The client controls placement and text display.

```text
CORE
  Extra Spirit
  Extra Regen
  Healing Booster
  Healbane
  Improved Spirit
  Mystic Vulnerability

CORE OPTIONAL
  Mystic Regeneration
  Enchanter's Emblem
  Radiant Regeneration
  High-Velocity Rounds
  Opening Rounds

TIER 1
  Golden Goose Egg
  Extra Charge
  Extra Stamina
  Sprint Boots
  Mystic Burst
  Healing Rite
  Mystic Expansion
  Grit

TIER 2
  Arcane Surge
  Trophy Collector
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

The build contains 53 cards.
Radiant Regeneration appears in CORE OPTIONAL because a supported variant uses it in its core.
Additional tier items come from the other supported variant pools.
Their notes retain the variant scope.

## Captured-data verification

The verification reconstructs the existing bundle through the normal artifact loader.
The source cutoff remains `2026-09-09T00:19:49Z`.
The snapshot remains `07d9927c014442376d0e3344cf5c1907967397956b4cb3e975cedd8ce81f768b`.
No timestamp or fingerprint changed to admit old data.

| Check | Result |
| --- | ---: |
| Heroes | 38 |
| Build groups | 142 |
| Supported variants, including defaults | 787 |
| Serialized item cards | 6,782 |
| Restored item entries across groups | 4,250 |
| Restored tier panels | 333 |
| Missing supported item IDs | 0 |
| Changed default purchase paths | 0 |

The comparison checks each reconstructed canonical variant against the previous generated record.
Only the obsolete display-omission metadata differs.
The comparison decodes protobuf fields and checks every category, item, annotation, optional flag, dimension, and ability purchase.
It also checks titles, descriptions, tags, flex requirements, sell priorities, and imbue targets.
Every main Markdown file matches the current presentation renderer.

Artifacts: `generated/steam-display-verification/verification.json` and `generated/steam-display-verification/builds/`.
The `.preview.pb` files use account ID 0, build ID 1, and timestamp 0.
They are serializer test payloads, not installed Steam records.

## Local and installed-wheel checks

All documented fast local gates passed.
All 1,549 tests passed with warnings treated as errors.
Statement coverage was 97.11%. Branch coverage was 91.97%.
Formatting, Ruff, SQLFluff, type checks, dependency checks, architecture checks, and complexity checks passed.
Coverage, dead-code checks, duplicate-code checks, package consistency, and package builds also passed.

The wheel and source distribution contain all 226 expected Python and SQL source files with matching bytes.
The installed wheel reconstructed all 142 groups and 787 variants outside the source checkout.
Its presentation and protobuf content matched the saved official records.
The in-memory cache test retained unrelated entries and produced identical content after a repeated update.
Both CLI help commands and the installed package consistency check passed.
Wheel SHA-256: `aa649eabc9058fe2bfe2af4e685724475dbf44432b9a6c9fdfb877bfc5bae677`.

The slower mutation gate did not run. Steam storage modules did not change.
Check records: `generated/steam-display-verification/quality-gates.json` and `wheel-verification.json`.

## Verification limits

No live Steam sync or client layout check ran.
Captured-data verification does not certify current patch freshness or a win-rate improvement.
Native wrapping, screen fit, and description visibility remain unverified.
The Kelvin description contains 10,323 characters. The JSON preserves that complete text.
The client can display less text than the serialized payload contains.
This report verifies export completeness. It does not certify the complete in-game presentation.
