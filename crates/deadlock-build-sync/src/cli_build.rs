use deadlock_data::{Result, atomic_write_json};
use deadlock_guides::{BuildEvidenceCatalog, group_guides};
use deadlock_steam::require_deadlock_stopped;

use crate::artifact_generation::{policy_artifact, strategy_context, write_build_artifacts};
use crate::cli_arguments::{
    BuildArguments, ExportArguments, InstallArguments, PreviewArguments, SyncArguments,
};
use crate::cli_generation::{
    generate_requested, load_narratives, require_current_evidence, require_generator,
    require_selection,
};
use crate::cli_installation::{InstallationParameters, install_guides, print_installation};
use crate::cli_output::print_guides;
use crate::cli_paths::{absolute_path, artifact_directory, cache_location, evidence_path};

pub fn run_build(args: &BuildArguments, base_url: &str) -> Result<u8> {
    let directory = artifact_directory(args.artifacts.as_deref())?;
    let path = evidence_path(
        args.generation.snapshot.build_evidence.as_deref(),
        Some(&directory),
    )?;
    let evidence = require_current_evidence(&path, base_url)?;
    require_generator(&evidence, args.generator)?;
    let generated = generate_requested(base_url, &args.generation, &evidence, &path, 0, None)?;
    let guides = write_build_artifacts(&directory, &generated)?;
    print_guides(&guides, &generated, args.format, args.details, 0)?;
    eprintln!("Build index: {}", directory.join("builds.json").display());
    Ok(0)
}

pub fn run_sync(args: &SyncArguments, base_url: &str) -> Result<u8> {
    let location = cache_location(&args.location)?;
    require_deadlock_stopped()?;
    let directory = artifact_directory(args.artifacts.as_deref())?;
    let path = evidence_path(
        args.generation.snapshot.build_evidence.as_deref(),
        Some(&directory),
    )?;
    let evidence = require_current_evidence(&path, base_url)?;
    require_generator(&evidence, args.generator)?;
    let generated = generate_requested(
        base_url,
        &args.generation,
        &evidence,
        &path,
        location.account_id,
        None,
    )?;
    let guides = write_build_artifacts(&directory, &generated)?;
    let result = install_guides(
        &location,
        &guides,
        &InstallationParameters {
            persona: &generated.persona,
            patch: &generated.patch,
            ranks: generated.rank_range,
            manifest: &generated.manifest,
            expected_heroes: &generated.eligible_hero_ids,
            allow_subset: generated.subset_selected,
        },
    )?;
    print_installation(
        &result,
        Some(&directory),
        &generated.manifest,
        &generated.coverage,
    )?;
    Ok(0)
}

pub fn run_preview(args: &PreviewArguments, base_url: &str) -> Result<u8> {
    let install = &args.install;
    require_selection(&install.generation)?;
    let location = cache_location(&install.location)?;
    let path = evidence_path(install.generation.snapshot.build_evidence.as_deref(), None)?;
    let evidence = BuildEvidenceCatalog::read(&path)?;
    let narratives = load_narratives(&install.narrative)?;
    let generated = generate_requested(
        base_url,
        &install.generation,
        &evidence,
        &path,
        location.account_id,
        narratives.as_ref(),
    )?;
    let guides = group_guides(generated.guides.clone(), &generated.guide_groups)?;
    print_guides(
        &guides,
        &generated,
        args.format,
        args.details,
        location.account_id,
    )?;
    Ok(0)
}

pub fn run_install(args: &InstallArguments, base_url: &str) -> Result<u8> {
    require_selection(&args.generation)?;
    let location = cache_location(&args.location)?;
    require_deadlock_stopped()?;
    let path = evidence_path(args.generation.snapshot.build_evidence.as_deref(), None)?;
    let evidence = BuildEvidenceCatalog::read(&path)?;
    let narratives = load_narratives(&args.narrative)?;
    let generated = generate_requested(
        base_url,
        &args.generation,
        &evidence,
        &path,
        location.account_id,
        narratives.as_ref(),
    )?;
    generated.require_complete()?;
    let guides = group_guides(generated.guides.clone(), &generated.guide_groups)?;
    let result = install_guides(
        &location,
        &guides,
        &InstallationParameters {
            persona: &generated.persona,
            patch: &generated.patch,
            ranks: generated.rank_range,
            manifest: &generated.manifest,
            expected_heroes: &generated.eligible_hero_ids,
            allow_subset: generated.subset_selected,
        },
    )?;
    print_installation(&result, None, &generated.manifest, &generated.coverage)?;
    Ok(0)
}

pub fn run_export(args: &ExportArguments, base_url: &str) -> Result<u8> {
    require_selection(&args.generation)?;
    let location = cache_location(&args.location)?;
    let path = evidence_path(args.generation.snapshot.build_evidence.as_deref(), None)?;
    let evidence = BuildEvidenceCatalog::read(&path)?;
    let generated = generate_requested(
        base_url,
        &args.generation,
        &evidence,
        &path,
        location.account_id,
        None,
    )?;
    let context = strategy_context(&generated)?;
    let policies = policy_artifact(&generated)?;
    let output = absolute_path(&args.output)?;
    let policy_output = args
        .policy_output
        .as_deref()
        .map(absolute_path)
        .transpose()?
        .unwrap_or_else(|| output.with_file_name("policies.json"));
    atomic_write_json(&output, context.document())?;
    atomic_write_json(&policy_output, &policies.to_document()?)?;
    eprintln!(
        "Context: {}\nPolicies: {}",
        output.display(),
        policy_output.display()
    );
    Ok(0)
}
