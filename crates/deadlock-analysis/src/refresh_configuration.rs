use std::path::{Path, PathBuf};

use deadlock_data::{Error, Rank, RankRange, Result, format_timestamp, parse_timestamp};
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const DUCKLAKE_URL: &str = "https://data.deadlock-api.com/v1/catalog.ducklake";
pub const RANK_RESET_AT: &str = "2026-07-30T19:14:37Z";

#[derive(Clone, Debug)]
pub struct RefreshRequest {
    pub root: PathBuf,
    pub run_id: Option<String>,
    pub since: Option<i64>,
    pub as_of: Option<i64>,
    pub ranks: RankRange,
    pub extraction_resources: ExtractionResources,
    pub resume: bool,
    pub api_base_url: String,
}

#[derive(Clone, Copy, Debug)]
pub struct ExtractionResources {
    pub memory_limit_mb: u32,
    pub threads: u16,
}

impl ExtractionResources {
    /// # Errors
    /// Returns an error when the memory limit or thread count is zero.
    pub fn validate(self) -> Result<()> {
        if self.memory_limit_mb == 0 || self.threads == 0 {
            return Err(Error::new(
                "Extraction requires positive memory and thread limits",
            ));
        }
        Ok(())
    }
}

/// The match mode and game mode of every run.
pub const MATCH_MODE: &str = "Ranked";
pub const GAME_MODE: &str = "Normal";

#[derive(Clone, Debug)]
pub struct Cohort {
    pub ranks: RankRange,
    pub since: i64,
    pub as_of: i64,
}

impl Cohort {
    pub fn validate(&self) -> Result<()> {
        self.ranks.validate()?;
        if self.since < 0 || self.since >= self.as_of {
            return Err(Error::new(
                "Cohort start must be nonnegative and precede its cutoff",
            ));
        }
        Ok(())
    }

    /// Returns the manifest record of the cohort.
    ///
    /// # Errors
    /// Returns an error when the cohort is invalid.
    pub fn record(&self) -> Result<CohortRecord> {
        self.validate()?;
        Ok(CohortRecord {
            minimum_badge: self.ranks.minimum.badge(),
            maximum_badge: self.ranks.maximum.badge(),
            since: format_timestamp(self.since)?,
            as_of: format_timestamp(self.as_of)?,
            match_mode: MATCH_MODE.into(),
            game_mode: GAME_MODE.into(),
        })
    }

    /// Returns the filters that select the cached rows: the record without its cutoff.
    ///
    /// The filters are part of the cache file name, so their keys must not change.
    ///
    /// # Errors
    /// Returns an error when the cohort is invalid.
    pub fn cache_filters(&self) -> Result<Value> {
        let mut filters = serde_json::to_value(self.record()?)?;
        if let Some(filters) = filters.as_object_mut() {
            filters.remove("as_of");
        }
        Ok(filters)
    }
}

/// The match filters of a run in its manifest, with timestamps as RFC 3339 text.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CohortRecord {
    pub minimum_badge: u16,
    pub maximum_badge: u16,
    pub since: String,
    pub as_of: String,
    pub match_mode: String,
    pub game_mode: String,
}

impl CohortRecord {
    /// # Errors
    /// Returns an error when a badge is not a rank or the range is inverted.
    pub fn ranks(&self) -> Result<RankRange> {
        RankRange {
            minimum: Rank::try_from(self.minimum_badge)?,
            maximum: Rank::try_from(self.maximum_badge)?,
        }
        .validate()
    }

    /// # Errors
    /// Returns an error when a badge or a timestamp is invalid.
    pub fn cohort(&self) -> Result<Cohort> {
        let cohort = Cohort {
            ranks: self.ranks()?,
            since: parse_timestamp(&self.since)?,
            as_of: parse_timestamp(&self.as_of)?,
        };
        cohort.validate()?;
        Ok(cohort)
    }
}

/// The run identifier format when `--run-id` is absent: the UTC start time.
const AUTOMATIC_RUN_ID_FORMAT: &str = "%Y%m%dT%H%M%SZ";

pub fn is_automatic_run_id(identifier: &str) -> bool {
    chrono::NaiveDateTime::parse_from_str(identifier, AUTOMATIC_RUN_ID_FORMAT).is_ok()
}

#[derive(Clone, Debug)]
pub struct RunPaths {
    pub run: PathBuf,
    pub raw: PathBuf,
    /// The cache of downloaded remote files, which all runs share.
    pub cache: PathBuf,
}

impl RunPaths {
    /// Opens the paths of an existing analysis run directory.
    ///
    /// # Errors
    /// Returns an error when the directory has no `manifest.json` file.
    pub fn open(run: &Path) -> Result<Self> {
        if !run.join(MANIFEST_FILE).is_file() {
            return Err(Error::new(format!(
                "Run directory has no manifest.json: {}",
                run.display()
            )));
        }
        // A run directory is ROOT/results/RUN_ID, and the shared cache is ROOT/cache.
        let root = run
            .parent()
            .and_then(Path::parent)
            .ok_or_else(|| Error::new("Run directory must be inside ROOT/results"))?;
        Ok(Self {
            raw: run.join("raw"),
            run: run.to_path_buf(),
            cache: root.join("cache"),
        })
    }

    /// Creates the directories of one analysis run.
    ///
    /// # Errors
    /// Returns an error for an invalid run identifier or a failed directory creation.
    pub fn create(root: &Path, run_id: Option<&str>) -> Result<Self> {
        let identifier = run_id.map_or_else(
            || {
                chrono::Utc::now()
                    .format(AUTOMATIC_RUN_ID_FORMAT)
                    .to_string()
            },
            str::to_owned,
        );
        if identifier.is_empty()
            || identifier.len() > 120
            || !identifier
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
        {
            return Err(Error::new(
                "Run identifier must contain 1 to 120 ASCII letters, digits, hyphens, or underscores",
            ));
        }
        let run = root.join("results").join(identifier);
        let paths = Self {
            raw: run.join("raw"),
            run,
            cache: root.join("cache"),
        };
        std::fs::create_dir_all(&paths.raw)?;
        Ok(paths)
    }

    /// The manifest file of the run.
    #[must_use]
    pub fn manifest(&self) -> PathBuf {
        self.run.join(MANIFEST_FILE)
    }

    /// The extracted `DuckDB` database of the run.
    #[must_use]
    pub fn database(&self) -> PathBuf {
        self.raw.join(DATABASE_FILE)
    }
}

const MANIFEST_FILE: &str = "manifest.json";
const DATABASE_FILE: &str = "analysis.duckdb";
