# Changelog

This file records notable project changes.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

Make one build for every active hero.
Estimate the effect of each item with a hierarchical ridge logistic regression at eight landmark times.
Compare owners with players at the same time, net worth, team lead, and rank.
Assemble MAIN CORE in lane, mid-game, and late-game phases from items that players use, tilted toward items with a positive effect.
Order MAIN CORE by the median net worth at purchase.
Show situational TIER 1 to TIER 4 items with a positive effect.
Select the key item by effect and by how much more this hero uses it than other heroes.
Test each build on the latest 20% of matches and show `strong`, `moderate`, or `limited` confidence.
Start each description with the key ability, the key item, and its power spike.
Infer ability focus from supported CORE imbue targets, current item properties, and ability upgrade order.
Use `ability + key item` titles, with the first fully upgraded ability as the fallback when focus evidence is weak.
Keep hero names out of titles.
State the inferred focus and the first fully upgraded ability separately.
Show four lines for each item: the game phase, the win rate, the pick rate, and the soul window.
Lower the default minimum rank from `emissary-i` to `ritualist-i`.
Write `hero-builds.json` and one Markdown file per hero. Replace the complete artifact directory on each run.
Include the analysis code in every build. The `analysis` feature no longer exists.
Download only ranked matches in the selected rank range, and read the remote data with 64 threads.
With one week of matches, a build takes about 2 minutes instead of about 11 minutes.
Each analysis run uses 0.9 GiB instead of 4.3 GiB.
Send the ability order requests from four threads during the local analysis.
After a successful build, remove the other analysis runs whose name has the automatic format.
Describe every option in `--help`.
Name the update command when `status` finds stale builds.

### Removed

Remove the admission method with exact core sets, Eclat, Leiden, and pairwise ordering.
It gave builds for only 2 to 8 of 40 heroes in the first days of a patch.
Remove the strategy context, policy, narrative, and evidence artifacts.
Remove the `refresh-evidence`, `quality-report`, `preview`, `install-artifacts`, `export-context`, and `generate-narratives` commands.
Remove rank expansion, subset bundles, and the API response cache.

### Fixed

Read the remote match catalog in the DuckDB 2.0 storage format.
Verify all seven source JSON fingerprints before resuming an extracted run.
Check the current patch and client version in the shared installation function for both `sync` and `install`.
Restore native IMBUE ABILITY selection for MAIN CORE and situational items with sufficient evidence.
Store imbue evidence and inferred ability focus in catalog schema 5. Earlier catalogs require regeneration.
Report the installed cache as current after a partial sync when the synced heroes match.
Require a valid SHA-256 fingerprint before restoring a Steam backup.
Recover interrupted artifact installation under the artifact lock.

### Added

Use `bash scripts/check_repository.sh` for the shared local and CI verification command.
Run isolated executable checks with temporary Steam caches and the existing KV3 reference fixture.
These checks do not certify live builds.

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
