# Decision log: untangle deadlock-build-sync (2026-11-08)

Sources: survey-analysis.md, survey-steam.md, survey-cli-guides.md, audit-steam.md, audit-input-cli.md, skeleton.txt, imports.txt, git churn.
Rule for every fix: pieces that change together end up together, pieces that do not are not tied, everything depends on what changes less.
Behavior test: `build --resume` on run 20261108T013049Z must reproduce the baseline catalog (exact, except the 6 float fields from DuckDB parallel sums and API drift, see Fix 1).

## Fix 1. Record the API inputs of a run in the run directory, so a resumed run is reproducible.
Production writes raw/ability-orders.json and raw/build-tags.json during the first build and reads them on --resume.
- hero_build_production.rs:135-196 requests ability orders and tags live, even on --resume; the API adds late matches, so two builds of one run differ in 53 ability_matches fields and `status` reports the Steam cache stale.
- refresh.rs:134-160 validate_resume does not compare production_method or implementation; it cannot, because the production inputs are not in the run.
- Experiments cannot test the ability selection, because they have no recorded rows.

## Fix 2. One typed run manifest and one typed patch record. No string keys across modules.
`RunManifest` (serde struct) in refresh_configuration.rs, written by refresh.rs and read by run_inputs.rs, hero_build_production.rs, validate_resume. `PatchRecord` (serde struct) replaces `patch: Map<String, Value>` in HeroBuildCatalog; `Patch::to_document` becomes `Patch::record()`.
- hero_build_production.rs:41-45,105-107 read "cohort", "as_of", "since", "sources", "client_version", "extraction", "player_matches" by string; refresh.rs:188-191 and refresh_configuration.rs:62 write them; check_safety/resume_checks.rs:125-126 writes them by hand.
- hero_build.rs:22 patch is an untyped Map; api_patch.rs:29-40 writes "identity" and "title"; build_workflow.rs:127 reads "identity"; hero_presentation.rs:233-238 reads "title" with unwrap_or_default; freshness_checks.rs:46 writes "identity".
- Patch title keeps the feed's leading space (" Minor Update - 11-04-2026") and reaches the Steam description as "Patch:  Minor…". The record trims at parse.
- Manifest keys that nothing reads: production_method, implementation, extraction.{match_folds, purchases, heroes, source_snapshot_version, extracted_minimum_badge}. The struct keeps only read fields.
- hero_presentation.rs:221-222 cuts cohort dates to 10 bytes; depends on the to_rfc3339 format at refresh_configuration.rs:164. The record gives a date accessor.
- Production patch cutoff Some(as_of) vs staleness None (api_patch.rs:59): a catalog built with --as-of in the past is always stale. Staleness compares with the same cutoff rule (latest patch at or before now is the only valid "current"; document this, no behavior change).

## Fix 3. One definition of the managed-build description: a `ManagedDescription` type in deadlock-guides with render and parse.
- hero_presentation.rs:225-228 writes marker, "Build path: X.", "Patch: X.", "Snapshot: X."; build_metadata.rs:27 parses the path; cache_request.rs:67 checks the snapshot as an exact line; compare_managed_heroes.rs:33 and dump_category_sizes.rs:72 parse again; check_safety/reference_data.rs:48 writes the format by hand.
- path_id format hero_build.rs:373-378; character rule twice: hero_build.rs:584-587 and build_metadata.rs:28-31 (parse side lacks the 80-byte limit).
- BuildKey derived two ways: parse description (cache_request.rs:56-79) and path_id() (freshness.rs:107-110).
- ManagedBuild::new builds a fake HeroBuildMetadata (cache_request.rs:59-66) to reuse the parser for write validation.
- Snapshot ID passed three ways (build_workflow.rs:214-217) and checked twice (cache_request.rs:67,132).
- LEGACY_MANAGED_MARKER (v1): is_managed accepts it (build_metadata.rs:41) but managed_path rejects it; sync removes v1 builds (cache_plan.rs:193-196), status ignores them (cache_status.rs:69); no check covers v1. Decision: keep removal of v1 builds (user data from this tool), make status count them as stale, one code path.

## Fix 4. One managed-build scan of the Steam cache, with one rule for unreadable blobs.
`scan_managed_builds(cache, account_id) -> Result<ManagedScan { builds: BTreeMap<BuildKey, &[u8]>, unreadable: usize }>` in cache_scan.rs, used by cache_plan, cache_status, examples. A blob that this tool cannot parse is unrelated user data: both sync and status keep it and report the count (AGENTS.md: preserve unrelated private builds). Status stops reporting "malformed" for such a blob.
- "Managed build of a target hero" exists three times: cache_plan.rs:171-180, cache_scope.rs:32-41, cache_status.rs:59-86.
- cache_plan.rs:176,239-240,272-273 and cache_scope.rs:35-36 treat unparseable blobs as unmanaged; cache_status.rs:65 errors. A managed blob that fails to parse is kept and sync creates a second build for its path.
- KV3 section names repeated: "Unpublished" in cache_plan.rs:74,115,264,311, cache_read.rs:58,63, cache_scope.rs:16, cache_status.rs:61, three examples; "Favorites"/"SavedLastUsed" in cache_plan.rs:264, cache_read.rs:57,59. One `sections` constant set.
- Local-ID test duplicated cache_plan.rs:241-244 and :275-278 over different sections; limit 1000 at :200,:279,:289. next_local_id does not scan LastUsedBuilds (audit 6).
- cache_scope.rs exists only for out_of_scope_sha256 (cache_plan.rs:165-167), which nothing reads; normalize_float can fail a sync. Remove the module and the manifest key. validate_preserved_values keeps preservation.
- Dead: ManagedBuild::key, InstallResult.build_ids, HeroBuildMetadata.version and tag_ids (parsed, never read), BuildIdentity::validate repeats validate_sha256.
- examples/list_managed_builds.rs:39 defaults the path to "main", which is not a valid path; it uses the scan instead.

## Fix 5. Backups: one layout module. (The restore selection rule stays as it is: the user did not select "Restore toggles".)
- "backups/<account>" built twice (cache_backup.rs:19-22, cache_restore.rs:63-66), hard-coded in check_safety/steam_checks.rs:189,199; manifest keys written in four files, read in cache_restore.rs:40,80,101,104.
- cache_restore.rs:76 one malformed manifest stops restore; :73 incomplete directories are skipped; :86 selects by created_at only, so `restore --latest` twice toggles.
- Backups copy remotecache.vdf and store remote_cache_sha256; nothing restores them. Decision: keep the copy (Steam Cloud state), record why in one comment; do not add retention (owner decision).

## Fix 6. Experiments call the production assembly. One `HeroAssembly` with recorded gates.
`assemble_hero_builds` returns, per hero, the main build, the selected variants, and `dropped: Vec<(item_id, VariantGate)>` from both the development selection and the production re-check. hero_build_production prints the drops from this data; `explain_variant_candidates` and `compare_variant_agreement` call the same function.
- experiments/variant_candidates.rs:78-104 re-implements hero_build_production.rs:317-342; iterates in catalog order, so production_gate can differ.
- compare_variant_agreement (build_agreement.rs:132-184) skips the all-fold re-assembly and dedupe.
- Preamble (load, split, estimate effects) copied at build_agreement.rs:53-57,136-140,258-260,371-375,416-420,542-546,683-687,738-742: one `RunStudy::load(paths, resources)` holding inputs, folds and development effects.
- summarize_owners (build_variants.rs:379-413) re-implements summarize_hero (item_effects.rs:323-374).
- Pass-throughs: select_item_variants → _with_rule → evaluate_item_variants; the rule becomes a field of the assembly options, one function.
- Dead branch: UnsupportedItem filter in assemble_item_variant (build_variants.rs:267).
- 18 examples repeat ExtractionResources {12_000, 8}: `ExtractionResources::default()` is the one definition, and the clap defaults read it.

## Fix 7. Production options flow as one struct from the CLI to the analysis, and the catalog records them.
`ProductionOptions { variant_selection: VariantSelection }` is a field of `RefreshRequest`'s sibling `BuildRequest`; the CLI gains `--variant-distinct-items` (default 2) and `--variant-separation` (default 0.30); `HeroBuildCatalog` gains `rules: BuildRules { variant_distinct_items, variant_separation }` next to `method`.
- The user asked for a tolerance option for alternate builds; the binding gate is the distinct-item count.
- build_workflow.rs:38-59 copies BuildArguments into ExtractionResources, RefreshRequest and produce_hero_builds; resources and base_url are passed twice.
- build_workflow.rs:21-23 imports the clap struct, cli_output and cli_paths; print_installation and eprintln are CLI output inside the workflow. The workflow takes `BuildRequest`, the CLI converts arguments and prints.
- Rank defaults disagree: CLI ritualist-i vs RankRange::default emissary-i (rank.rs:141). One default in deadlock-data.
- 12000/8 at cli_arguments.rs:94,97, README.md:129-130 and examples (see Fix 6).

## Fix 8. Every active hero gets a build, and the catalog proves it.
A hero with fewer than 100 rows at every landmark gets a build from the all-hero effects and the all-hero adoption (a generic build with the `limited` label, as AGENTS.md requires). BEHAVIOR CHANGE, needs user approval. The ability-request change (one failed request no longer stops the run) is also a BEHAVIOR CHANGE. `HeroBuildCatalog::validate` rejects an empty hero list; production rejects a catalog that lacks an active hero.
- hero_build_production.rs:287-296 skips a hero; AGENTS.md: "Do not skip a hero to hide weak evidence". No validator detects the skip. The manifest counts 44 heroes in matches against 42 active; two get no message.
- Empty catalog accepted (hero_build.rs:423-466): zero matches replace good artifacts, build exits 0, status reports "Validated 0 hero builds" current.
- expected_hero_ids comes from catalog.heroes (build_workflow.rs:184-188), so the coverage check at cache_request.rs:124 cannot fail; it compares against the active list instead.
- "Active hero" has two meanings: sources.rs:100-108 (game_mode) vs hero_build_production.rs:463-464 (player_selectable). One predicate in sources.rs; heroes.json holds the result.
- hero_build_production.rs:90,191,432,446-447: one failed ability request or a hero without a complete ability order stops the whole run. The ability order is optional data; a failure leaves the order unset for that hero (already allowed by the schema).

## Fix 9. The artifact destination must be an artifact directory.
- cli_paths.rs:168-181, build_workflow.rs:74-98, artifact_transaction.rs:73,177: `--artifacts ~/Documents` moves the directory aside and remove_dir_all deletes it. ArtifactTransaction::new refuses a non-empty destination without hero-builds.json.
- Recovery runs twice (build_workflow.rs:36 and ArtifactTransaction::new:20).
- cli_paths.rs:32 does not canonicalize the default path, so a symlinked default is refused (audit 8).

## Fix 10. One text model for a build, rendered by Markdown and by Steam.
`BuildText` in deadlock-guides: focus sentence, ability sentence, variant sentence, evidence sentence, phase label, souls format, soul window format. Both renderers consume it.
- Two renderers apply different rules to the same data (survey table: net worth, phase, soul window, rank, counter phase text, rate sentence).
- Copied sentences: "Ability order: max … first." and "Item choices use …" in both files; evidence sentences in three places plus README.
- Confidence text from serde snake_case (cli_commands.rs:33, build_workflow.rs:235) and label() (hero_build.rs:361).
- Panel names in CounterTarget::panel_name and COUNTER_PANELS (presentation.rs:83); "MAIN CORE"/"TIER n" literals in two files; 50-char limit const and literal; 240-byte limits literals.
- The 4x4 ability rule in four places (ability_order.rs:116-117, build_tags.rs:80, presentation.rs:151, hero_build.rs:290); focus support rule twice (ability_focus.rs:52, hero_build.rs:288-291).
- describe_counter_panel repeats validation then returns a constant.

## Fix 11. Landmarks and thresholds have one home each.
- EVALUATION_LANDMARKS ⊇ PHASES ⊇ late phases; KEY_ITEM_PHASES (build_variants.rs:15), COUNTER_PHASES (counter_items.rs:64), `>= 1200` (build_agreement.rs:757): one `landmarks` module; late phases derived from PHASES. run_inputs checks the loaded landmark set against EVALUATION_LANDMARKS (fail fast on the SQL link).
- 100 with two meanings (MINIMUM_OWNERS :322,:368) and MINIMUM_HERO_ROWS (item_effects.rs:15); doc text repeats the number.
- tier >= 3 at build_assembly.rs:243, build_variants.rs:181,430: `ItemAsset::is_expensive()`.
- 3%: score_item uses MINIMUM_ADOPTION not adoption_floor (build_assembly.rs:97) — the experiment knob changes only the gate, not the score; document, keep production equal.
- Fold name "test" in create_match_folds.sql:7 and item_effects.rs:36; split shares in SQL and extraction.rs:299-301: one SQL parameter each.
- Covariate columns 0-3 repeated in three files: one `covariates(state)` function.
- "analysis.duckdb" literal in three files; run layout written twice (RunPaths::create and ::open): RunPaths owns the names.
- Trace limits 100 MiB vs 101 MiB and mode strings in two crates; User-Agent "0.1" vs 0.2.0 (`env!("CARGO_PKG_VERSION")`).

## Fix 12. Remove surplus.
- Checks that cannot fail: cli_commands.rs:75 (--latest required by clap), trace_summary.rs:109 (zero nodes forbidden by clap).
- Dead: deadlock_data::field export, BuildTag.class_name/label, format_sha256, AXIS_CLASSES/COMPLEXITY_CLASSES, unused SQL outputs discovery_end/observed_players/train-validation labels, GroupInteraction reuse for non-counter values (rename to `Coefficient`), build.rs hashing experiments and examples into the implementation fingerprint.
- Always-default parameters: ApiOptions.timeout/request_interval; build_category annotate; required_flex_slots/sell_priority always None.
- build_tags and fallback tag selection live in hero_build_production.rs:410-454 but AGENTS.md gives tags to deadlock-guides: move.
- deadlock-guides → deadlock-input dependency (build_tags.rs:4) for non-network data: move BuildTagCatalog, FUNCTION_CLASSES and clean_mechanical_text to deadlock-guides; the arch-lint network deny list for guides becomes redundant and stays as a gate.
- Untracked examples compare_managed_heroes.rs and dump_category_sizes.rs duplicate production: delete after the owner confirms.

## Comments (user chose)
Remove comments that restate the code. Keep comments about the outside world (Steam layout sizes, API behavior, DuckDB behavior, research-log references).

## Tests (user chose, last)
Checks that only repeat the implementation or cannot fail are removed or rewritten against behavior. From the surveys: check_variants (separation always 1.0, two candidates = maximum, no production re-check) gets items that share CORE so the cost-share rule and the limit are exercised, and calls the production assembly; counter_checks uses distinct items and evidence per target and a z between −2 and 0; freshness_checks calls build_freshness_report and checks exit codes; check_reference_fixture (encoder round trip only) keeps a real Steam fixture or goes; focus_checks exact-string assertions become behavior checks (title limit with a long persona).

## Not in this pass (owner decisions)
- Patch detection by the word "update" (F5). Needs Valve post conventions.
- Backup retention and remotecache.vdf restore.
- Process guard matching any argument named "deadlock" (user did not select).
- DuckDB float nondeterminism in parallel sums (6 fields).
- Behavior of status after a title change (documented: titles ignored).

## Status on 2026-11-08

Done on branch `refactor/untangle`, one commit for each fix: 1, 2, 3, 4, 5 (layout only), 6, 7, 8, 9, 10, 11, 12, the comment pass, and the test pass.
Behavior test: `build --resume --extraction-threads 1` on one named run reproduces the catalog of the previous commit, and `dump_presentations` shows the same Steam text. The first eleven fixes were tested on run `20261108T013049Z`. A named run then removed that automatic run, as documented, so the later fixes were tested on `refactor-fresh-check` and `refactor-check-2`, two extractions of the same cohort with the same counts.
Steam text changed in one place: the patch title lost its leading space (Fix 2).

Not done, with the reason:

- Fix 5 restore selection: the owner did not select it.
- Fix 12 `required_flex_slots` and `sell_priority`: they are Steam schema fields, so they stay.
- Fix 12 `compare_managed_heroes.rs` and `dump_category_sizes.rs`: untracked owner files.
- `measure_counter_placebo` tests the model without hero terms while production uses hero terms. A change alters a documented experiment (E29), so it waits for a research-log entry.
- `layout_checks` has no sizes for 3, 7 to 9, 11, or more than 14 items. The sizes come from the game and cannot be invented.
- The `#[path]` includes in `check_imbues`, `check_item_statistics`, `check_variants`, `imbue_checks`, and `artifact_checks` compile private modules. They stay until the checks move behind public interfaces.
- The examples `compare_key_item_signal`, `compare_situational_signal`, and `compare_variant_agreement` differ only by the function they call.
