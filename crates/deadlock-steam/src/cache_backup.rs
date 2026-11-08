//! Backups of the Steam cache: one directory for each write, under the state directory.

use std::fs::{self, File};
use std::io::{ErrorKind, Write};
use std::path::{Path, PathBuf};

use chrono::Utc;
use deadlock_data::{Error, Result, atomic_write_json, read_json, sha256};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::binary_reader::MAX_BINARY_BYTES;
use crate::cache_files::{read_limited, sync_directory};
use crate::cache_location::{CACHE_FILENAME, CacheLocation, REMOTE_CACHE_FILENAME};

const MANIFEST_FILENAME: &str = "manifest.json";

/// Returns the directory that holds the backups of one account's cache.
#[must_use]
pub fn backup_directory(state_directory: &Path, location: &CacheLocation) -> PathBuf {
    state_directory
        .join("backups")
        .join(location.account_id.to_string())
}

/// `manifest.json` of one backup: the source of the bytes and the operation that made it.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BackupManifest {
    pub account_id: u32,
    pub cache_path: String,
    pub created_at: String,
    pub cache_sha256: String,
    /// The fingerprint of `remotecache.vdf`, when Steam Cloud had one.
    pub remote_cache_sha256: Option<String>,
    /// The operation details: the installed builds, or the restore source.
    #[serde(flatten)]
    pub details: Map<String, Value>,
}

impl BackupManifest {
    /// # Errors
    /// Returns an error when the manifest is missing or malformed.
    pub fn read(directory: &Path) -> Result<Self> {
        serde_json::from_value(read_json(&directory.join(MANIFEST_FILENAME))?)
            .map_err(|error| Error::new(format!("Malformed backup manifest: {error}")))
    }

    /// Returns true when the backup came from this account and cache path.
    ///
    /// # Errors
    /// Returns an error when a path cannot be resolved.
    pub fn matches(&self, location: &CacheLocation) -> Result<bool> {
        if self.account_id != location.account_id {
            return Ok(false);
        }
        match Path::new(&self.cache_path).canonicalize() {
            Ok(path) => Ok(path == location.cache_path.canonicalize()?),
            Err(error) if error.kind() == ErrorKind::NotFound => Ok(false),
            Err(error) => Err(error.into()),
        }
    }
}

/// Returns true when the directory holds a cache file and a manifest.
#[must_use]
pub fn is_complete_backup(directory: &Path) -> bool {
    directory.join(CACHE_FILENAME).is_file() && directory.join(MANIFEST_FILENAME).is_file()
}

pub fn create_backup(
    location: &CacheLocation,
    original: &[u8],
    state_directory: &Path,
    details: &Value,
) -> Result<PathBuf> {
    let timestamp = Utc::now();
    let parent = backup_directory(state_directory, location);
    fs::create_dir_all(&parent)?;
    let directory = unique_directory(&parent, &timestamp.format("%Y%m%dT%H%M%SZ").to_string())?;
    write_backup_file(&directory.join(CACHE_FILENAME), original)?;
    // Steam Cloud keeps the cache fingerprint in remotecache.vdf. The copy records that state.
    let remote_path = location.remote_cache_path();
    let remote_cache_sha256 = if remote_path.try_exists()? {
        let bytes = read_limited(&remote_path, MAX_BINARY_BYTES)?;
        write_backup_file(&directory.join(REMOTE_CACHE_FILENAME), &bytes)?;
        Some(sha256(&bytes))
    } else {
        None
    };
    let manifest = BackupManifest {
        account_id: location.account_id,
        cache_path: location.cache_path.to_string_lossy().into_owned(),
        created_at: timestamp.to_rfc3339(),
        cache_sha256: sha256(original),
        remote_cache_sha256,
        details: details
            .as_object()
            .cloned()
            .ok_or_else(|| Error::new("Backup details must be a JSON object"))?,
    };
    atomic_write_json(
        &directory.join(MANIFEST_FILENAME),
        &serde_json::to_value(manifest)?,
    )?;
    sync_directory(&directory)?;
    sync_directory(&parent)?;
    Ok(directory)
}

fn unique_directory(parent: &Path, timestamp: &str) -> Result<PathBuf> {
    for suffix in 0..10_000 {
        let name = if suffix == 0 {
            timestamp.to_owned()
        } else {
            format!("{timestamp}-{suffix}")
        };
        let candidate = parent.join(name);
        match fs::create_dir(&candidate) {
            Ok(()) => return Ok(candidate),
            Err(error) if error.kind() == ErrorKind::AlreadyExists => (),
            Err(error) => return Err(error.into()),
        }
    }
    Err(Error::new("Cannot allocate a unique backup directory"))
}

fn write_backup_file(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = File::options().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    if read_limited(path, MAX_BINARY_BYTES)? != bytes {
        return Err(Error::new("Backup bytes do not match the source"));
    }
    Ok(())
}
