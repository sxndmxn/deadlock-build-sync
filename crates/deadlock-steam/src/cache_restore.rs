use std::fs;
use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};
use deadlock_data::{Error, Result, sha256, validate_sha256};
use serde_json::json;

use crate::binary_reader::MAX_BINARY_BYTES;
use crate::cache_backup::{BackupManifest, backup_directory, create_backup, is_complete_backup};
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
    let manifest = BackupManifest::read(&source_directory)?;
    if !manifest.matches(location)? {
        return Err(Error::new("Backup identity differs from the destination"));
    }
    let source = read_cache(&source_directory.join(CACHE_FILENAME))?;
    validate_sha256(&manifest.cache_sha256, "Backup cache")?;
    if source.fingerprint() != manifest.cache_sha256 {
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

/// Returns the complete backup of this destination with the latest creation time.
fn latest_backup(location: &CacheLocation, state_directory: &Path) -> Result<PathBuf> {
    let parent = backup_directory(state_directory, location);
    if !parent.try_exists()? {
        return Err(Error::new("No Steam cache backup exists for this account"));
    }
    let mut latest: Option<(DateTime<Utc>, PathBuf)> = None;
    for entry in fs::read_dir(parent)? {
        let path = entry?.path();
        if !is_complete_backup(&path) {
            continue;
        }
        let manifest = BackupManifest::read(&path)?;
        if !manifest.matches(location)? {
            continue;
        }
        let created = DateTime::parse_from_rfc3339(&manifest.created_at)
            .map_err(|error| Error::new(format!("Backup creation time is invalid: {error}")))?
            .with_timezone(&Utc);
        if latest.as_ref().is_none_or(|(time, _)| created > *time) {
            latest = Some((created, path));
        }
    }
    latest
        .map(|(_, path)| path)
        .ok_or_else(|| Error::new("No complete Steam cache backup exists for this destination"))
}
