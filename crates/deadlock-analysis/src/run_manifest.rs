//! The manifest of an analysis run: the cohort, the captured sources, and the extraction counts.

use std::collections::BTreeMap;

use deadlock_data::{Error, Result, atomic_write_json, read_json};
use serde::{Deserialize, Serialize};

use crate::refresh_configuration::{CohortRecord, RunPaths};

pub const MANIFEST_SCHEMA_VERSION: u32 = 2;

/// The fingerprint of the extraction SQL that this executable runs.
///
/// A resumed run must have the same fingerprint, because the SQL defines the extracted tables.
pub const EXTRACTION_SQL_SHA256: &str = env!("DEADLOCK_EXTRACTION_SQL_SHA256");

/// `manifest.json` in the run directory.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RunManifest {
    pub schema_version: u32,
    pub cohort: CohortRecord,
    pub sources: SourceRecord,
    /// The extraction counts. A run without them did not complete its extraction.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub extraction: Option<ExtractionRecord>,
    /// The fingerprint of the extraction SQL. Runs before this field have none.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub extraction_sql_sha256: Option<String>,
}

/// The API sources that a run captured in its `raw` directory.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourceRecord {
    pub client_version: u64,
    pub active_heroes: u64,
    pub shop_items: u64,
    /// The fingerprint of each source file, by file name.
    pub source_sha256: BTreeMap<String, String>,
}

/// The row counts of the extracted tables.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExtractionRecord {
    pub player_matches: u64,
    pub match_folds: u64,
    pub purchases: u64,
    pub heroes: u64,
    pub source_snapshot_version: u64,
}

impl RunManifest {
    /// # Errors
    /// Returns an error when the manifest is missing or malformed.
    pub fn read(paths: &RunPaths) -> Result<Self> {
        serde_json::from_value(read_json(&paths.manifest())?)
            .map_err(|error| Error::new(format!("Malformed run manifest: {error}")))
    }

    /// # Errors
    /// Returns an error when the write fails.
    pub fn write(&self, paths: &RunPaths) -> Result<()> {
        atomic_write_json(&paths.manifest(), &serde_json::to_value(self)?)
    }

    /// # Errors
    /// Returns an error when the run has no extraction counts.
    pub fn extraction(&self) -> Result<&ExtractionRecord> {
        self.extraction
            .as_ref()
            .ok_or_else(|| Error::new("Run manifest has no completed extraction"))
    }
}
