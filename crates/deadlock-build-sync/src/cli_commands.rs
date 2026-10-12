use deadlock_data::{Error, Result, state_directory};
use deadlock_guides::HeroBuildCatalog;
use deadlock_steam::{LinuxProcesses, require_deadlock_stopped, restore_latest};
use serde_json::json;

use crate::artifact_transaction::ArtifactTransaction;
use crate::build_workflow::{
    CATALOG_FILE, generate_builds, install_catalog, print_installation, resolve_persona,
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
    let (directory, catalog) = generate_builds(&arguments.build, base_url)?;
    require_deadlock_stopped()?;
    let result = install_catalog(&location, &catalog, &persona, base_url)?;
    print_installation(&result, &directory, &catalog)?;
    Ok(0)
}

pub fn run_build(arguments: &BuildArguments, base_url: &str) -> Result<u8> {
    let (directory, catalog) = generate_builds(arguments, base_url)?;
    print_json(&json!({
        "artifacts":directory,
        "builds":catalog.heroes.iter().map(|build| json!({
            "hero":build.hero_name,"title":build.title,"confidence":build.evaluation.confidence,
            "core":build.core.iter().map(|item| &item.name).collect::<Vec<_>>(),
        })).collect::<Vec<_>>(),
    }))?;
    Ok(0)
}

pub fn run_install(arguments: &InstallArguments, base_url: &str) -> Result<u8> {
    let location = cache_location(&arguments.location)?;
    require_deadlock_stopped()?;
    let directory = artifact_directory(arguments.artifacts.as_deref())?;
    ArtifactTransaction::recover(&directory)?;
    let catalog = HeroBuildCatalog::read(&directory.join(CATALOG_FILE))?;
    let persona = resolve_persona(&location, arguments.persona.as_deref())?;
    let result = install_catalog(&location, &catalog, &persona, base_url)?;
    print_installation(&result, &directory, &catalog)?;
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
