use std::path::Path;

use deadlock_analysis::{ExtractionResources, RefreshRequest};
use deadlock_data::{Error, RankRange, Result, parse_timestamp, state_directory};
use deadlock_guides::{BuildRules, HeroBuildCatalog};
use deadlock_steam::{InstallResult, LinuxProcesses, require_deadlock_stopped, restore_latest};
use serde_json::json;

use crate::artifact_transaction::{ArtifactTransaction, CATALOG_FILE};
use crate::build_workflow::{
    BuildRequest, GeneratedBuilds, generate_builds, install_catalog, resolve_persona,
};
use crate::cli_arguments::{
    BuildArguments, InstallArguments, RestoreArguments, StatusArguments, SyncArguments,
};
use crate::cli_output::{print_json, print_text};
use crate::cli_paths::{artifact_directory, cache_location};
use crate::freshness::build_freshness_report;

pub fn run_sync(arguments: &SyncArguments, base_url: &str) -> Result<u8> {
    let location = cache_location(&arguments.location)?;
    require_deadlock_stopped()?;
    let persona = resolve_persona(&location, arguments.persona.as_deref())?;
    let request = build_request(&arguments.build, base_url)?;
    let generated = generate_builds(&request)?;
    report_generation(&generated);
    require_deadlock_stopped()?;
    let result = install_catalog(&location, &generated.catalog, &persona, base_url)?;
    print_installation(&result, &request.artifacts, &generated.catalog)
}

pub fn run_build(arguments: &BuildArguments, base_url: &str) -> Result<u8> {
    let request = build_request(arguments, base_url)?;
    let generated = generate_builds(&request)?;
    report_generation(&generated);
    print_json(&json!({
        "artifacts":request.artifacts,
        "builds":generated.catalog.heroes.iter().map(|build| json!({
            "hero":build.hero_name,"title":build.title,"confidence":build.evaluation.confidence,
            "core":build.core.iter().map(|item| &item.name).collect::<Vec<_>>(),
        })).collect::<Vec<_>>(),
    }))?;
    Ok(0)
}

/// Converts the command line arguments to a build request.
fn build_request(arguments: &BuildArguments, base_url: &str) -> Result<BuildRequest> {
    let parse = |value: Option<&String>| value.map(|text| parse_timestamp(text)).transpose();
    let rules = BuildRules {
        variant_distinct_items: arguments.variant_distinct_items,
        variant_separation: arguments.variant_separation,
    };
    rules.validate()?;
    Ok(BuildRequest {
        refresh: RefreshRequest {
            root: state_directory()?.join("offline"),
            run_id: arguments.run_id.clone(),
            since: parse(arguments.since.as_ref())?,
            as_of: parse(arguments.as_of.as_ref())?,
            ranks: RankRange {
                minimum: arguments.min_rank,
                maximum: arguments.max_rank,
            }
            .validate()?,
            extraction_resources: ExtractionResources {
                memory_limit_mb: arguments.extraction_memory_mb,
                threads: arguments.extraction_threads,
            },
            resume: arguments.resume,
            api_base_url: base_url.into(),
        },
        rules,
        artifacts: artifact_directory(arguments.artifacts.as_deref())?,
    })
}

fn report_generation(generated: &GeneratedBuilds) {
    eprintln!("Analysis run: {}", generated.run.display());
    if generated.removed_runs > 0 {
        eprintln!(
            "Removed {} other automatic analysis runs",
            generated.removed_runs
        );
    }
}

pub fn run_install(arguments: &InstallArguments, base_url: &str) -> Result<u8> {
    let location = cache_location(&arguments.location)?;
    require_deadlock_stopped()?;
    let directory = artifact_directory(arguments.artifacts.as_deref())?;
    ArtifactTransaction::recover(&directory)?;
    let catalog = HeroBuildCatalog::read(&directory.join(CATALOG_FILE))?;
    let persona = resolve_persona(&location, arguments.persona.as_deref())?;
    let result = install_catalog(&location, &catalog, &persona, base_url)?;
    print_installation(&result, &directory, &catalog)
}

/// Prints the installation result with the information needed for recovery.
fn print_installation(
    result: &InstallResult,
    artifacts: &Path,
    catalog: &HeroBuildCatalog,
) -> Result<u8> {
    print_json(&json!({
        "cache_path":result.cache_path,"backup_path":result.backup_directory,"artifacts":artifacts,
        "created":result.created,"updated":result.updated,"removed":result.removed,"changed":result.changed,
        "builds":catalog.heroes.iter().map(|build| json!({
            "hero":build.hero_name,"title":build.title,"confidence":build.evaluation.confidence,
        })).collect::<Vec<_>>(),
    }))?;
    Ok(0)
}

pub fn run_status(arguments: &StatusArguments, base_url: &str) -> Result<u8> {
    let directory = artifact_directory(arguments.artifacts.as_deref())?;
    let (code, report) =
        build_freshness_report(&directory, base_url, cache_location(&arguments.location))?;
    if arguments.json {
        print_json(&report)?;
    } else if let Some(stages) = report["stages"].as_array() {
        for stage in stages {
            print_text(&format!(
                "{}: {} — {}",
                stage["stage"].as_str().unwrap_or_default(),
                stage["state"].as_str().unwrap_or_default(),
                stage["detail"].as_str().unwrap_or_default()
            ))?;
        }
        if code == 2 {
            print_text("Run deadlock-build-sync sync to update the builds.")?;
        }
    }
    Ok(code)
}

pub fn run_restore(arguments: &RestoreArguments) -> Result<u8> {
    if !arguments.latest {
        return Err(Error::new(
            "Supply --latest to select the latest complete backup",
        ));
    }
    let location = cache_location(&arguments.location)?;
    let result = restore_latest(&location, &state_directory()?, &LinuxProcesses)?;
    print_json(
        &json!({"cache_path":result.cache_path,"source_backup":result.source_directory,"recovery_backup":result.recovery_backup_directory}),
    )?;
    Ok(0)
}
