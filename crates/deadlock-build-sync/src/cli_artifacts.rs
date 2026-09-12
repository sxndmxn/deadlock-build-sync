use deadlock_data::{Error, Result, atomic_write_json, state_directory};
use deadlock_guides::{
    NarrativeCatalog, StrategyContext, generate_narrative_document, load_artifact_guide_bundle,
};
use deadlock_steam::{
    LinuxProcesses, local_steam_persona, require_deadlock_stopped, restore_latest, steam_roots,
};
use serde_json::json;

use crate::cli_arguments::{InstallArtifactArguments, NarrativeArguments, RestoreArguments};
use crate::cli_installation::{InstallationParameters, install_guides, print_installation};
use crate::cli_output::print_json;
use crate::cli_paths::{absolute_path, artifact_directory, cache_location, home_directory};

pub fn run_install_artifacts(args: &InstallArtifactArguments) -> Result<u8> {
    let location = cache_location(&args.location)?;
    require_deadlock_stopped()?;
    let directory = artifact_directory(args.artifacts.as_deref())?;
    let bundle = load_artifact_guide_bundle(
        &directory.join("strategy-context.json"),
        &directory.join("policies.json"),
        &directory.join("narratives.json"),
        &directory.join("build-evidence.json"),
    )?;
    let persona = args
        .persona
        .clone()
        .or(local_steam_persona(
            location.account_id,
            &steam_roots(&home_directory()?)?,
        )?)
        .filter(|name| !name.trim().is_empty())
        .ok_or_else(|| {
            Error::new("Cannot resolve the local Steam persona. Supply --persona NAME")
        })?;
    let expected = bundle
        .coverage
        .requested()
        .difference(&bundle.coverage.exclusions().keys().copied().collect())
        .copied()
        .collect();
    let result = install_guides(
        &location,
        &bundle.guides,
        &InstallationParameters {
            persona: &persona,
            patch: &bundle.patch,
            ranks: bundle.rank_range,
            manifest: &bundle.manifest,
            expected_heroes: &expected,
            allow_subset: false,
        },
    )?;
    print_installation(
        &result,
        Some(&directory),
        &bundle.manifest,
        &bundle.coverage,
    )?;
    Ok(0)
}

pub fn run_narratives(args: &NarrativeArguments) -> Result<u8> {
    let context = StrategyContext::load(&absolute_path(&args.context)?)?;
    let output = absolute_path(&args.output)?;
    let existing = if output.try_exists()? && !args.force {
        Some(NarrativeCatalog::load(&output)?)
    } else {
        None
    };
    let generated = generate_narrative_document(
        &context,
        &args.hero,
        existing.as_ref(),
        args.force,
        &chrono::Utc::now().to_rfc3339(),
    )?;
    atomic_write_json(&output, generated.catalog.document())?;
    print_json(&json!({"path":output,"written":generated.written,"reused":generated.reused}))?;
    Ok(0)
}

pub fn run_restore(args: &RestoreArguments) -> Result<u8> {
    if !args.latest {
        return Err(Error::new(
            "Supply --latest to select the latest complete backup",
        ));
    }
    let location = cache_location(&args.location)?;
    let result = restore_latest(&location, &state_directory()?, &LinuxProcesses)?;
    print_json(
        &json!({"cache_path":result.cache_path,"source_backup":result.source_directory,"recovery_backup":result.recovery_backup_directory}),
    )?;
    Ok(0)
}
