use std::collections::BTreeMap;
use std::path::Path;

use deadlock_data::{
    Error, RankRange, Result, integer, parse_timestamp, read_json, text, trace_operation,
};
use deadlock_guides::{
    BuildCohort, BuildEvaluation, BuildRules, CounterEvidence, HERO_BUILD_METHOD,
    HERO_BUILD_SCHEMA_VERSION, HeroBuild, HeroBuildCatalog, TagItem, assign_build_focus,
    select_ability_path, select_build_tags,
};
use deadlock_input::{ApiOptions, BuildTagCatalog, DeadlockApi, parse_patch_feed};
use serde_json::Value;

use crate::api_inputs::{AbilityRequest, ApiInputs, request_inputs};
use crate::build_assembly::{AssembledBuild, PHASES, PurchaseMedians, assemble_build};
use crate::build_evaluation::{evaluate_build, shrink_evaluations};
use crate::build_variants::{
    VariantSelection, assemble_item_variant, select_item_variants_with_rule,
};
use crate::counter_items::{CounterGroups, estimate_counter_evidence, select_counter_panels};
use crate::item_effects::{EffectTable, ItemCatalog, LandmarkState, estimate_item_effects};
use crate::item_imbues::{ItemImbues, attach_item_imbues, load_item_imbues};
use crate::item_statistics::{HeroItemStatistics, attach_item_statistics, load_item_statistics};
use crate::refresh_configuration::{ExtractionResources, RunPaths};
use crate::run_inputs::{load_assembly_inputs, open_run_database};
use crate::run_manifest::RunManifest;

/// Produces a main build and distinct supported variants for each active hero.
///
/// The test fold measures each build assembled from the other folds.
/// The installed build uses all folds, so it uses all available matches.
///
/// # Errors
/// Returns an error when the run, the analysis database, a model, or the API fails.
pub fn produce_hero_builds(
    paths: &RunPaths,
    resources: ExtractionResources,
    api_base_url: &str,
    rules: &BuildRules,
) -> Result<HeroBuildCatalog> {
    rules.validate()?;
    let selection = VariantSelection::from_rules(rules);
    let manifest = RunManifest::read(paths)?;
    let ranks = manifest.cohort.ranks()?;
    let as_of = parse_timestamp(&manifest.cohort.as_of)?;
    let patch = parse_patch_feed(&read_json(&paths.raw.join("patches.json"))?, Some(as_of))?;
    let client_version = manifest.sources.client_version;
    let heroes = read_hero_names(&paths.raw.join("heroes.json"))?;
    let mut api = build_api(api_base_url, ranks, client_version, as_of)?;
    let mut api_inputs = ApiInputs::load(paths)?;
    let main_requests = heroes
        .keys()
        .map(|hero_id| (*hero_id, Vec::new()))
        .collect::<Vec<_>>();
    let missing = api_inputs.missing_requests(&main_requests);
    let needs_tags = !api_inputs.has_build_tags();
    // The API requests wait on a fixed request interval, so they run during the local work.
    let (local, requested) = std::thread::scope(|scope| {
        let requests =
            scope.spawn(|| request_inputs(&mut api, needs_tags, &missing, patch.start_timestamp));
        let local = assemble_from_database(paths, resources, ranks, &heroes, selection);
        let remote = trace_operation("analysis.wait_for_api", Some("wait_for_api"), || {
            requests
                .join()
                .map_err(|_| Error::new("API requests stopped unexpectedly"))?
        });
        Ok::<_, Error>((local?, remote?))
    })?;
    api_inputs.record(requested);
    // A variant build needs the ability orders of the players who own its key item.
    let variant_requests = local
        .builds
        .iter()
        .map(ability_request)
        .filter(|(_, items)| !items.is_empty())
        .collect::<Vec<_>>();
    let missing = api_inputs.missing_requests(&variant_requests);
    if !missing.is_empty() {
        api_inputs.record(request_inputs(
            &mut api,
            false,
            &missing,
            patch.start_timestamp,
        )?);
    }
    api_inputs.save(paths)?;
    let assets = read_json(&paths.raw.join("items-all.json"))?;
    let assets = assets
        .as_array()
        .ok_or_else(|| Error::new("Item assets must be an array"))?;
    let tags = BuildTagCatalog::from_assets(api_inputs.build_tags()?)?;
    let builds = local
        .builds
        .into_iter()
        .map(|build| {
            let rows = api_inputs.ability_rows(&ability_request(&build));
            let mut build = attach_ability_and_tags(build, rows, assets, &tags)?;
            attach_item_imbues(&mut build, &local.imbues, assets);
            attach_item_statistics(&mut build, &local.statistics)?;
            assign_build_focus(&mut build, assets)?;
            Ok(build)
        })
        .collect::<Result<Vec<_>>>()?;
    let catalog = HeroBuildCatalog {
        schema_version: HERO_BUILD_SCHEMA_VERSION,
        method: HERO_BUILD_METHOD.into(),
        rules: *rules,
        client_version,
        patch,
        cohort: BuildCohort {
            minimum_badge: ranks.minimum.badge(),
            maximum_badge: ranks.maximum.badge(),
            since: manifest.cohort.since.clone(),
            as_of: manifest.cohort.as_of.clone(),
            player_matches: manifest.extraction()?.player_matches,
        },
        counter_evidence: local.counter_evidence,
        heroes: builds,
    };
    catalog.validate()?;
    Ok(catalog)
}

/// Returns the ability order request of a build. Only a variant build filters by its key item.
fn ability_request(build: &HeroBuild) -> AbilityRequest {
    let items = build
        .variant_id
        .as_ref()
        .map_or_else(Vec::new, |_| vec![build.key_item_id]);
    (build.hero_id, items)
}

/// The builds, the counter evidence, and the item data from the extracted matches.
struct LocalBuilds {
    builds: Vec<HeroBuild>,
    counter_evidence: Vec<CounterEvidence>,
    imbues: ItemImbues,
    statistics: HeroItemStatistics,
}

/// Reads the extracted matches and assembles the builds of each hero.
fn assemble_from_database(
    paths: &RunPaths,
    resources: ExtractionResources,
    ranks: RankRange,
    heroes: &BTreeMap<u64, String>,
    selection: VariantSelection,
) -> Result<LocalBuilds> {
    let (database, parameters) = open_run_database(paths, resources, ranks)?;
    let inputs = load_assembly_inputs(&database, &parameters)?;
    let imbues = load_item_imbues(&database, &parameters)?;
    let statistics = load_item_statistics(&database, &parameters)?;
    drop(database);
    let (builds, counter_evidence) = assemble_hero_builds(
        &inputs.states,
        &inputs.catalog,
        &inputs.medians,
        heroes,
        selection,
    )?;
    Ok(LocalBuilds {
        builds,
        counter_evidence,
        imbues,
        statistics,
    })
}

/// Assembles the builds of each hero and adds counter panels for groups that pass the run test.
fn assemble_hero_builds(
    states: &[LandmarkState],
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
    heroes: &BTreeMap<u64, String>,
    selection: VariantSelection,
) -> Result<(Vec<HeroBuild>, Vec<CounterEvidence>)> {
    let development = states
        .iter()
        .filter(|state| !state.is_test())
        .collect::<Vec<_>>();
    eprintln!("Estimating item effects for the held-out test");
    let development_effects = estimate_item_effects(&development, catalog, &PHASES)?;
    eprintln!("Estimating item effects from all matches");
    let all = states.iter().collect::<Vec<_>>();
    let effects = estimate_item_effects(&all, catalog, &PHASES)?;
    let mut builds = Vec::new();
    for (hero_id, hero_name) in heroes {
        builds.extend(assemble_hero(
            *hero_id,
            hero_name,
            states,
            &effects,
            &development_effects,
            catalog,
            medians,
            selection,
        )?);
    }
    for variants in [false, true] {
        let mut pool = builds
            .iter_mut()
            .filter(|build| build.variant_id.is_some() == variants)
            .map(|build| &mut build.evaluation)
            .collect::<Vec<_>>();
        shrink_evaluations(&mut pool);
    }
    eprintln!("Testing counter item groups");
    let groups = CounterGroups::from_catalog(catalog);
    let evidence = estimate_counter_evidence(&all, catalog, &groups)?;
    for build in &mut builds {
        build.counters =
            select_counter_panels(build, &effects, catalog, medians, &groups, &evidence);
    }
    Ok((builds, evidence))
}

#[expect(
    clippy::too_many_arguments,
    reason = "Fix 6 of the decision log replaces these arguments with one assembly context."
)]
fn assemble_hero(
    hero_id: u64,
    hero_name: &str,
    states: &[LandmarkState],
    effects: &EffectTable,
    development_effects: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
    selection: VariantSelection,
) -> Result<Vec<HeroBuild>> {
    let all = states
        .iter()
        .filter(|state| state.hero_id == hero_id)
        .collect::<Vec<_>>();
    if all.is_empty() {
        eprintln!("Skipping {hero_name}: the run has no matches of this hero");
        return Ok(Vec::new());
    }
    let (test, development): (Vec<_>, Vec<_>) =
        all.iter().copied().partition(|state| state.is_test());
    let Some(main) = assemble_build(hero_id, effects, catalog, medians) else {
        eprintln!("Warning: Skipping {hero_name}: no item has enough owners");
        return Ok(Vec::new());
    };
    let development_main = assemble_build(hero_id, development_effects, catalog, medians);
    let evaluation = match &development_main {
        Some(build) => evaluate_build(&test, &build.phase_sets, catalog)?,
        None => evaluate_build(&[], &main.phase_sets, catalog)?,
    };
    let observations = PHASES
        .iter()
        .filter_map(|phase| effects.get(&(hero_id, *phase)))
        .map(|phase| phase.observations)
        .max()
        .unwrap_or(0);
    let mut installed = vec![main.clone()];
    let mut builds = vec![create_hero_build(
        hero_id,
        hero_name,
        main,
        evaluation,
        observations,
        None,
    )?];
    if let Some(development_main) = development_main {
        for variant in select_item_variants_with_rule(
            hero_id,
            &development,
            development_effects,
            catalog,
            medians,
            &development_main,
            selection,
        )? {
            let item_id = variant.build.key_item_id;
            let Some(production) =
                assemble_item_variant(hero_id, item_id, &all, effects, catalog, medians)?
            else {
                eprintln!(
                    "Dropped an additional build for {hero_name}: item {item_id} has no build from all matches"
                );
                continue;
            };
            if installed
                .iter()
                .any(|build| !selection.is_distinct(build, &production.build, catalog))
            {
                eprintln!(
                    "Dropped an additional build for {hero_name}: item {item_id} is similar to an installed build"
                );
                continue;
            }
            let evaluation = evaluate_build(&test, &variant.build.phase_sets, catalog)?;
            installed.push(production.build.clone());
            builds.push(create_hero_build(
                hero_id,
                hero_name,
                production.build,
                evaluation,
                production.owners,
                Some(format!("item-{item_id}")),
            )?);
        }
    }
    eprintln!("Selected {} builds for {hero_name}", builds.len());
    Ok(builds)
}

fn create_hero_build(
    hero_id: u64,
    hero_name: &str,
    build: AssembledBuild,
    evaluation: BuildEvaluation,
    observations: usize,
    variant_id: Option<String>,
) -> Result<HeroBuild> {
    Ok(HeroBuild {
        hero_id,
        hero_name: hero_name.into(),
        variant_id,
        power_spike_net_worth: build
            .core
            .iter()
            .find(|item| item.item_id == build.key_item_id)
            .map_or(0, |item| item.median_net_worth),
        title: String::new(),
        tag_ids: [0; 3],
        key_ability_name: None,
        ability_focus: None,
        core: build.core,
        situational: build.situational,
        key_item_id: build.key_item_id,
        ability_ids: Vec::new(),
        ability_matches: 0,
        evaluation,
        observations: u64::try_from(observations)?,
        counters: Vec::new(),
    })
}

fn build_api(
    api_base_url: &str,
    ranks: RankRange,
    client_version: u64,
    as_of: i64,
) -> Result<DeadlockApi> {
    DeadlockApi::new(ApiOptions {
        base_url: api_base_url.into(),
        rank_range: ranks,
        client_version: Some(client_version),
        as_of_timestamp: as_of,
        ..ApiOptions::default()
    })
}

/// Adds the most supported complete ability order and the three build icons.
///
/// The icons are the first maxed ability, the key item, and the dominant build function.
/// Without a complete ability order, the icons use CORE items instead of the ability.
fn attach_ability_and_tags(
    mut build: HeroBuild,
    rows: &[Value],
    assets: &[Value],
    tags: &BuildTagCatalog,
) -> Result<HeroBuild> {
    if let Some(path) = select_ability_path(rows)? {
        build.ability_ids = path.ability_ids;
        build.ability_matches = path.matches;
    }
    let mut core = build
        .core
        .iter()
        .map(|item| TagItem {
            item_id: item.item_id,
            tier: if item.item_id == build.key_item_id {
                3
            } else {
                item.tier.min(2)
            },
        })
        .collect::<Vec<_>>();
    core.sort_by_key(|item| std::cmp::Reverse(item.tier));
    match select_build_tags(&build.ability_ids, &core, assets, tags) {
        Ok(selection) => {
            build.tag_ids = selection.tag_ids;
            build.key_ability_name = Some(selection.ability_name);
        }
        Err(_) => build.tag_ids = select_fallback_tags(&build)?,
    }
    Ok(build)
}

fn select_fallback_tags(build: &HeroBuild) -> Result<[u64; 3]> {
    let mut ids = vec![build.key_item_id];
    let mut others = build
        .core
        .iter()
        .filter(|item| item.item_id != build.key_item_id)
        .collect::<Vec<_>>();
    others.sort_by_key(|item| (std::cmp::Reverse(item.cost), item.item_id));
    ids.extend(others.iter().take(2).map(|item| item.item_id));
    ids.try_into()
        .map_err(|_| Error::new("Build needs three CORE items for its icons"))
}

fn read_hero_names(path: &Path) -> Result<BTreeMap<u64, String>> {
    let document = read_json(path)?;
    let rows = document
        .as_array()
        .ok_or_else(|| Error::new("Hero assets must be an array"))?;
    let mut heroes = BTreeMap::new();
    for row in rows {
        let flag = |name: &str| row[name].as_bool().unwrap_or(false);
        if flag("player_selectable") && !flag("disabled") && !flag("in_development") {
            heroes.insert(integer(row, "id")?, text(row, "name")?.to_owned());
        }
    }
    if heroes.is_empty() {
        return Err(Error::new("Hero assets contain no active heroes"));
    }
    Ok(heroes)
}
