# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Use the selected or resolved Steam persona as the installed build-title prefix.
- Size each Steam category from its item count so extra item rows are not cut off.

### Added

- Repository quality gates for complexity, coverage, CRAP score, dead code,
  repeated code, and Steam-boundary mutation testing.
- Read-only artifact freshness, evidence refresh, and state-aware recommendation
  commands.
- Pinned build tags, archetype titles, tactical hover projection, and typed
  situational counter cards.
- An optional offline analysis extra with component-aware sequence evidence,
  same-opportunity comparator gates, and fail-closed branch admission.

### Changed

- Show one two-line statistics card on every item hover: `SOUL WINDOW`, then
  `PR`, `WR`, and `TOTAL GAMES`. This replaces the four-line `USE` / `WHY` /
  `SKIP` / `DATA` tier card, the five-line `VS` / `WHY` / `SWAP` / `WHEN` /
  `SKIP` swap card, and the five-line `CORE ITEMS` block. The `IMBUE` line is
  gone because Steam shows its own imbue icon. The card is derived from evidence,
  so a stored artifact whose card no longer matches is rejected. Conditional
  decision copy stays in the policy sidecar.
- Leave the `TIER 1` through `TIER 4` category notes empty. Only `CORE ITEMS`
  and `OPTIONAL CORE` keep a Queue note.
- Require a concrete threat response and normal-item purpose before an item can move
  into `OPTIONAL CORE`; keep unsupported choices in their tier reference row.
- Keep CORE as the only automatic path while making all four tier menus sparse,
  disjoint, mechanics-labeled optional references.
- Generate build descriptions from pinned role, playstyle, archetype, and ability
  order without a model or network request.
- Encode a supported majority imbue target when it is a current hero ability.
- Derive visible build titles from CORE item composition so an ability-path label
  cannot misname a weapon-, spirit-, or vitality-heavy build.
- Show the first-maxed ability, highest-win-rate Tier 3 CORE item (Tier 4 fallback),
  and dominant build function as the three ordered build icons.
- Version the deterministic description artifact and generator as 9 / 1.

## [0.1.0] - 2026-08-01

### Added

- Linux-first `deadlock-build-sync sync` workflow for generating and safely
  installing private Deadlock hero builds.
- Analytics-backed item tiers, ability paths, purchase windows, and duration
  curves.
- Staged Codex narrative generation with schema and semantic validation.
- Fingerprint-aware artifact reuse and explicit regeneration controls.
- Steam account discovery, backups, atomic cache replacement, and restoration.
- Local linting, type checking, tests, packaging checks, and GitHub Actions CI.

[Unreleased]: https://github.com/sxndmxn/deadlock-build-sync/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sxndmxn/deadlock-build-sync/releases/tag/v0.1.0
