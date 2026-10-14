use std::collections::{BTreeMap, BTreeSet};
use std::fs;

use deadlock_build_sync::{CATALOG_FILE, write_build_artifacts};
use deadlock_data::{Error, Result, fingerprint};
use deadlock_guides::{
    HERO_BUILD_METHOD, HERO_BUILD_SCHEMA_VERSION, HeroBuildCatalog, ItemStatistics,
    build_hero_presentation,
};
use deadlock_steam::{
    BuildIdentity, BuildKey, CacheLocation, CacheUpdate, CacheUpdateRequest, ManagedBuild,
    ProcessInspection, SteamCache, compare_managed_builds, encode_kv3, install_cache_update,
    prepare_cache_update, read_cache,
};

use super::reference_data::{create_cache, create_snapshot};

struct StoppedProcesses;

impl ProcessInspection for StoppedProcesses {
    fn require_stopped(&self) -> Result<()> {
        Ok(())
    }
}

pub fn check_build_variants() -> Result<()> {
    let catalog = create_variant_catalog()?;
    check_duplicate_paths(&catalog)?;
    check_variant_exports(&catalog)?;
    check_variant_installation(&catalog)
}

fn create_variant_catalog() -> Result<HeroBuildCatalog> {
    let reference = include_str!("../../../../tests/fixtures/imbue-catalog.json");
    let mut catalog: HeroBuildCatalog = serde_json::from_str(reference)?;
    catalog.validate()?;
    if catalog.heroes[0].path_id() != "1-main"
        || serde_json::to_value(&catalog)? != serde_json::from_str::<serde_json::Value>(reference)?
    {
        return Err(Error::new(
            "Schema 5 compatibility changed the build identity or fingerprint",
        ));
    }
    catalog.schema_version = HERO_BUILD_SCHEMA_VERSION;
    catalog.method = HERO_BUILD_METHOD.into();
    for build in &mut catalog.heroes {
        for item in build.core.iter_mut().chain(&mut build.situational) {
            item.statistics = Some(ItemStatistics {
                hero_matches: 100,
                buyer_matches: 40,
                buyer_wins: 21,
            });
        }
    }
    let mut second = catalog.heroes[0].clone();
    second.variant_id = Some("ability-102".into());
    second.title = "Second ability build".into();
    std::mem::swap(&mut second.core[0], &mut second.situational[0]);
    second.key_item_id = second.core[0].item_id;
    second.tag_ids[1] = second.key_item_id;
    let mut third = catalog.heroes[0].clone();
    third.variant_id = Some("early-item-16".into());
    third.title = "Early item build".into();
    third.core.reverse();
    catalog.heroes.extend([second, third]);
    catalog.validate()?;
    Ok(catalog)
}

fn check_duplicate_paths(catalog: &HeroBuildCatalog) -> Result<()> {
    for variant in [None, Some("main"), Some("ability-102")] {
        let mut invalid = catalog.clone();
        invalid.heroes[2].variant_id = variant.map(str::to_owned);
        if invalid.validate().is_ok() {
            return Err(Error::new(
                "Catalog accepted a duplicate hero and build path pair",
            ));
        }
    }
    for variant in [
        "",
        "../outside",
        "MixedCase",
        "two words",
        "line\nbreak",
        &"a".repeat(81),
    ] {
        let mut invalid = catalog.clone();
        invalid.heroes[1].variant_id = Some(variant.into());
        if invalid.validate().is_ok() {
            return Err(Error::new("Catalog accepted an invalid variant identity"));
        }
    }
    let mut old_schema = catalog.clone();
    old_schema.schema_version = 5;
    if old_schema.validate().is_ok() {
        return Err(Error::new("Schema 5 accepted variant identifiers"));
    }
    let mut other_hero = catalog.clone();
    let mut build = catalog.heroes[1].clone();
    build.hero_id = 2;
    build.hero_name = "Second hero".into();
    other_hero.heroes.push(build);
    other_hero.validate()
}

fn check_variant_exports(catalog: &HeroBuildCatalog) -> Result<()> {
    let root = tempfile::tempdir()?;
    let directory = root.path().join("artifacts");
    write_build_artifacts(&directory, catalog)?;
    if HeroBuildCatalog::read(&directory.join(CATALOG_FILE))? != *catalog {
        return Err(Error::new("Catalog serialization changed build variants"));
    }
    let markdown = fs::read_to_string(directory.join("builds/reference-hero.md"))?;
    if !markdown.contains("52.5% (21/40) | 40.0% (40/100)") {
        return Err(Error::new(
            "Markdown export omitted item purchase rates or counts",
        ));
    }
    let titles = markdown
        .lines()
        .filter_map(|line| line.strip_prefix("# "))
        .collect::<Vec<_>>();
    if titles
        != catalog
            .heroes
            .iter()
            .map(|build| build.title.as_str())
            .collect::<Vec<_>>()
    {
        return Err(Error::new("Markdown export lost a build variant"));
    }
    Ok(())
}

fn prepare_variants(original: &SteamCache, catalog: &HeroBuildCatalog) -> Result<CacheUpdate> {
    catalog.validate()?;
    let snapshot = create_snapshot();
    let builds = catalog
        .heroes
        .iter()
        .map(|build| {
            ManagedBuild::new(
                build_hero_presentation(build, catalog, &snapshot.snapshot_id, "Reference")?,
                BuildIdentity {
                    snapshot_id: snapshot.snapshot_id.clone(),
                    build_fingerprint: fingerprint(&serde_json::to_value(build)?)?,
                },
            )
        })
        .collect::<Result<Vec<_>>>()?;
    prepare_cache_update(
        original,
        &CacheUpdateRequest {
            builds: &builds,
            account_id: 7,
            timestamp: 1,
            snapshot: &snapshot,
            expected_hero_ids: &BTreeSet::from([1]),
            allow_subset: false,
        },
    )
}

fn check_variant_installation(catalog: &HeroBuildCatalog) -> Result<()> {
    let root = tempfile::tempdir()?;
    let location = CacheLocation {
        account_id: 7,
        cache_path: root.path().join("cache.kv3"),
        app_directory: root.path().join("app"),
    };
    fs::write(
        &location.cache_path,
        encode_kv3(&create_cache(&create_snapshot())?)?,
    )?;
    let original = read_cache(&location.cache_path)?;
    let update = prepare_variants(&original, catalog)?;
    if update.created() != 3 || update.build_ids().values().collect::<BTreeSet<_>>().len() != 3 {
        return Err(Error::new(
            "Steam did not allocate three distinct build IDs for one hero",
        ));
    }
    let state = root.path().join("state");
    let result = install_cache_update(&location, &update, &state, &StoppedProcesses)?;
    let backup = result
        .backup_directory
        .ok_or_else(|| Error::new("Variant installation has no backup"))?;
    if fs::read(backup.join("cached_hero_builds.kv3"))? != original.bytes() {
        return Err(Error::new(
            "Variant installation backup changed the original cache",
        ));
    }
    let installed = read_cache(&location.cache_path)?;
    check_variant_comparison(&installed, catalog)?;
    let repeated = prepare_variants(&installed, catalog)?;
    let result = install_cache_update(&location, &repeated, &state, &StoppedProcesses)?;
    if result.changed
        || result.backup_directory.is_some()
        || read_cache(&location.cache_path)?.bytes() != installed.bytes()
    {
        return Err(Error::new(
            "Repeated variant installation changed the cache",
        ));
    }
    check_variant_updates(&installed, catalog, update.build_ids())
}

fn check_variant_comparison(installed: &SteamCache, catalog: &HeroBuildCatalog) -> Result<()> {
    let snapshot = create_snapshot();
    let mut expected = catalog
        .heroes
        .iter()
        .map(|build| {
            Ok((
                BuildKey {
                    hero_id: build.hero_id,
                    path_id: build.path_id(),
                },
                build_hero_presentation(build, catalog, &snapshot.snapshot_id, "Reference")?,
            ))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    if !compare_managed_builds(installed, 7, &expected)?.is_current {
        return Err(Error::new(
            "Installed variants do not match the complete catalog",
        ));
    }
    if expected
        .remove(&BuildKey {
            hero_id: 1,
            path_id: "1-ability-102".into(),
        })
        .is_some()
        && compare_managed_builds(installed, 7, &expected)?.is_current
    {
        return Err(Error::new(
            "Steam comparison ignored an extra build variant",
        ));
    }
    Ok(())
}

fn check_variant_updates(
    installed: &SteamCache,
    catalog: &HeroBuildCatalog,
    identifiers: &BTreeMap<BuildKey, u64>,
) -> Result<()> {
    let mut renamed = catalog.clone();
    renamed.heroes.reverse();
    renamed.heroes[0].title = "Changed title".into();
    let update = prepare_variants(installed, &renamed)?;
    if update.build_ids() != identifiers || update.created() != 0 || update.updated() != 1 {
        return Err(Error::new(
            "Title or catalog order changed a variant build ID",
        ));
    }
    let mut remaining = catalog.clone();
    remaining.heroes.remove(1);
    let update = prepare_variants(installed, &remaining)?;
    if update.removed() != 1
        || update.created() != 0
        || update.updated() != 0
        || update
            .build_ids()
            .iter()
            .any(|(key, id)| identifiers.get(key) != Some(id))
    {
        return Err(Error::new("Removing one variant changed another variant"));
    }
    check_variant_comparison(update.replacement(), &remaining)
}
