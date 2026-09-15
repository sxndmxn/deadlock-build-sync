use std::path::Path;

use deadlock_data::{
    Error, RankCatalog, Result, array, atomic_write_json, fingerprint, integer, object, read_json,
    text, trace_operation,
};
use deadlock_guides::{
    BUILD_EVIDENCE_SCHEMA_VERSION, BuildEvidenceCatalog, expected_selection_method,
    select_hero_build,
};
use deadlock_input::parse_patch_feed;
use serde_json::{Value, json};

use crate::ability_prefetch::AbilityPrefetch;
use crate::discovery_models::ExportContext;
use crate::discovery_roster::discover_roster;
use crate::refresh_configuration::{RunPaths, parse_timestamp};

pub fn export_evidence(
    paths: &RunPaths,
    output: &Path,
    workers: u16,
    resume: bool,
    base_url: &str,
) -> Result<Value> {
    let manifest = read_json(&paths.run.join("manifest.json"))?;
    object(&manifest["sources"])?;
    let cutoff = parse_timestamp(text(&manifest["cohort"], "as_of")?)?;
    let heroes = read_json(&paths.raw.join("heroes.json"))?;
    if array(&heroes)?.is_empty() {
        return Err(Error::new("Hero source contains no active heroes"));
    }
    let context = ExportContext::load(paths, &manifest)?;
    let patch = parse_patch_feed(&read_json(&paths.raw.join("patches.json"))?, Some(cutoff))?;
    let ranks = read_json(&paths.raw.join("ranks.json"))?;
    let prefetch = AbilityPrefetch::new(output, &manifest, &patch, base_url)?;
    let roster = discover_roster(array(&heroes)?, &context, workers, resume, &prefetch)?;
    if roster
        .iter()
        .any(|hero| hero["builds"].as_array().is_none_or(Vec::is_empty))
    {
        let report = paths.run.join("discovery-exclusions.json");
        atomic_write_json(&report, &roster.into())?;
        return Err(Error::new(format!(
            "Requested heroes lack supported builds. Existing artifacts are unchanged. Report: {}",
            report.display()
        )));
    }
    let patch_identity = patch.identity()?;
    let epochs = ["mechanics", "matchmaking", "map_objectives", "telemetry"]
        .into_iter()
        .map(|name| {
            (
                name,
                json!({"identity":patch_identity,"start_timestamp":patch.start_timestamp}),
            )
        })
        .collect::<std::collections::BTreeMap<_, _>>();
    let mut payload = json!({"schema_version":BUILD_EVIDENCE_SCHEMA_VERSION,"producer":"deadlock-build-sync.offline","method":production_method(),"cohort":manifest["cohort"],
        "patch":patch.to_document()?,"epochs":epochs,"client_version":integer(&manifest["sources"],"client_version")?,"rank_labels_sha256":RankCatalog::from_assets(array(&ranks)?)?.fingerprint(),
        "heroes_sha256":fingerprint(&heroes)?,"items_sha256":fingerprint(&serde_json::to_value(&context.normal_assets)?)?,"mechanics_assets":context.normal_assets,
        "source_sha256":manifest["sources"]["source_sha256"],"frozen_data_sha256":manifest.get("frozen_data_sha256").cloned().unwrap_or_else(||json!({})),"extraction":manifest["extraction"],
        "requested_hero_ids":array(&heroes)?.iter().map(|hero|integer(hero,"id")).collect::<Result<Vec<_>>>()?,"heroes":roster});
    payload["artifact_id"] = fingerprint(&payload)?.into();
    trace_operation(
        "analysis.validate_evidence",
        Some("validate_evidence"),
        || write_validated_evidence(output, &payload),
    )?;
    Ok(payload)
}

fn production_method() -> Value {
    let mut method = expected_selection_method();
    method["core_selection"] = "Eclat exact cores use Leiden groups, frozen selection ranking, corrected outcomes, and supported pairwise order".into();
    method["tier_membership"] =
        "Discovery buyers of the exact core; minimum 20 buyers, maximum 10 items per tier".into();
    method["tier_display_order"] =
        "Discovery median first-purchase time, then item identifier".into();
    method["core_economy_reference"] =
        json!({"target_core_cost":19200,"basis":"frozen discovery maximum"});
    method["outcome_usage"]="Freeze candidates, ranking, orders, and pools before corrected validation. Do not use reserved test data.".into();
    method["independent_evaluation"] =
        "Later replay states after the frozen artifact cutoff".into();
    method["rejected_branch_diagnostics"] =
        "Stop at the first failed balance check. Do not calculate later outcome diagnostics."
            .into();
    method
}

fn write_validated_evidence(output: &Path, document: &Value) -> Result<()> {
    let catalog = BuildEvidenceCatalog::from_bytes(serde_json::to_vec_pretty(document)?)?;
    for hero in catalog.heroes().values() {
        for build in &hero.builds {
            select_hero_build(build, catalog.assets())?;
        }
    }
    atomic_write_json(output, document)
}
