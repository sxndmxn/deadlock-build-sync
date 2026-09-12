use std::path::{Path, PathBuf};

use deadlock_data::{Error, RankRange, Result};
use deadlock_guides::{BuildGenerator, RankExpansion};
use serde_json::{Value, json};

pub const DUCKLAKE_URL: &str = "https://s3-cache.deadlock-api.com/fast/db_snapshot.ducklake";
pub const RANK_RESET_AT: &str = "2026-07-30T19:14:37Z";

#[derive(Clone, Debug)]
pub struct RefreshRequest {
    pub output: PathBuf,
    pub root: PathBuf,
    pub run_id: Option<String>,
    pub since: Option<i64>,
    pub as_of: Option<i64>,
    pub ranks: RankRange,
    pub rank_expansion: RankExpansion,
    pub workers: u16,
    pub resume: bool,
    pub generator: BuildGenerator,
    pub api_base_url: String,
}

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

    pub fn to_document(&self) -> Result<Value> {
        self.validate()?;
        Ok(
            json!({"minimum_badge":self.ranks.minimum.badge(),"maximum_badge":self.ranks.maximum.badge(),
            "since":format_timestamp(self.since)?,"as_of":format_timestamp(self.as_of)?,"match_mode":"Ranked","game_mode":"Normal"}),
        )
    }
}

#[derive(Clone, Debug)]
pub struct RunPaths {
    pub run: PathBuf,
    pub raw: PathBuf,
    pub data: PathBuf,
    pub tables: PathBuf,
}

impl RunPaths {
    pub fn create(root: &Path, run_id: Option<&str>) -> Result<Self> {
        let identifier = run_id.map_or_else(
            || chrono::Utc::now().format("%Y%m%dT%H%M%SZ").to_string(),
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
            data: run.join("data"),
            tables: run.join("tables"),
            run,
        };
        for path in [&paths.raw, &paths.data, &paths.tables] {
            std::fs::create_dir_all(path)?;
        }
        Ok(paths)
    }
}

/// # Errors
/// Returns an error when an ISO 8601 timestamp is invalid or precedes the Unix epoch.
pub fn parse_timestamp(value: &str) -> Result<i64> {
    let timestamp = if let Ok(parsed) = chrono::DateTime::parse_from_rfc3339(value) {
        parsed.timestamp()
    } else if let Ok(parsed) = chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S%.f")
    {
        parsed.and_utc().timestamp()
    } else {
        chrono::NaiveDate::parse_from_str(value, "%Y-%m-%d")
            .ok()
            .and_then(|date| date.and_hms_opt(0, 0, 0))
            .ok_or_else(|| Error::new("Invalid ISO 8601 timestamp"))?
            .and_utc()
            .timestamp()
    };
    if timestamp < 0 {
        return Err(Error::new("Analysis timestamp precedes the Unix epoch"));
    }
    Ok(timestamp)
}

pub fn format_timestamp(value: i64) -> Result<String> {
    chrono::DateTime::from_timestamp(value, 0)
        .map(|date| date.to_rfc3339())
        .ok_or_else(|| Error::new("Analysis timestamp is outside the supported range"))
}

pub fn cohort_ranks(value: &Value) -> Result<RankRange> {
    RankRange {
        minimum: deadlock_data::Rank::try_from(u16::try_from(deadlock_data::integer(
            value,
            "minimum_badge",
        )?)?)?,
        maximum: deadlock_data::Rank::try_from(u16::try_from(deadlock_data::integer(
            value,
            "maximum_badge",
        )?)?)?,
    }
    .validate()
}

pub fn implementation_record() -> Value {
    json!({"language":"rust","source_sha256":env!("DEADLOCK_ANALYSIS_SOURCE_SHA256")})
}
