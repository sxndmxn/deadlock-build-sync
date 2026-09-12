use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};

use deadlock_data::{Error, Result, sha256};
use serde_json::json;

use crate::binary::MAX_BINARY_BYTES;
use crate::cache_backup::create_backup;
use crate::cache_files::{read_limited, sync_directory};
use crate::cache_location::CacheLocation;
use crate::cache_plan::CacheUpdate;
use crate::cache_read::read_cache;
use crate::cache_request::BuildKey;
use crate::process_check::ProcessInspection;

#[derive(Debug)]
pub struct InstallResult {
    pub cache_path: PathBuf,
    pub backup_directory: Option<PathBuf>,
    pub build_ids: BTreeMap<BuildKey, u64>,
    pub created: usize,
    pub updated: usize,
    pub removed: usize,
    pub changed: bool,
}

/// Installs a prepared replacement after process, backup, and preservation checks.
///
/// # Errors
/// Returns an error when the cache changed, Deadlock is running, or installation fails.
pub fn install_cache_update(
    location: &CacheLocation,
    update: &CacheUpdate,
    state_directory: &Path,
    processes: &impl ProcessInspection,
) -> Result<InstallResult> {
    processes.require_stopped()?;
    if update.account_id != location.account_id {
        return Err(Error::new(
            "Cache update account does not match the destination",
        ));
    }
    let _lock = lock_cache(location)?;
    require_unchanged(&location.cache_path, &update.original_fingerprint)?;
    let changed = update.original_bytes != update.replacement.bytes();
    let backup_directory = if changed {
        let backup = create_backup(
            location,
            &update.original_bytes,
            state_directory,
            &update.manifest,
        )?;
        let result = replace_cache(
            location,
            &update.original_fingerprint,
            update.replacement.bytes(),
            processes,
        );
        if let Err(error) = result {
            return Err(recover_installation(
                location,
                update,
                state_directory,
                processes,
                &error,
                &backup,
            ));
        }
        Some(backup)
    } else {
        None
    };
    Ok(InstallResult {
        cache_path: location.cache_path.clone(),
        backup_directory,
        build_ids: update.build_ids.clone(),
        created: update.created,
        updated: update.updated,
        removed: update.removed,
        changed,
    })
}

fn recover_installation(
    location: &CacheLocation,
    update: &CacheUpdate,
    state_directory: &Path,
    processes: &impl ProcessInspection,
    failure: &Error,
    backup: &Path,
) -> Error {
    let attempt = || -> Result<()> {
        let current = read_limited(&location.cache_path, MAX_BINARY_BYTES)?;
        if current == update.original_bytes {
            return Ok(());
        }
        if current != update.replacement.bytes() {
            return Err(Error::new(
                "Steam cache changed after the failed installation",
            ));
        }
        processes.require_stopped()?;
        create_backup(
            location,
            &current,
            state_directory,
            &json!({"operation": "automatic_recovery"}),
        )?;
        replace_cache(
            location,
            &sha256(&current),
            &update.original_bytes,
            processes,
        )
    };
    match attempt() {
        Ok(()) => Error::new(format!(
            "Cache installation failed. The original cache is intact. Cause: {failure}. Backup: {}",
            backup.display()
        )),
        Err(recovery) => Error::new(format!(
            "Cache installation failed: {failure}. Recovery failed: {recovery}. Backup: {}",
            backup.display()
        )),
    }
}

pub fn lock_cache(location: &CacheLocation) -> Result<File> {
    let parent = cache_parent(location)?;
    let file = File::options()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(parent.join(".deadlock-build-sync.lock"))?;
    file.try_lock()
        .map_err(|error| Error::new(format!("Cannot lock the Steam cache: {error}")))?;
    Ok(file)
}

pub fn require_unchanged(path: &Path, fingerprint: &str) -> Result<()> {
    if sha256(&read_limited(path, MAX_BINARY_BYTES)?) != fingerprint {
        return Err(Error::new(
            "Steam cache changed after preparation. The replacement was cancelled",
        ));
    }
    Ok(())
}

pub fn replace_cache(
    location: &CacheLocation,
    expected_fingerprint: &str,
    bytes: &[u8],
    processes: &impl ProcessInspection,
) -> Result<()> {
    let parent = cache_parent(location)?;
    let permissions = fs::metadata(&location.cache_path)?.permissions();
    let mut temporary = tempfile::Builder::new()
        .prefix(".cached_hero_builds.")
        .suffix(".tmp")
        .tempfile_in(parent)?;
    temporary.as_file().set_permissions(permissions)?;
    temporary.write_all(bytes)?;
    temporary.flush()?;
    temporary.as_file().sync_all()?;
    let candidate = read_cache(temporary.path())?;
    if candidate.bytes() != bytes {
        return Err(Error::new(
            "Temporary Steam cache differs from the prepared replacement",
        ));
    }
    processes.require_stopped()?;
    require_unchanged(&location.cache_path, expected_fingerprint)?;
    temporary
        .persist(&location.cache_path)
        .map_err(|error| Error::from(error.error))?;
    sync_directory(parent)?;
    let installed = read_cache(&location.cache_path)?;
    if installed.bytes() != bytes {
        return Err(Error::new(
            "Installed Steam cache differs from the validated replacement",
        ));
    }
    Ok(())
}

fn cache_parent(location: &CacheLocation) -> Result<&Path> {
    location
        .cache_path
        .parent()
        .ok_or_else(|| Error::new("Steam cache path has no parent directory"))
}
