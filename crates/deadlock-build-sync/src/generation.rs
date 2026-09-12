use std::collections::{BTreeMap, BTreeSet};

use chrono::Utc;
use deadlock_data::{
    ArtifactCoverage, EvidenceSemantics, EvidenceUnit, Result, object, trace_operation,
};
use deadlock_guides::{
    BEAM_METHOD_VERSION, BuildEvidenceCatalog, BuildEvidenceIdentity, BuildGenerator,
    CURRENT_METHOD_VERSION, NarrativeCatalog, build_item_mechanics_catalog,
};
use deadlock_input::{BuildTagCatalog, DeadlockApi, ItemGraph};
use serde_json::{Value, json};

use crate::generation_inputs::{collect_cohort_analytics, collect_hero_inputs};
use crate::generation_projection::project_hero;
use crate::generation_types::{GeneratedGuides, select_heroes};

#[derive(Clone, Debug, Default)]
pub struct GenerationRequest {
    pub account_id: u32,
    pub hero_query: Option<String>,
    pub all_heroes: bool,
}

/// # Errors
/// Returns an error when current inputs differ from admitted evidence or any requested hero has incomplete generation data.
pub fn generate_guides(
    api: &mut DeadlockApi,
    evidence: &BuildEvidenceCatalog,
    request: &GenerationRequest,
    narratives: Option<&NarrativeCatalog>,
) -> Result<GeneratedGuides> {
    let GenerationAssets {
        rank_catalog,
        heroes,
        assets,
        tags,
        patch,
        start,
    } = collect_generation_assets(api, evidence)?;
    let selected = select_heroes(&heroes, request.hero_query.as_deref(), request.all_heroes)?;
    let options = api.options().clone();
    let evidence = evidence.select_hero_subset(
        &selected
            .iter()
            .map(|hero| deadlock_data::integer(hero, "id"))
            .collect::<Result<BTreeSet<_>>>()?,
    )?;
    record_build_evidence(api, &evidence)?;
    let analytics = trace_operation(
        "guides.collect_cohort_analytics",
        Some("collect_cohort_analytics"),
        || collect_cohort_analytics(api, start),
    )?;
    let persona = if request.account_id == 0 {
        "Build Preview".into()
    } else {
        api.steam_persona(request.account_id)?
    };
    let prepared = trace_operation(
        "guides.collect_hero_inputs",
        Some("collect_hero_inputs"),
        || collect_hero_inputs(api, &selected, &evidence, &assets, start, &analytics),
    )?;
    let manifest = api.snapshot_manifest(&patch, &rank_catalog, tags.sha256())?;
    let projected = trace_operation("guides.project_roster", Some("project_roster"), || {
        deadlock_data::map_jobs(&prepared, 8, |inputs| {
            let (mut guide, policy, context) = project_hero(inputs, &assets, &manifest, &tags)?;
            if let Some(narratives) = narratives {
                narratives.apply(&mut guide, &context, &patch)?;
            }
            Ok((guide, policy, context))
        })
    })?;
    let mut guides = Vec::with_capacity(projected.len());
    let mut policies = Vec::with_capacity(projected.len());
    let mut contexts = Vec::with_capacity(projected.len());
    for (guide, policy, context) in projected {
        guides.push(guide);
        policies.push(policy);
        contexts.push(context);
    }
    let item_ids = contexts
        .iter()
        .flat_map(|context| {
            context["item_mechanics_ids"]
                .as_array()
                .into_iter()
                .flatten()
        })
        .filter_map(Value::as_u64)
        .collect();
    let eligible_hero_ids = heroes
        .iter()
        .filter_map(|hero| hero["id"].as_u64())
        .collect::<BTreeSet<_>>();
    let requested = if request.all_heroes {
        eligible_hero_ids.clone()
    } else {
        guides.iter().map(|guide| guide.hero_id).collect()
    };
    let result = GeneratedGuides {
        guides,
        policies,
        contexts,
        item_mechanics: build_item_mechanics_catalog(&assets, &item_ids)?,
        coverage: ArtifactCoverage::new(requested, BTreeMap::new())?,
        eligible_hero_ids,
        subset_selected: !request.all_heroes,
        rank_range: options.rank_range,
        rank_catalog,
        persona,
        patch,
        manifest,
        guide_groups: evidence
            .heroes()
            .values()
            .flat_map(|hero| &hero.builds)
            .map(|build| {
                (
                    (build.hero_id, build.path_id.clone()),
                    build.guide_group_id.clone(),
                )
            })
            .collect(),
        evidence,
    };
    result.require_complete()?;
    Ok(result)
}

#[derive(Debug)]
struct GenerationAssets {
    rank_catalog: deadlock_data::RankCatalog,
    heroes: Vec<Value>,
    assets: Vec<Value>,
    tags: BuildTagCatalog,
    patch: deadlock_input::Patch,
    start: i64,
}

fn collect_generation_assets(
    api: &mut DeadlockApi,
    evidence: &BuildEvidenceCatalog,
) -> Result<GenerationAssets> {
    let client_version = api.resolve_client_version()?;
    let rank_catalog = api.rank_catalog()?;
    let heroes = api.active_heroes()?;
    let assets = api.items()?;
    let tags = BuildTagCatalog::from_assets(&api.build_tags()?)?;
    ItemGraph::from_assets(&assets)?;
    let patch = api.current_patch()?;
    let epochs = api.epochs_for_patch(&patch)?;
    let options = api.options().clone();
    evidence.assert_compatible(&BuildEvidenceIdentity {
        patch_identity: &patch.identity()?,
        client_version,
        as_of_timestamp: options.as_of_timestamp,
        match_mode: options.match_mode,
        rank_range: options.rank_range,
        rank_catalog: &rank_catalog,
        heroes: &heroes,
        assets: &assets,
        epochs: &epochs,
    })?;
    Ok(GenerationAssets {
        rank_catalog,
        heroes,
        assets,
        tags,
        patch,
        start: epochs.analysis_start_timestamp(),
    })
}

fn record_build_evidence(api: &mut DeadlockApi, evidence: &BuildEvidenceCatalog) -> Result<()> {
    api.recorder_mut().declare(
        "artifact:build-evidence",
        EvidenceSemantics {
            unit: EvidenceUnit::EligibleAppearance,
            backend_grain: "reconstructed-final-inventory-and-first-ownership".into(),
            fallback_behavior: "reject; no aggregate-API approximation".into(),
            warnings: Vec::new(),
        },
    )?;
    let method = match evidence.metadata().generator {
        BuildGenerator::Current => CURRENT_METHOD_VERSION,
        BuildGenerator::Beam => BEAM_METHOD_VERSION,
    };
    api.recorder_mut().record(
        "artifact:build-evidence",
        object(&json!({"artifact_id":evidence.metadata().artifact_id,
        "method":method,"hero_count":evidence.heroes().len()}))?
        .clone(),
        evidence.raw_bytes(),
        Utc::now(),
    )
}
