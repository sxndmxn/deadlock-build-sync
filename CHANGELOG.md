# Changelog

This file records notable project changes.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

Report the installed cache as current after a partial sync when the synced heroes match.
Report how many other heroes keep managed builds from an earlier install.

Require a valid SHA-256 fingerprint before restoring a Steam backup.
Reject missing, malformed, and mismatched fingerprints before any backup or cache write.

Record artifact recovery information before moving the previous directory.
Recover interrupted installation under the artifact lock before building, syncing, or installing artifacts.
Preserve the previous directory when installation stops before replacement.

Propagate analysis execution errors instead of recording them as unsupported candidates.
Record unsupported purchase orders and incomplete component observations as candidate rejections.

Preserve full-roster artifacts when `build` or `sync` selects one hero.
Write subset bundles to an adjacent directory and report their location.
Check the current patch and client version before installing reviewed artifacts.
Compare complete managed guide contents when reporting installed-build freshness.
Select restore backups by account and canonical cache path before comparing creation times.

Preserve concurrent cache changes when installation stops before replacement.
Refuse backup restoration while Deadlock is running.
Verify exact backup filename casing and JSON-stable guide fingerprints.

Use the selected or resolved Steam persona as the installed build-title prefix.
Size each Steam category from its item count so Steam shows all item rows.

Reject null reward eligibility, extra source players, and incomplete team wealth.
Exclude purchases after match completion from extraction.
Restrict split-boundary detection to the current database and schema.

### Added

Use `bash scripts/check_repository.sh` for the shared local and CI verification command.
Check formatting, Clippy, architecture, parsing, complexity, SQL, documentation, dependencies, and the default build.
Use `--release` to include release archive validation outside the source checkout.

Run isolated executable checks with temporary Steam caches and the existing KV3 reference fixture.
Check data preservation, repeated installation, process guards, concurrent changes, backup validation, restoration, and interrupted artifact installation.
These checks do not certify live builds.

Retain read-only artifact freshness and evidence refresh commands.
Use pinned build tags, archetype titles, tactical hover descriptions, and typed situational counter cards.
Provide optional offline analysis with component-aware sequence evidence and comparator requirements for the same purchase opportunity.
Reject branches that fail admission checks.

### Changed

Calculate purchase-pool statistics, checkpoint counts, and checkpoint wealth in DuckDB.
Select checkpoint fields in SQL.
Reuse extracted first purchases and preserve purchase-order rules.
Remove unused purchase-time quartiles from item metrics.
Check all research SQL files with SQLFluff and include those files in data fingerprints.

Remove Beam search, scoring, metadata, and the `--generator` option.
Use Eclat, Leiden, and pairwise purchase ordering for normal build production.
Require `eclat-leiden-pairwise-v4` after the SQL validation corrections.
Generate fresh evidence instead of resuming an older source extraction.
Reject unsupported Beam artifacts.
Use exact-core discovery buyers for all item pools.
Retain every supported legal identity without a build-count limit per hero.
Group related exact cores into one guide with a default purchase order and optional variants.
Preserve each variant's path, evidence, costs, and pool.
Group frozen core items before validation.

Use one purchase guide for Steam rows, Markdown, JSON, recommendations, and installation checks.
Keep only the validated component path in the automatic purchase order.
Support selected optional items, placement overrides, inventory planning, wealth conditions, enemy conditions, and separately admitted core substitutions.

Use CORE, CORE OPTIONAL, and TIER 1–4 for the visible guide.
Combine variant items without duplicate cards.
Keep full purchase instructions in descriptions and detailed files.
Keep CORE as the only automatic path.
Use sparse, disjoint tier menus as optional references with item mechanics labels.
Require a supported threat response and normal-item purpose before optional core placement.
Keep unsupported choices in their tier reference row.

Show one two-line statistics card per item: `SOUL WINDOW`, then `PR`, `WR`, and `TOTAL GAMES`.
Replace the four-line `USE` / `WHY` / `SKIP` / `DATA` card.
Replace the five-line `VS` / `WHY` / `SWAP` / `WHEN` / `SKIP` card and the five-line `CORE ITEMS` block.
Remove the `IMBUE` line because Steam shows the imbue icon.
Reject stored artifacts whose cards differ from the evidence.
Keep conditional decisions in the policy sidecar.
Leave TIER 1–4 category notes empty.
Keep purchase order notes for core categories.

Remove generic build prose, repeated variant descriptions, and generic item-purpose advice.
Show core costs and observed sample counts per path.
Preserve purchase instructions, item statistics, and managed build identities.
Generate descriptions from pinned roles, playstyles, archetypes, and ability orders without a model or network request.
Encode a supported majority imbue target only when the target is a current hero ability.
Derive visible titles from CORE item composition.
Show three ordered build icons: the first-maxed ability, the highest-win-rate Tier 3 CORE item, and the dominant build function.
Use a Tier 4 CORE item when no Tier 3 CORE item is available.
Use description artifact version 9 and generator version 1.

Use compact categories for context generation and canonical reconstruction.
Remove the discarded detailed panel builder and unused projection branches.
Remove the `recommend` command and unused policy evaluator.
Retain guide recommendations for quality replay.

Require evidence schema 13, context schema 18, projection guide version 6, and purchase guidance schema 4.
Keep state schema 3 and guide index and group schema 2.
Refresh and rebuild older artifacts before installation.

Archive comparison code and its tests in Git history.
Remove unused reconstruction and producer paths.
Reuse the durable byte writer without changing JSON serialization.
Use reference fixtures and isolated executable checks for current safety verification.
Unit tests remain deferred until the user requests them.

## [0.1.0] - 2026-08-01

### Added

Add `deadlock-build-sync sync` to generate and safely install private Deadlock hero builds, with Linux as the primary platform.
Use analytics for item tiers, ability paths, purchase windows, and duration curves.
Add staged Codex narrative generation with schema and semantic validation.
Reuse compatible artifacts through fingerprints and provide explicit regeneration controls.
Add Steam account discovery, backups, atomic cache replacement, and restoration.
Add local linting, type checking, tests, packaging checks, and GitHub Actions CI.

[Unreleased]: https://github.com/sxndmxn/deadlock-build-sync/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sxndmxn/deadlock-build-sync/releases/tag/v0.1.0
