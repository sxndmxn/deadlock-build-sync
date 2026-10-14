use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use deadlock_analysis::{
    ExtractionResources, RefreshRequest, extract_run, parse_timestamp, produce_hero_builds,
};
use deadlock_data::{
    Error, RankRange, Result, atomic_write, fingerprint, state_directory, trace_operation,
};
use deadlock_guides::{HeroBuild, HeroBuildCatalog, build_hero_presentation};
use deadlock_input::{ApiOptions, DeadlockApi};
use deadlock_steam::{
    BuildIdentity, BuildSnapshot, CacheLocation, CacheUpdateRequest, InstallResult, LinuxProcesses,
    ManagedBuild, install_cache_update, local_steam_persona, prepare_cache_update, read_cache,
    steam_roots,
};
use serde_json::json;

use crate::artifact_transaction::ArtifactTransaction;
use crate::build_markdown::render_build_markdown;
use crate::cli_arguments::BuildArguments;
use crate::cli_output::print_json;
use crate::cli_paths::{artifact_directory, home_directory};

pub const CATALOG_FILE: &str = "hero-builds.json";

/// Extracts matches, produces a build for every hero, and replaces the artifact directory.
///
/// # Errors
/// Returns an error when extraction, production, validation, or the artifact write fails.
pub fn generate_builds(
    arguments: &BuildArguments,
    base_url: &str,
) -> Result<(PathBuf, HeroBuildCatalog)> {
    let directory = artifact_directory(arguments.artifacts.as_deref())?;
    ArtifactTransaction::recover(&directory)?;
    let parse = |value: Option<&String>| value.map(|text| parse_timestamp(text)).transpose();
    let resources = ExtractionResources {
        memory_limit_mb: arguments.extraction_memory_mb,
        threads: arguments.extraction_threads,
    };
    let run = trace_operation("analysis.extract_run", Some("extract_run"), || {
        extract_run(&RefreshRequest {
            root: state_directory()?.join("offline"),
            run_id: arguments.run_id.clone(),
            since: parse(arguments.since.as_ref())?,
            as_of: parse(arguments.as_of.as_ref())?,
            ranks: RankRange {
                minimum: arguments.min_rank,
                maximum: arguments.max_rank,
            }
            .validate()?,
            extraction_resources: resources,
            resume: arguments.resume,
            api_base_url: base_url.into(),
        })
    })?;
    let catalog = trace_operation("analysis.produce_builds", Some("produce_builds"), || {
        produce_hero_builds(&run.paths, resources, base_url)
    })?;
    write_build_artifacts(&directory, &catalog)?;
    eprintln!("Analysis run: {}", run.paths.run.display());
    Ok((directory, catalog))
}

/// Writes the catalog and all builds in each hero's Markdown file, then replaces the directory.
///
/// # Errors
/// Returns an error when validation or the guarded directory replacement fails.
pub fn write_build_artifacts(directory: &Path, catalog: &HeroBuildCatalog) -> Result<()> {
    let transaction = ArtifactTransaction::new(directory)?;
    let staged = transaction.staged();
    catalog.write(&staged.join(CATALOG_FILE))?;
    let builds = staged.join("builds");
    std::fs::create_dir(&builds)?;
    let mut documents = BTreeMap::<String, (u64, String)>::new();
    for build in &catalog.heroes {
        let (hero_id, text) = documents
            .entry(markdown_name(&build.hero_name))
            .or_insert_with(|| (build.hero_id, String::new()));
        if *hero_id != build.hero_id {
            return Err(Error::new(
                "Different heroes have the same Markdown file name",
            ));
        }
        if !text.is_empty() {
            text.push('\n');
        }
        text.push_str(&render_build_markdown(build, catalog)?);
    }
    for (name, (_, text)) in documents {
        atomic_write(&builds.join(format!("{name}.md")), text.as_bytes())?;
    }
    transaction.commit()
}

fn markdown_name(hero_name: &str) -> String {
    hero_name
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() {
                character.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect()
}

/// Returns why the catalog is stale, or `None` when it matches the current patch and client.
///
/// # Errors
/// Returns an error when the API is unavailable.
pub fn describe_staleness(catalog: &HeroBuildCatalog, base_url: &str) -> Result<Option<String>> {
    let mut api = DeadlockApi::new(ApiOptions {
        base_url: base_url.into(),
        ..ApiOptions::default()
    })?;
    let client = api.resolve_client_version()?;
    let patch = api.current_patch()?;
    Ok(if catalog.client_version != client {
        Some("Hero builds use another client version".into())
    } else if catalog.patch.get("identity") != Some(&patch.identity()?.into()) {
        Some("Hero builds use another patch".into())
    } else {
        None
    })
}

/// Returns the snapshot identity of a catalog: the fingerprint of its JSON document.
///
/// # Errors
/// Returns an error when serialization fails.
pub fn catalog_snapshot(catalog: &HeroBuildCatalog) -> Result<BuildSnapshot> {
    let document = serde_json::to_value(catalog)?;
    Ok(BuildSnapshot {
        snapshot_id: fingerprint(&document)?,
        document: json!({"method":catalog.method,"client_version":catalog.client_version,
            "patch":catalog.patch,"cohort":catalog.cohort}),
    })
}

/// Returns the Steam persona from the argument or from local Steam files.
///
/// # Errors
/// Returns an error when no persona is available.
pub fn resolve_persona(location: &CacheLocation, configured: Option<&str>) -> Result<String> {
    configured
        .map(str::to_owned)
        .or(local_steam_persona(
            location.account_id,
            &steam_roots(&home_directory()?)?,
        )?)
        .filter(|name| !name.trim().is_empty())
        .ok_or_else(|| Error::new("Cannot resolve the local Steam persona. Supply --persona NAME"))
}

/// Installs every managed build path. Builds for heroes in the catalog replace older managed builds.
///
/// # Errors
/// Returns an error when the catalog is malformed or stale, or the guarded installation fails.
pub fn install_catalog(
    location: &CacheLocation,
    catalog: &HeroBuildCatalog,
    persona: &str,
    base_url: &str,
) -> Result<InstallResult> {
    catalog.validate()?;
    if let Some(reason) = describe_staleness(catalog, base_url)? {
        return Err(Error::new(format!(
            "{reason}. Run deadlock-build-sync sync"
        )));
    }
    let snapshot = catalog_snapshot(catalog)?;
    let builds = catalog
        .heroes
        .iter()
        .map(|build| create_managed_build(build, catalog, &snapshot, persona))
        .collect::<Result<Vec<_>>>()?;
    let expected = catalog
        .heroes
        .iter()
        .map(|build| build.hero_id)
        .collect::<BTreeSet<_>>();
    let original = read_cache(&location.cache_path)?;
    let update = trace_operation("steam.prepare_update", Some("prepare_steam_update"), || {
        prepare_cache_update(
            &original,
            &CacheUpdateRequest {
                builds: &builds,
                account_id: location.account_id,
                timestamp: u64::try_from(chrono::Utc::now().timestamp())?,
                snapshot: &snapshot,
                expected_hero_ids: &expected,
                allow_subset: false,
            },
        )
    })?;
    trace_operation("steam.install_update", Some("install_steam_update"), || {
        install_cache_update(location, &update, &state_directory()?, &LinuxProcesses)
    })
}

fn create_managed_build(
    build: &HeroBuild,
    catalog: &HeroBuildCatalog,
    snapshot: &BuildSnapshot,
    persona: &str,
) -> Result<ManagedBuild> {
    ManagedBuild::new(
        build_hero_presentation(build, catalog, &snapshot.snapshot_id, persona)?,
        BuildIdentity {
            snapshot_id: snapshot.snapshot_id.clone(),
            build_fingerprint: fingerprint(&serde_json::to_value(build)?)?,
        },
    )
}

/// Prints the installation result with the information needed for recovery.
///
/// # Errors
/// Returns an error when output fails.
pub fn print_installation(
    result: &InstallResult,
    artifacts: &Path,
    catalog: &HeroBuildCatalog,
) -> Result<()> {
    print_json(&json!({
        "cache_path":result.cache_path,"backup_path":result.backup_directory,"artifacts":artifacts,
        "created":result.created,"updated":result.updated,"removed":result.removed,"changed":result.changed,
        "builds":catalog.heroes.iter().map(|build| json!({
            "hero":build.hero_name,"title":build.title,"confidence":build.evaluation.confidence,
        })).collect::<Vec<_>>(),
    }))
}
