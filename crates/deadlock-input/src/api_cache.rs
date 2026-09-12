use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};
use deadlock_data::{Error, Result, atomic_write_json, read_json, sha256};
use serde::{Deserialize, Serialize};
use serde_json::Value;

const MAXIMUM_CACHE_AGE_SECONDS: i64 = 3600;

#[derive(Clone, Debug)]
pub struct ApiResponseCache {
    directory: PathBuf,
    reuse: bool,
}

#[derive(Debug)]
pub struct CachedResponse {
    pub content: Vec<u8>,
    pub data: Value,
    pub fetched_at: DateTime<Utc>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CacheEntry {
    schema_version: u32,
    request_sha256: String,
    response_sha256: String,
    fetched_at: String,
    content: String,
}

impl ApiResponseCache {
    #[must_use]
    pub fn reuse_for_evidence(evidence: &Path) -> Self {
        Self {
            directory: evidence.with_extension("api-cache"),
            reuse: true,
        }
    }

    #[must_use]
    pub fn refresh_for_evidence(evidence: &Path) -> Self {
        Self {
            directory: evidence.with_extension("api-cache"),
            reuse: false,
        }
    }

    pub(super) fn read(&self, request_sha256: &str) -> Result<Option<CachedResponse>> {
        let path = self.directory.join(format!("{request_sha256}.json"));
        if !self.reuse || !path.try_exists()? {
            return Ok(None);
        }
        let entry: CacheEntry = serde_json::from_value(read_json(&path)?)?;
        if entry.schema_version != 1
            || entry.request_sha256 != request_sha256
            || entry.response_sha256 != sha256(entry.content.as_bytes())
        {
            return Err(Error::new("Cached API response identity is invalid"));
        }
        let fetched_at = DateTime::parse_from_rfc3339(&entry.fetched_at)
            .map_err(|error| Error::new(format!("Cached API timestamp is invalid: {error}")))?
            .with_timezone(&Utc);
        let age = Utc::now().signed_duration_since(fetched_at).num_seconds();
        if age < 0 {
            return Err(Error::new(
                "Cached API response has a future fetch timestamp",
            ));
        }
        if age > MAXIMUM_CACHE_AGE_SECONDS {
            return Ok(None);
        }
        Ok(Some(CachedResponse {
            data: serde_json::from_str(&entry.content)?,
            content: entry.content.into_bytes(),
            fetched_at,
        }))
    }

    pub(super) fn write(&self, request_sha256: &str, response: &CachedResponse) -> Result<()> {
        let entry = CacheEntry {
            schema_version: 1,
            request_sha256: request_sha256.into(),
            response_sha256: sha256(&response.content),
            fetched_at: response.fetched_at.to_rfc3339(),
            content: std::str::from_utf8(&response.content)
                .map_err(|error| Error::new(format!("API response is not UTF-8: {error}")))?
                .into(),
        };
        atomic_write_json(
            &self.directory.join(format!("{request_sha256}.json")),
            &serde_json::to_value(entry)?,
        )
    }
}
