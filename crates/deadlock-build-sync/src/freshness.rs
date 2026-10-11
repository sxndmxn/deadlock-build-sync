use std::collections::BTreeMap;
use std::path::Path;

use deadlock_data::Result;
use deadlock_guides::{HeroBuildCatalog, build_hero_presentation};
use deadlock_steam::{
    BuildKey, CacheLocation, ManagedBuildComparison, compare_managed_builds, read_cache,
};
use serde_json::{Value, json};

use crate::build_workflow::{CATALOG_FILE, catalog_snapshot, describe_staleness};

/// Reports whether the generated builds match the current game and whether Steam has them.
///
/// The exit code is 0 when both stages are current, 1 when a stage is malformed or
/// unavailable, and 2 when a stage needs a new sync.
///
/// # Errors
/// Returns an error when the API is unavailable.
pub fn build_freshness_report(
    directory: &Path,
    base_url: &str,
    location: Result<CacheLocation>,
) -> Result<(u8, Value)> {
    let path = directory.join(CATALOG_FILE);
    let (builds, catalog) = if path.is_file() {
        match HeroBuildCatalog::read(&path) {
            Ok(catalog) => match describe_staleness(&catalog, base_url)? {
                Some(reason) => (build_stage("hero_builds", "stale", &reason), Some(catalog)),
                None => (
                    build_stage(
                        "hero_builds",
                        "current",
                        &format!("Validated {} hero builds", catalog.heroes.len()),
                    ),
                    Some(catalog),
                ),
            },
            Err(error) => (
                build_stage("hero_builds", "malformed", &error.to_string()),
                None,
            ),
        }
    } else {
        (
            build_stage("hero_builds", "missing", &path.display().to_string()),
            None,
        )
    };
    let installed = match (location, &catalog) {
        (Err(error), _) => build_stage("installed_cache", "unavailable", &error.to_string()),
        (Ok(_), None) => build_stage("installed_cache", "missing", "No hero builds to compare"),
        (Ok(location), Some(catalog)) => check_installation(&location, catalog),
    };
    let stages = [builds, installed];
    let code = if stages.iter().all(|stage| stage["state"] == "current") {
        0
    } else if stages
        .iter()
        .any(|stage| matches!(stage["state"].as_str(), Some("malformed" | "unavailable")))
    {
        1
    } else {
        2
    };
    Ok((code, json!({"stages":stages})))
}

fn build_stage(name: &str, state: &str, detail: &str) -> Value {
    json!({"stage":name,"state":state,"detail":detail})
}

fn check_installation(location: &CacheLocation, catalog: &HeroBuildCatalog) -> Value {
    match compare_installation(location, catalog) {
        Ok(ManagedBuildComparison {
            is_current: true,
            retained_heroes,
        }) => {
            let detail = if retained_heroes == 0 {
                "Validated".into()
            } else {
                format!(
                    "Validated. {retained_heroes} other heroes keep managed builds from an earlier install"
                )
            };
            build_stage("installed_cache", "current", &detail)
        }
        Ok(_) => build_stage(
            "installed_cache",
            "stale",
            "Managed builds differ from the generated hero builds",
        ),
        Err(error) => build_stage("installed_cache", "malformed", &error.to_string()),
    }
}

fn compare_installation(
    location: &CacheLocation,
    catalog: &HeroBuildCatalog,
) -> Result<ManagedBuildComparison> {
    let snapshot = catalog_snapshot(catalog)?;
    let expected = catalog
        .heroes
        .iter()
        .map(|build| {
            Ok((
                BuildKey {
                    hero_id: build.hero_id,
                    path_id: build.path_id(),
                },
                build_hero_presentation(build, catalog, &snapshot.snapshot_id, "Build Preview")?,
            ))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    compare_managed_builds(
        &read_cache(&location.cache_path)?,
        location.account_id,
        &expected,
    )
}
