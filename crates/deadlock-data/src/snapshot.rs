use chrono::DateTime;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::error::{Error, Result};
use crate::evidence::{EpochSet, EvidenceRecord, MatchMode, validate_sha256};
use crate::json::fingerprint;

const OUTCOME_EXCLUSIONS: [&str; 7] = [
    "exclude_not_scored",
    "exclude_penalized",
    "exclude_party_penalized",
    "exclude_abandoned",
    "exclude_unrewarded",
    "exclude_low_priority",
    "exclude_new_player",
];

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SnapshotContent {
    pub schema_version: u32,
    pub client_version: u64,
    pub as_of_timestamp: i64,
    pub created_at: String,
    pub match_mode: MatchMode,
    pub game_mode: String,
    pub rank_range: Map<String, Value>,
    pub rank_labels_sha256: String,
    pub build_tags_sha256: String,
    pub patch: Map<String, Value>,
    pub epochs: EpochSet,
    pub outcome_policy: Map<String, Value>,
    pub records: Vec<EvidenceRecord>,
    pub warnings: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct SnapshotManifest {
    content: SnapshotContent,
    identifier: String,
}

impl SnapshotManifest {
    /// # Errors
    /// Returns an error for incomplete source identities or inconsistent evidence timestamps.
    pub fn new(content: SnapshotContent) -> Result<Self> {
        validate_content(&content)?;
        let mut identity = serde_json::to_value(&content)?;
        remove_fetch_times(&mut identity)?;
        let identifier = fingerprint(&identity)?;
        Ok(Self {
            content,
            identifier,
        })
    }

    /// # Errors
    /// Returns an error for an invalid manifest or a mismatched snapshot fingerprint.
    pub fn from_document(document: &Value) -> Result<Self> {
        let identifier = document["snapshot_id"]
            .as_str()
            .ok_or_else(|| Error::new("Snapshot manifest has no snapshot ID"))?;
        let mut payload = document.clone();
        payload
            .as_object_mut()
            .ok_or_else(|| Error::new("Snapshot manifest must be an object"))?
            .remove("snapshot_id");
        let content = serde_json::from_value(payload)?;
        let manifest = Self::new(content)?;
        if identifier != manifest.identifier {
            return Err(Error::new(
                "Snapshot ID does not match the source identities",
            ));
        }
        Ok(manifest)
    }

    #[must_use]
    pub const fn content(&self) -> &SnapshotContent {
        &self.content
    }

    #[must_use]
    pub fn identifier(&self) -> &str {
        &self.identifier
    }

    /// # Errors
    /// Returns an error when epoch serialization fails.
    pub fn cohort_record(&self) -> Result<Map<String, Value>> {
        Ok(Map::from_iter([
            ("match_mode".into(), self.content.match_mode.as_str().into()),
            ("game_mode".into(), self.content.game_mode.clone().into()),
            ("rank_range".into(), self.content.rank_range.clone().into()),
            (
                "as_of_timestamp".into(),
                self.content.as_of_timestamp.into(),
            ),
            ("epochs".into(), serde_json::to_value(&self.content.epochs)?),
        ]))
    }

    /// # Errors
    /// Returns an error when a rank bound has no display label.
    pub fn rank_identity(&self) -> Result<String> {
        let format_rank = |name: &str| -> Result<String> {
            let rank = self
                .content
                .rank_range
                .get(name)
                .ok_or_else(|| Error::new("Snapshot rank bound is missing"))?;
            let label = rank["label"]
                .as_str()
                .ok_or_else(|| Error::new("Snapshot rank label is missing"))?;
            let badge = rank["badge_id"]
                .as_u64()
                .ok_or_else(|| Error::new("Snapshot rank badge is missing"))?;
            Ok(format!("{label} [{badge}]"))
        };
        let minimum = format_rank("minimum")?;
        let maximum = format_rank("maximum")?;
        Ok(if minimum == maximum {
            minimum
        } else {
            format!("{minimum}–{maximum}")
        })
    }

    /// # Errors
    /// Returns an error when manifest serialization fails.
    pub fn to_document(&self) -> Result<Value> {
        let mut document = serde_json::to_value(&self.content)?;
        document["snapshot_id"] = self.identifier.clone().into();
        Ok(document)
    }
}

fn validate_content(content: &SnapshotContent) -> Result<()> {
    if content.schema_version != 1 || content.client_version == 0 || content.game_mode != "normal" {
        return Err(Error::new(
            "Snapshot requires schema 1, a positive client version, and the normal game mode",
        ));
    }
    content.epochs.validate()?;
    if content.as_of_timestamp < content.epochs.analysis_start_timestamp() {
        return Err(Error::new(
            "Snapshot cutoff precedes a required epoch boundary",
        ));
    }
    if content.records.is_empty() {
        return Err(Error::new("Snapshot manifest has no source records"));
    }
    validate_sha256(&content.rank_labels_sha256, "Rank catalog")?;
    validate_sha256(&content.build_tags_sha256, "Build tag catalog")?;
    validate_rank_range(&content.rank_range)?;
    validate_outcome_policy(&content.outcome_policy)?;
    DateTime::parse_from_rfc3339(&content.created_at)
        .map_err(|error| Error::new(format!("Snapshot creation timestamp is invalid: {error}")))?;
    for record in &content.records {
        record.validate()?;
    }
    Ok(())
}

fn validate_rank_range(value: &Map<String, Value>) -> Result<()> {
    let rank = |name: &str| -> Result<crate::rank::Rank> {
        let badge = value
            .get(name)
            .and_then(|value| value.get("badge_id"))
            .and_then(Value::as_u64)
            .ok_or_else(|| Error::new(format!("Snapshot rank range has no {name} badge")))?;
        crate::rank::Rank::try_from(u16::try_from(badge)?)
    };
    crate::rank::RankRange {
        minimum: rank("minimum")?,
        maximum: rank("maximum")?,
    }
    .validate()?;
    Ok(())
}

fn validate_outcome_policy(value: &Map<String, Value>) -> Result<()> {
    for name in OUTCOME_EXCLUSIONS.into_iter().chain(["enforced_by_source"]) {
        if value.get(name).and_then(Value::as_bool).is_none() {
            return Err(Error::new(format!(
                "Snapshot outcome policy has no boolean {name} field"
            )));
        }
    }
    Ok(())
}

fn remove_fetch_times(document: &mut Value) -> Result<()> {
    let object = document
        .as_object_mut()
        .ok_or_else(|| Error::new("Snapshot identity is not an object"))?;
    object.remove("created_at");
    let records = object
        .get_mut("records")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| Error::new("Snapshot identity has no source record list"))?;
    for record in records {
        record
            .as_object_mut()
            .ok_or_else(|| Error::new("Snapshot source record is not an object"))?
            .remove("fetched_at");
    }
    Ok(())
}

#[must_use]
pub fn default_outcome_policy(enforced: bool) -> Map<String, Value> {
    let mut policy = OUTCOME_EXCLUSIONS
        .into_iter()
        .map(|name| (name.to_owned(), Value::Bool(true)))
        .collect::<Map<_, _>>();
    policy.insert("enforced_by_source".into(), enforced.into());
    policy
}
