use std::collections::BTreeSet;

use chrono::DateTime;
use deadlock_data::{
    EpochSet, Error, Rank, RankRange, Result, array, fingerprint, object, text, validate_sha256,
};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};

use crate::discovery_evidence::REFRESH_INSTRUCTION;
use crate::evidence_values::integer;
use crate::generator_evidence::{
    BEAM_METHOD_VERSION, BEAM_SCHEMA_VERSION, validate_generator_header,
};

pub const BUILD_EVIDENCE_SCHEMA_VERSION: u64 = 12;
pub const CURRENT_METHOD_VERSION: &str = "eclat-leiden-pairwise-v4";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum BuildGenerator {
    Current,
    Beam,
}

impl BuildGenerator {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Current => "current",
            Self::Beam => "beam",
        }
    }
}

#[derive(Clone, Debug)]
pub struct BuildEvidenceMetadata {
    pub artifact_id: String,
    pub client_version: u64,
    pub patch: Map<String, Value>,
    pub cohort: Map<String, Value>,
    pub epochs: EpochSet,
    pub rank_labels_sha256: String,
    pub heroes_sha256: String,
    pub items_sha256: String,
    pub requested_hero_ids: BTreeSet<u64>,
    pub as_of_timestamp: i64,
    pub generator: BuildGenerator,
}

pub fn parse_header(document: &Value) -> Result<BuildEvidenceMetadata> {
    let mut payload = object(document)?.clone();
    let artifact_id = sha256_field(document, "artifact_id")?;
    payload.remove("artifact_id");
    if fingerprint(&Value::Object(payload))? != artifact_id {
        return Err(Error::new(
            "Build evidence fingerprint does not match its contents",
        ));
    }
    let generator = parse_generator(document)?;
    validate_method(document, generator)?;
    let patch = object(&document["patch"])?.clone();
    sha256_field(&document["patch"], "identity")?;
    let cohort = object(&document["cohort"])?.clone();
    validate_rank_range(&document["cohort"])?;
    let as_of_timestamp = DateTime::parse_from_rfc3339(text(&document["cohort"], "as_of")?)
        .map_err(|error| {
            Error::new(format!(
                "Build evidence has an invalid timestamp or missing timezone: {error}"
            ))
        })?
        .timestamp();
    let epochs: EpochSet = serde_json::from_value(document["epochs"].clone())?;
    epochs.validate()?;
    if as_of_timestamp < epochs.analysis_start_timestamp() {
        return Err(Error::new(
            "Build evidence cutoff precedes an epoch boundary",
        ));
    }
    Ok(BuildEvidenceMetadata {
        artifact_id,
        client_version: integer(&document["client_version"], "client version", 1)?,
        patch,
        cohort,
        epochs,
        as_of_timestamp,
        generator,
        rank_labels_sha256: sha256_field(document, "rank_labels_sha256")?,
        heroes_sha256: sha256_field(document, "heroes_sha256")?,
        items_sha256: sha256_field(document, "items_sha256")?,
        requested_hero_ids: parse_requested(&document["requested_hero_ids"])?,
    })
}

fn parse_generator(document: &Value) -> Result<BuildGenerator> {
    match document["schema_version"].as_u64() {
        Some(BUILD_EVIDENCE_SCHEMA_VERSION) => {
            if document.get("generator").is_some() {
                return Err(Error::new(
                    "Current evidence cannot contain a beam generator header",
                ));
            }
            Ok(BuildGenerator::Current)
        }
        Some(BEAM_SCHEMA_VERSION) => {
            validate_generator_header(&document["generator"])?;
            Ok(BuildGenerator::Beam)
        }
        _ => Err(Error::new(format!(
            "Unsupported build evidence schema. {REFRESH_INSTRUCTION}"
        ))),
    }
}

fn validate_method(document: &Value, generator: BuildGenerator) -> Result<()> {
    let method = object(&document["method"])?;
    let expected = expected_selection_method(generator);
    if object(&expected)?
        .iter()
        .any(|(key, value)| method.get(key) != Some(value))
    {
        return Err(Error::new(format!(
            "Build evidence uses an unsupported selection method. {REFRESH_INSTRUCTION}"
        )));
    }
    Ok(())
}

#[must_use]
pub fn expected_selection_method(generator: BuildGenerator) -> Value {
    let version = match generator {
        BuildGenerator::Current => CURRENT_METHOD_VERSION,
        BuildGenerator::Beam => BEAM_METHOD_VERSION,
    };
    json!({"version":version,"minimum_core_item_count":3,"maximum_core_item_count":9,"minimum_core_support":100,
        "minimum_tier_support":20,"minimum_tier_adoption":0.05,"maximum_tier_adoption_drift":0.10,"tier_item_count":10,
        "minimum_purchase_window_coverage":0.50,"minimum_purchase_window_observations":20,"minimum_imbue_support":20,"minimum_imbue_share":0.5})
}

fn parse_requested(value: &Value) -> Result<BTreeSet<u64>> {
    let mut requested = BTreeSet::new();
    for value in array(value)? {
        if !requested.insert(integer(value, "requested hero identifier", 1)?) {
            return Err(Error::new(
                "Build evidence contains duplicate requested heroes",
            ));
        }
    }
    Ok(requested)
}

fn validate_rank_range(cohort: &Value) -> Result<()> {
    let rank = |field: &str| Rank::try_from(u16::try_from(integer(&cohort[field], field, 1)?)?);
    RankRange {
        minimum: rank("minimum_badge")?,
        maximum: rank("maximum_badge")?,
    }
    .validate()?;
    Ok(())
}

fn sha256_field(document: &Value, name: &str) -> Result<String> {
    let value = text(document, name)?;
    validate_sha256(value, name)?;
    Ok(value.into())
}
