use std::path::Path;

use deadlock_data::{Error, Result, sha256};

use crate::binary::MAX_BINARY_BYTES;
use crate::cache_files::read_limited;
use crate::kv3_read::decode_kv3;
use crate::kv3_value::Kv3Document;

#[derive(Debug)]
pub struct SteamCache {
    document: Kv3Document,
    bytes: Vec<u8>,
}

impl SteamCache {
    /// # Errors
    /// Returns an error when the bytes contain an invalid Steam cache.
    pub fn from_bytes(bytes: Vec<u8>) -> Result<Self> {
        let document = decode_kv3(&bytes)?;
        validate_sections(&document)?;
        Ok(Self { document, bytes })
    }

    #[must_use]
    pub const fn document(&self) -> &Kv3Document {
        &self.document
    }

    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    #[must_use]
    pub fn fingerprint(&self) -> String {
        sha256(&self.bytes)
    }
}

/// # Errors
/// Returns an error when the file cannot be read or contains an invalid Steam cache.
pub fn read_cache(path: &Path) -> Result<SteamCache> {
    if !path.is_file() {
        return Err(Error::new(format!(
            "Steam cache is not a regular file: {}",
            path.display()
        )));
    }
    SteamCache::from_bytes(read_limited(path, MAX_BINARY_BYTES)?)
        .map_err(|error| error.context(format!("Cannot read Steam cache {}", path.display())))
}

pub fn validate_sections(document: &Kv3Document) -> Result<()> {
    for name in [
        "LastUsedBuilds",
        "Favorites",
        "Unpublished",
        "SavedLastUsed",
    ] {
        document.root.field(name)?;
    }
    document.root.field("Unpublished")?.array()?;
    Ok(())
}
