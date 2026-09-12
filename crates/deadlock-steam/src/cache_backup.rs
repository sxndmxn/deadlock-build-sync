use std::fs::{self, File};
use std::io::{ErrorKind, Write};
use std::path::{Path, PathBuf};

use chrono::Utc;
use deadlock_data::{Error, Result, atomic_write_json, sha256};
use serde_json::Value;

use crate::binary::MAX_BINARY_BYTES;
use crate::cache_files::{read_limited, sync_directory};
use crate::cache_location::{CACHE_FILENAME, CacheLocation};

pub fn create_backup(
    location: &CacheLocation,
    original: &[u8],
    state_directory: &Path,
    details: &Value,
) -> Result<PathBuf> {
    let timestamp = Utc::now();
    let parent = state_directory
        .join("backups")
        .join(location.account_id.to_string());
    fs::create_dir_all(&parent)?;
    let directory = unique_directory(&parent, &timestamp.format("%Y%m%dT%H%M%SZ").to_string())?;
    write_backup_file(&directory.join(CACHE_FILENAME), original)?;
    let remote_path = location.remote_cache_path();
    let remote_hash = if remote_path.try_exists()? {
        let bytes = read_limited(&remote_path, MAX_BINARY_BYTES)?;
        write_backup_file(&directory.join("remotecache.vdf"), &bytes)?;
        Some(sha256(&bytes))
    } else {
        None
    };
    let mut manifest = details
        .as_object()
        .cloned()
        .ok_or_else(|| Error::new("Backup details must be a JSON object"))?;
    manifest.insert("account_id".into(), location.account_id.into());
    manifest.insert(
        "cache_path".into(),
        location.cache_path.to_string_lossy().into_owned().into(),
    );
    manifest.insert("created_at".into(), timestamp.to_rfc3339().into());
    manifest.insert("cache_sha256".into(), sha256(original).into());
    manifest.insert("remote_cache_sha256".into(), remote_hash.into());
    atomic_write_json(&directory.join("manifest.json"), &Value::Object(manifest))?;
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
