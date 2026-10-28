use std::collections::BTreeMap;
use std::path::Path;

use deadlock_data::{Error, Result, integer, read_json, text};
use deadlock_guides::{
    BuildCohort, HERO_BUILD_METHOD, HERO_BUILD_SCHEMA_VERSION, HeroBuild, HeroBuildCatalog,
    TagItem, assign_build_focus, select_ability_path, select_build_tags,
};
use deadlock_input::{ApiOptions, BuildTagCatalog, DeadlockApi, parse_patch_feed};
use duckdb::types::Value as SqlValue;
use serde::Deserialize;
use serde_json::Value;

use crate::build_assembly::{PHASES, PurchaseMedian, PurchaseMedians, assemble_build};
use crate::build_evaluation::evaluate_build;
use crate::database::{AnalysisDatabase, Parameters};
use crate::item_effects::{ItemCatalog, LandmarkState, estimate_item_effects};
use crate::item_imbues::{attach_item_imbues, load_item_imbues};
use crate::refresh_configuration::{ExtractionResources, RunPaths, cohort_ranks, parse_timestamp};
use crate::sql_resources::sql;

const EFFECT_LANDMARKS: [u32; 8] = [360, 540, 720, 900, 1200, 1500, 1800, 2100];
const ABILITY_MINIMUM_MATCHES: u32 = 10;

#[derive(Debug, Deserialize)]
struct PurchaseMedianRow {
    hero_id: u64,
    item_id: u64,
    median_buy_time_s: f64,
    median_net_worth: u32,
    lower_quartile_net_worth: u32,
    upper_quartile_net_worth: u32,
}

/// Produces one build for each active hero from an extracted run.
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
) -> Result<HeroBuildCatalog> {
    let manifest = read_json(&paths.run.join("manifest.json"))?;
    let cohort = &manifest["cohort"];
    let ranks = cohort_ranks(cohort)?;
    let as_of = parse_timestamp(text(cohort, "as_of")?)?;
    let patch = parse_patch_feed(&read_json(&paths.raw.join("patches.json"))?, Some(as_of))?;
    let client_version = integer(&manifest["sources"], "client_version")?;
    let heroes = read_hero_names(&paths.raw.join("heroes.json"))?;
    let database = AnalysisDatabase::open_read_only(
        &paths.raw.join("analysis.duckdb"),
        &paths.raw.join("duckdb-read-tmp"),
        resources,
    )?;
    let parameters = Parameters::from([
        (
            "minimum_badge".into(),
            SqlValue::UInt(u32::from(ranks.minimum.badge())),
        ),
        (
            "maximum_badge".into(),
            SqlValue::UInt(u32::from(ranks.maximum.badge())),
        ),
    ]);
    eprintln!("Loading landmark states");
    let states: Vec<LandmarkState> =
        database.query_rows(sql!("builds/select_landmark_states"), &parameters)?;
    let catalog = ItemCatalog::new(
        database.query_rows(sql!("builds/select_item_assets"), &Parameters::new())?,
    )?;
    let medians = database
        .query_rows::<PurchaseMedianRow>(sql!("builds/select_item_purchase_medians"), &parameters)?
        .into_iter()
        .map(|row| {
            (
                (row.hero_id, row.item_id),
                PurchaseMedian {
                    buy_time_s: row.median_buy_time_s,
                    net_worth: row.median_net_worth,
                    soul_window: [row.lower_quartile_net_worth, row.upper_quartile_net_worth],
                },
            )
        })
        .collect::<PurchaseMedians>();
    let imbues = load_item_imbues(&database, &parameters)?;
    drop(database);
    let builds = assemble_hero_builds(&states, &catalog, &medians, &heroes)?;
    let mut api = build_api(api_base_url, ranks, client_version, as_of)?;
    let assets = read_json(&paths.raw.join("items-all.json"))?;
    let assets = assets
        .as_array()
        .ok_or_else(|| Error::new("Item assets must be an array"))?;
    let tags = BuildTagCatalog::from_assets(&api.build_tags()?)?;
    let builds = builds
        .into_iter()
        .map(|build| {
            let mut build =
                attach_ability_and_tags(build, &mut api, patch.start_timestamp, assets, &tags)?;
            attach_item_imbues(&mut build, &imbues, assets);
            assign_build_focus(&mut build, assets)?;
            Ok(build)
        })
        .collect::<Result<Vec<_>>>()?;
    let catalog = HeroBuildCatalog {
        schema_version: HERO_BUILD_SCHEMA_VERSION,
        method: HERO_BUILD_METHOD.into(),
        client_version,
        patch: patch.to_document()?,
        cohort: BuildCohort {
            minimum_badge: ranks.minimum.badge(),
            maximum_badge: ranks.maximum.badge(),
            since: text(cohort, "since")?.into(),
            as_of: text(cohort, "as_of")?.into(),
            player_matches: integer(&manifest["extraction"], "player_matches")?,
        },
        heroes: builds,
    };
    catalog.validate()?;
    Ok(catalog)
}

fn assemble_hero_builds(
    states: &[LandmarkState],
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
    heroes: &BTreeMap<u64, String>,
) -> Result<Vec<HeroBuild>> {
    let (test, development): (Vec<_>, Vec<_>) =
        states.iter().partition(|state| state.fold == "test");
    eprintln!("Estimating item effects for the held-out test");
    let development_effects = estimate_item_effects(&development, catalog, &EFFECT_LANDMARKS)?;
    eprintln!("Estimating item effects from all matches");
    let all = states.iter().collect::<Vec<_>>();
    let effects = estimate_item_effects(&all, catalog, &EFFECT_LANDMARKS)?;
    let mut builds = Vec::new();
    for (hero_id, hero_name) in heroes {
        let Some(build) = assemble_build(*hero_id, &effects, catalog, medians) else {
            eprintln!("Warning: Skipping {hero_name}: no item has enough owners");
            continue;
        };
        let hero_test = test
            .iter()
            .copied()
            .filter(|state| state.hero_id == *hero_id)
            .collect::<Vec<_>>();
        let evaluation = match assemble_build(*hero_id, &development_effects, catalog, medians) {
            Some(development_build) => {
                evaluate_build(&hero_test, &development_build.phase_sets, catalog)?
            }
            None => evaluate_build(&[], &build.phase_sets, catalog)?,
        };
        let observations = PHASES
            .iter()
            .filter_map(|phase| effects.get(&(*hero_id, *phase)))
            .map(|phase| phase.observations)
            .max()
            .unwrap_or(0);
        builds.push(HeroBuild {
            hero_id: *hero_id,
            hero_name: hero_name.clone(),
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
        });
    }
    Ok(builds)
}

fn build_api(
    api_base_url: &str,
    ranks: deadlock_data::RankRange,
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
    api: &mut DeadlockApi,
    since: i64,
    assets: &[Value],
    tags: &BuildTagCatalog,
) -> Result<HeroBuild> {
    eprintln!("Selecting ability order and icons for {}", build.hero_name);
    let rows = api.ability_order_stats(build.hero_id, since, ABILITY_MINIMUM_MATCHES, &[])?;
    if let Some(path) = select_ability_path(&rows, &[])? {
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
            build.key_ability_name = Some(selection.labels[0].clone());
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
