use std::collections::BTreeMap;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::error::{Error, Result};
use crate::json::sha256;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MatchMode {
    Ranked,
    Unranked,
}

impl MatchMode {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Ranked => "ranked",
            Self::Unranked => "unranked",
        }
    }
}

impl std::str::FromStr for MatchMode {
    type Err = Error;

    fn from_str(value: &str) -> Result<Self> {
        match value.trim().to_ascii_lowercase().as_str() {
            "ranked" => Ok(Self::Ranked),
            "unranked" => Ok(Self::Unranked),
            _ => Err(Error::new("Match mode must be ranked or unranked")),
        }
    }
}

impl std::fmt::Display for MatchMode {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.as_str())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum EvidenceUnit {
    #[serde(rename = "asset")]
    Asset,
    #[serde(rename = "purchase_event")]
    PurchaseEvent,
    #[serde(rename = "eligible_player_appearance")]
    EligibleAppearance,
    #[serde(rename = "ability_path")]
    AbilityPath,
    #[serde(rename = "ability_decision_reached")]
    AbilityDecision,
    #[serde(rename = "hero_appearance")]
    HeroAppearance,
    #[serde(rename = "hero_enemy_pair")]
    HeroEnemyPair,
    #[serde(rename = "game")]
    Game,
    #[serde(rename = "adjacent_phase_item_pair")]
    ItemFlowPair,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct EpochBoundary {
    pub identity: String,
    pub start_timestamp: i64,
}

impl EpochBoundary {
    /// # Errors
    /// Returns an error for an empty identity or negative timestamp.
    pub fn validate(&self) -> Result<()> {
        if self.identity.trim().is_empty() || self.start_timestamp < 0 {
            return Err(Error::new(
                "Epoch requires a nonempty identity and a nonnegative start timestamp",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct EpochSet {
    pub mechanics: EpochBoundary,
    pub matchmaking: EpochBoundary,
    pub map_objectives: EpochBoundary,
    pub telemetry: EpochBoundary,
}

impl EpochSet {
    #[must_use]
    pub fn analysis_start_timestamp(&self) -> i64 {
        self.mechanics
            .start_timestamp
            .max(self.matchmaking.start_timestamp)
            .max(self.map_objectives.start_timestamp)
            .max(self.telemetry.start_timestamp)
    }

    /// # Errors
    /// Returns an error when an epoch boundary is invalid.
    pub fn validate(&self) -> Result<()> {
        for boundary in [
            &self.mechanics,
            &self.matchmaking,
            &self.map_objectives,
            &self.telemetry,
        ] {
            boundary.validate()?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EvidenceRecord {
    pub path: String,
    pub parameters: Map<String, Value>,
    pub fetched_at: String,
    pub sha256: String,
    pub byte_count: usize,
    pub unit: EvidenceUnit,
    pub backend_grain: String,
    pub fallback_behavior: String,
    pub warnings: Vec<String>,
}

impl EvidenceRecord {
    /// # Errors
    /// Returns an error for invalid request identity, semantics, timestamp, or response fingerprint.
    pub fn validate(&self) -> Result<()> {
        if self.path.is_empty()
            || self.backend_grain.trim().is_empty()
            || self.fallback_behavior.trim().is_empty()
        {
            return Err(Error::new(
                "Evidence record requires a request path, backend grain, and fallback behavior",
            ));
        }
        validate_sha256(&self.sha256, "Evidence response")?;
        DateTime::parse_from_rfc3339(&self.fetched_at)
            .map_err(|error| Error::new(format!("Evidence fetch timestamp is invalid: {error}")))?;
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct EvidenceSemantics {
    pub unit: EvidenceUnit,
    pub backend_grain: String,
    pub fallback_behavior: String,
    pub warnings: Vec<String>,
}

#[derive(Clone, Debug, Default)]
pub struct EvidenceRecorder {
    records: Vec<EvidenceRecord>,
    semantics: BTreeMap<String, EvidenceSemantics>,
}

impl EvidenceRecorder {
    #[must_use]
    pub fn fork(&self) -> Self {
        Self {
            records: Vec::new(),
            semantics: self.semantics.clone(),
        }
    }

    pub fn append(&mut self, mut other: Self) {
        self.records.append(&mut other.records);
    }

    /// # Errors
    /// Returns an error when the evidence declaration is incomplete.
    pub fn declare(&mut self, path: &str, semantics: EvidenceSemantics) -> Result<()> {
        if path.is_empty()
            || semantics.backend_grain.trim().is_empty()
            || semantics.fallback_behavior.trim().is_empty()
        {
            return Err(Error::new(
                "Evidence declaration requires a path, backend grain, and fallback behavior",
            ));
        }
        self.semantics.insert(path.to_owned(), semantics);
        Ok(())
    }

    /// # Errors
    /// Returns an error when the request path has no declared evidence semantics.
    pub fn record(
        &mut self,
        path: &str,
        parameters: Map<String, Value>,
        bytes: &[u8],
        fetched_at: DateTime<Utc>,
    ) -> Result<()> {
        let semantics = self
            .semantics
            .get(path)
            .ok_or_else(|| Error::new(format!("Evidence semantics are not declared for {path}")))?;
        self.records.push(EvidenceRecord {
            path: path.to_owned(),
            parameters,
            fetched_at: fetched_at.to_rfc3339(),
            sha256: sha256(bytes),
            byte_count: bytes.len(),
            unit: semantics.unit,
            backend_grain: semantics.backend_grain.clone(),
            fallback_behavior: semantics.fallback_behavior.clone(),
            warnings: semantics.warnings.clone(),
        });
        Ok(())
    }

    #[must_use]
    pub fn records(&self) -> &[EvidenceRecord] {
        &self.records
    }
}

/// # Errors
/// Returns an error when the value is not a lowercase SHA-256 digest.
pub fn validate_sha256(value: &str, label: &str) -> Result<()> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(Error::new(format!(
            "{label} fingerprint must contain 64 lowercase hexadecimal digits"
        )));
    }
    Ok(())
}
