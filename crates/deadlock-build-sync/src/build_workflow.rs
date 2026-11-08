use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use deadlock_analysis::{RefreshRequest, extract_run, produce_hero_builds};
use deadlock_data::{Error, Result, atomic_write, fingerprint, state_directory, trace_operation};
use deadlock_guides::{BuildRules, HeroBuild, HeroBuildCatalog, build_hero_presentation};
use deadlock_input::{ApiOptions, DeadlockApi};
use deadlock_steam::{
    BuildIdentity, BuildSnapshot, CacheLocation, CacheUpdateRequest, InstallResult, LinuxProcesses,
    ManagedBuild, install_cache_update, local_steam_persona, prepare_cache_update, read_cache,
    steam_roots,
};
use serde_json::json;

use crate::artifact_transaction::ArtifactTransaction;
use crate::build_markdown::render_build_markdown;
use crate::cli_paths::home_directory;

pub const CATALOG_FILE: &str = "hero-builds.json";

/// One request to generate builds: the match extraction, the selection rules, and the output.
#[derive(Clone, Debug)]
pub struct BuildRequest {
    pub refresh: RefreshRequest,
    pub rules: BuildRules,
    /// The artifact directory that receives `hero-builds.json` and the Markdown builds.
    pub artifacts: PathBuf,
}

/// The result of a build request.
#[derive(Debug)]
pub struct GeneratedBuilds {
    pub catalog: HeroBuildCatalog,
    /// The analysis run directory.
    pub run: PathBuf,
    /// The number of other automatic runs that the request removed.
    pub removed_runs: usize,
}

/// Extracts matches, produces a build for every hero, and replaces the artifact directory.
///
/// # Errors
/// Returns an error when extraction, production, validation, or the artifact write fails.
pub fn generate_builds(request: &BuildRequest) -> Result<GeneratedBuilds> {
    ArtifactTransaction::recover(&request.artifacts)?;
    let run = trace_operation("analysis.extract_run", Some("extract_run"), || {
        extract_run(&request.refresh)
    })?;
    let catalog = trace_operation("analysis.produce_builds", Some("produce_builds"), || {
        produce_hero_builds(
            &run.paths,
            request.refresh.extraction_resources,
            &request.refresh.api_base_url,
            &request.rules,
        )
    })?;
    write_build_artifacts(&request.artifacts, &catalog)?;
    let removed_runs = run.remove_other_automatic_runs();
    Ok(GeneratedBuilds {
        catalog,
        run: run.paths.run,
        removed_runs,
    })
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
    } else if catalog.patch.identity != patch.identity {
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
