# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Use the selected or resolved Steam persona as the installed build-title prefix.

### Added

- Bounded concurrent hero narrative pipelines with atomic progress checkpoints and
  rate-limit-aware backpressure.
- Read-only artifact freshness, evidence refresh, and state-aware recommendation
  commands.
- Pinned build tags, archetype titles, tactical hover projection, and typed
  situational counter cards.
- An optional offline analysis extra with component-aware sequence evidence,
  same-opportunity comparator gates, and fail-closed branch admission.

### Changed

- Keep CORE as the only automatic path while making all four tier menus sparse,
  disjoint, mechanics-labeled optional references.
- Limit Luna generation to one validated build-level description per path; item
  hovers and category text are deterministic.
- Show purchase window, win rate, pick rate, buyer matches, and purchase events in
  item hovers. Encode a supported majority imbue target when it is a current hero
  ability.
- Derive visible build titles from CORE item composition so an ability-path label
  cannot misname a weapon-, spirit-, or vitality-heavy build.
- Show the first-maxed ability, highest-win-rate Tier 3 CORE item (Tier 4 fallback),
  and dominant build function as the three ordered build icons.
- Version the description-only narrative schema and prompt as 8 / 25.

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
