use std::cell::Cell;
use std::collections::BTreeSet;
use std::fs;

use base64::Engine as _;
use deadlock_data::{Error, Result, atomic_write_json};
use deadlock_steam::{
    CacheLocation, CacheUpdateRequest, ProcessInspection, SteamCache, decode_kv3, encode_kv3,
    install_cache_update, prepare_cache_update, read_cache, restore_latest,
};
use serde_json::{Value, json};

use super::reference_data::{create_cache, create_managed_build, create_snapshot};

#[derive(Debug, Default)]
struct ReferenceProcesses {
    inspections: Cell<usize>,
    reject_at: Option<usize>,
}

impl ProcessInspection for ReferenceProcesses {
    fn require_stopped(&self) -> Result<()> {
        let inspection = self.inspections.get() + 1;
        self.inspections.set(inspection);
        if self.reject_at == Some(inspection) {
            return Err(Error::new(
                "Reference process inspection rejected the write",
            ));
        }
        Ok(())
    }
}

pub fn check_steam_safety() -> Result<()> {
    check_reference_fixture()?;
    check_installation()?;
    check_write_guards()?;
    for fingerprint in [
        None,
        Some(Value::Null),
        Some(json!(7)),
        Some(json!("invalid")),
        Some(json!("0".repeat(64))),
    ] {
        check_invalid_backup(fingerprint)?;
    }
    check_valid_restore()
}

fn check_reference_fixture() -> Result<()> {
    let encoded = include_str!("../../../../tests/fixtures/keyvalues3-v5.kv3.b64");
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(encoded.split_ascii_whitespace().collect::<String>())
        .map_err(|error| Error::new(format!("Reference fixture is invalid: {error}")))?;
    let document = decode_kv3(&bytes)?;
    if decode_kv3(&encode_kv3(&document)?)? != document {
        return Err(Error::new("KV3 reference serialization changed values"));
    }
    Ok(())
}

fn create_location(root: &std::path::Path) -> Result<CacheLocation> {
    let snapshot = create_snapshot()?;
    let cache_path = root.join("cache.kv3");
    fs::write(&cache_path, encode_kv3(&create_cache(&snapshot)?)?)?;
    Ok(CacheLocation {
        account_id: 7,
        cache_path,
        app_directory: root.join("app"),
    })
}

fn check_installation() -> Result<()> {
    let root = tempfile::tempdir()?;
    let location = create_location(root.path())?;
    let original = read_cache(&location.cache_path)?;
    let snapshot = create_snapshot()?;
    let builds = [create_managed_build(&snapshot)?];
    let expected = BTreeSet::from([1]);
    let request = CacheUpdateRequest {
        builds: &builds,
        account_id: 7,
        timestamp: 1,
        snapshot: &snapshot,
        expected_hero_ids: &expected,
        allow_subset: false,
    };
    let update = prepare_cache_update(&original, &request)?;
    let state = root.path().join("state");
    let result = install_cache_update(&location, &update, &state, &ReferenceProcesses::default())?;
    let backup = result
        .backup_directory
        .ok_or_else(|| Error::new("Installation did not create a backup"))?;
    if !result.changed
        || result.created != 1
        || read_cache(&backup.join("cached_hero_builds.kv3"))?.bytes() != original.bytes()
    {
        return Err(Error::new(
            "Installation backup does not preserve the original cache",
        ));
    }
    let installed = read_cache(&location.cache_path)?;
    check_preserved_values(&original, &installed)?;
    let repeated = prepare_cache_update(&installed, &request)?;
    let result =
        install_cache_update(&location, &repeated, &state, &ReferenceProcesses::default())?;
    if result.changed
        || result.backup_directory.is_some()
        || read_cache(&location.cache_path)?.bytes() != installed.bytes()
    {
        return Err(Error::new("Repeated installation changed the Steam cache"));
    }
    Ok(())
}

fn check_preserved_values(original: &SteamCache, installed: &SteamCache) -> Result<()> {
    for section in ["Favorites", "LastUsedBuilds", "SavedLastUsed"] {
        if original.document().root.field(section)? != installed.document().root.field(section)? {
            return Err(Error::new(format!(
                "Installation changed section {section}"
            )));
        }
    }
    let previous = original.document().root.field("Unpublished")?.array()?;
    let current = installed.document().root.field("Unpublished")?.array()?;
    if !current.starts_with(previous) {
        return Err(Error::new("Installation changed unrelated private builds"));
    }
    Ok(())
}

fn check_write_guards() -> Result<()> {
    for reject_at in [1, 2] {
        let root = tempfile::tempdir()?;
        let location = create_location(root.path())?;
        let original = read_cache(&location.cache_path)?;
        let snapshot = create_snapshot()?;
        let builds = [create_managed_build(&snapshot)?];
        let expected = BTreeSet::from([1]);
        let update = prepare_cache_update(
            &original,
            &CacheUpdateRequest {
                builds: &builds,
                account_id: 7,
                timestamp: 1,
                snapshot: &snapshot,
                expected_hero_ids: &expected,
                allow_subset: false,
            },
        )?;
        let processes = ReferenceProcesses {
            reject_at: Some(reject_at),
            ..ReferenceProcesses::default()
        };
        if install_cache_update(&location, &update, &root.path().join("state"), &processes).is_ok()
            || read_cache(&location.cache_path)?.bytes() != original.bytes()
        {
            return Err(Error::new(
                "Process rejection failed to preserve the original cache",
            ));
        }
        let concurrent = encode_kv3(&deadlock_steam::Kv3Document::generic(
            deadlock_steam::Kv3Value::new(deadlock_steam::Kv3Kind::Object(vec![(
                "reference".into(),
                deadlock_steam::Kv3Value::new(deadlock_steam::Kv3Kind::Unsigned(2)),
            )])),
        ))?;
        fs::write(&location.cache_path, &concurrent)?;
        if install_cache_update(
            &location,
            &update,
            &root.path().join("state"),
            &ReferenceProcesses::default(),
        )
        .is_ok()
            || fs::read(&location.cache_path)? != concurrent
        {
            return Err(Error::new(
                "Installation replaced a concurrent cache change",
            ));
        }
    }
    Ok(())
}

fn check_invalid_backup(fingerprint: Option<Value>) -> Result<()> {
    let root = tempfile::tempdir()?;
    let location = create_location(root.path())?;
    let original = fs::read(&location.cache_path)?;
    let state = root.path().join("state");
    let backup = state.join("backups/7/reference");
    fs::create_dir_all(&backup)?;
    fs::write(backup.join("cached_hero_builds.kv3"), &original)?;
    let mut manifest = json!({"account_id":7,"cache_path":location.cache_path,"created_at":"2026-01-01T00:00:00Z"});
    if let Some(fingerprint) = fingerprint {
        manifest["cache_sha256"] = fingerprint;
    }
    atomic_write_json(&backup.join("manifest.json"), &manifest)?;
    if restore_latest(&location, &state, &ReferenceProcesses::default()).is_ok()
        || fs::read(&location.cache_path)? != original
        || fs::read_dir(state.join("backups/7"))?.count() != 1
    {
        return Err(Error::new("Restore accepted an invalid backup fingerprint"));
    }
    Ok(())
}

fn check_valid_restore() -> Result<()> {
    let root = tempfile::tempdir()?;
    let location = create_location(root.path())?;
    let original = fs::read(&location.cache_path)?;
    let snapshot = create_snapshot()?;
    let builds = [create_managed_build(&snapshot)?];
    let expected = BTreeSet::from([1]);
    let update = prepare_cache_update(
        &read_cache(&location.cache_path)?,
        &CacheUpdateRequest {
            builds: &builds,
            account_id: 7,
            timestamp: 1,
            snapshot: &snapshot,
            expected_hero_ids: &expected,
            allow_subset: false,
        },
    )?;
    let state = root.path().join("state");
    install_cache_update(&location, &update, &state, &ReferenceProcesses::default())?;
    let installed = fs::read(&location.cache_path)?;
    let restored = restore_latest(&location, &state, &ReferenceProcesses::default())?;
    if fs::read(&location.cache_path)? != original
        || fs::read(
            restored
                .recovery_backup_directory
                .join("cached_hero_builds.kv3"),
        )? != installed
    {
        return Err(Error::new(
            "Restore did not preserve the replaced cache in its recovery backup",
        ));
    }
    Ok(())
}
