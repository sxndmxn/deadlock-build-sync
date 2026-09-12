use std::fs;
use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};
use deadlock_data::{Error, Result, sha256};
use serde_json::{Value, json};

use crate::binary::MAX_BINARY_BYTES;
use crate::cache_backup::create_backup;
use crate::cache_files::read_limited;
use crate::cache_location::{CACHE_FILENAME, CacheLocation};
use crate::cache_read::read_cache;
use crate::cache_transaction::{lock_cache, replace_cache};
use crate::process_check::ProcessInspection;

#[derive(Debug)]
pub struct RestoreResult {
    pub cache_path: PathBuf,
    pub source_directory: PathBuf,
    pub recovery_backup_directory: PathBuf,
}

/// Restores the latest complete backup and first backs up the current cache.
///
/// # Errors
/// Returns an error when no valid backup exists, ownership differs, or a guarded write fails.
pub fn restore_latest(
    location: &CacheLocation,
    state_directory: &Path,
    processes: &impl ProcessInspection,
) -> Result<RestoreResult> {
    processes.require_stopped()?;
    let _lock = lock_cache(location)?;
    let source_directory = latest_backup(location, state_directory)?;
    let manifest = read_manifest(&source_directory)?;
    validate_backup_identity(location, &manifest)?;
    let source = read_cache(&source_directory.join(CACHE_FILENAME))?;
    if let Some(expected) = manifest.get("cache_sha256").and_then(Value::as_str)
        && source.fingerprint() != expected
    {
        return Err(Error::new(
            "Backup cache fingerprint does not match its manifest",
        ));
    }
    let original = read_limited(&location.cache_path, MAX_BINARY_BYTES)?;
    let details = json!({ "operation": "restore", "source_directory": source_directory });
    let recovery_backup_directory = create_backup(location, &original, state_directory, &details)?;
    replace_cache(location, &sha256(&original), source.bytes(), processes).map_err(|error| {
        error.context(format!(
            "Restore failed. Recovery backup: {}",
            recovery_backup_directory.display()
        ))
    })?;
    Ok(RestoreResult {
        cache_path: location.cache_path.clone(),
        source_directory,
        recovery_backup_directory,
    })
}

fn latest_backup(location: &CacheLocation, state_directory: &Path) -> Result<PathBuf> {
    let parent = state_directory
        .join("backups")
        .join(location.account_id.to_string());
    if !parent.try_exists()? {
        return Err(Error::new("No Steam cache backup exists for this account"));
    }
    let mut latest: Option<(DateTime<Utc>, PathBuf)> = None;
    for entry in fs::read_dir(parent)? {
        let path = entry?.path();
        if !path.join(CACHE_FILENAME).is_file() || !path.join("manifest.json").is_file() {
            continue;
        }
        let manifest = read_manifest(&path)?;
        let created = manifest["created_at"]
            .as_str()
            .ok_or_else(|| Error::new("Backup manifest has no creation time"))?;
        let created = DateTime::parse_from_rfc3339(created)
            .map_err(|error| Error::new(format!("Backup creation time is invalid: {error}")))?
            .with_timezone(&Utc);
        if latest.as_ref().is_none_or(|(time, _)| created > *time) {
            latest = Some((created, path));
        }
    }
    latest
        .map(|(_, path)| path)
        .ok_or_else(|| Error::new("No complete Steam cache backup exists for this account"))
}

fn read_manifest(directory: &Path) -> Result<Value> {
    let bytes = read_limited(&directory.join("manifest.json"), 1024 * 1024)?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn validate_backup_identity(location: &CacheLocation, manifest: &Value) -> Result<()> {
    if manifest["account_id"].as_u64() != Some(u64::from(location.account_id)) {
        return Err(Error::new(
            "Backup account does not match the destination account",
        ));
    }
    let path = manifest["cache_path"]
        .as_str()
        .ok_or_else(|| Error::new("Backup manifest has no cache path"))?;
    if Path::new(path).canonicalize()? != location.cache_path.canonicalize()? {
        return Err(Error::new(
            "Backup cache path does not match the destination",
        ));
    }
    Ok(())
}
