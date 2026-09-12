use std::fs::{self, File};
use std::io::{Read as _, Write as _};
use std::path::{Path, PathBuf};

use serde_json::Value;

use crate::{Error, Result, canonical_json, object, sha256, validate_sha256};

const MAXIMUM_JSON_BYTES: u64 = 512 * 1024 * 1024;

/// # Errors
/// Returns an error if the home directory is unavailable or a state path is relative.
pub fn state_directory() -> Result<PathBuf> {
    if let Some(directory) = std::env::var_os("XDG_STATE_HOME").filter(|value| !value.is_empty()) {
        let directory = PathBuf::from(directory);
        if !directory.is_absolute() {
            return Err(Error::new("XDG_STATE_HOME must be an absolute path"));
        }
        return Ok(directory.join("deadlock-build-sync"));
    }
    std::env::var_os("HOME")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .map(|home| home.join(".local/state/deadlock-build-sync"))
        .ok_or_else(|| Error::new("Cannot determine the user state directory"))
}

/// # Errors
/// Returns an error if the file cannot be read or contains invalid JSON.
pub fn read_json(path: &Path) -> Result<Value> {
    read_json_bytes(path).map(|(_, value)| value)
}

/// # Errors
/// Returns an error when the file bytes differ from the expected fingerprint or the JSON root is not an object.
pub fn read_fingerprinted_json(path: &Path, expected_sha256: &str) -> Result<Value> {
    validate_sha256(expected_sha256, "Artifact")?;
    let (bytes, value) = read_json_bytes(path)?;
    if sha256(&bytes) != expected_sha256 {
        return Err(Error::new(format!(
            "Artifact byte fingerprint differs: {}",
            path.display()
        )));
    }
    object(&value)?;
    Ok(value)
}

/// # Errors
/// Returns an error if the file exceeds the size limit, cannot be read, or contains invalid JSON.
pub fn read_json_bytes(path: &Path) -> Result<(Vec<u8>, Value)> {
    let mut bytes = Vec::new();
    File::open(path)?
        .take(MAXIMUM_JSON_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if u64::try_from(bytes.len())? > MAXIMUM_JSON_BYTES {
        return Err(Error::new(format!(
            "JSON file exceeds the size limit: {}",
            path.display()
        )));
    }
    let value = serde_json::from_slice(&bytes)
        .map_err(|error| Error::from(error).context(path.display()))?;
    Ok((bytes, value))
}

/// # Errors
/// Returns an error if serialization or atomic file replacement fails.
pub fn atomic_write_json(path: &Path, value: &Value) -> Result<()> {
    let mut bytes = canonical_json(value)?;
    bytes.push(b'\n');
    atomic_write(path, &bytes)
}

/// # Errors
/// Returns an error if writing, validation, synchronization, or replacement fails.
pub fn atomic_write(path: &Path, bytes: &[u8]) -> Result<()> {
    let parent = path
        .parent()
        .filter(|path| !path.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;
    let mut temporary = tempfile::Builder::new()
        .prefix(".deadlock-artifact.")
        .tempfile_in(parent)?;
    temporary.write_all(bytes)?;
    temporary.flush()?;
    temporary.as_file().sync_all()?;
    if fs::read(temporary.path())? != bytes {
        return Err(Error::new("Temporary artifact differs from its source"));
    }
    temporary
        .persist(path)
        .map_err(|error| Error::from(error.error))?;
    File::open(parent)?.sync_all()?;
    Ok(())
}
