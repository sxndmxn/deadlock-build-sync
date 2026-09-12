use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::error::{Error, Result};
use crate::json::fingerprint;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FingerprintLayers {
    pub mechanics: String,
    pub analytics: String,
    pub policy_basis: String,
    pub narrative: String,
    pub projection: String,
}

impl FingerprintLayers {
    /// # Errors
    /// Returns an error when an artifact layer cannot serialize.
    pub fn calculate(
        mechanics: &Value,
        analytics: &Value,
        policy_basis: &Value,
        narrative: &Value,
        projection: &Value,
    ) -> Result<Self> {
        let mechanics = fingerprint(mechanics)?;
        let analytics = fingerprint(&json!({"mechanics":mechanics,"analytics":analytics}))?;
        let policy_basis = fingerprint(
            &json!({"mechanics":mechanics,"analytics":analytics,"policy_basis":policy_basis}),
        )?;
        let narrative = fingerprint(&json!({"policy_basis":policy_basis,"narrative":narrative}))?;
        let projection =
            fingerprint(&json!({"policy_basis":policy_basis,"projection":projection}))?;
        Ok(Self {
            mechanics,
            analytics,
            policy_basis,
            narrative,
            projection,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArtifactCompatibility {
    pub schema_version: u64,
    pub hero_id: u64,
    pub snapshot_id: String,
    pub client_version: u64,
    pub match_mode: String,
    pub rank_labels_sha256: String,
    pub mechanics_sha256: String,
    pub analytics_sha256: String,
    pub policy_basis_sha256: String,
    pub description_generator_version: Option<u64>,
    pub path_id: String,
}

impl ArtifactCompatibility {
    /// # Errors
    /// Returns an error when schema, source, cohort, or evidence identities differ.
    pub fn assert_reusable_with(&self, expected: &Self) -> Result<()> {
        if self == expected {
            return Ok(());
        }
        let actual = serde_json::to_value(self)?;
        let expected = serde_json::to_value(expected)?;
        let differences = crate::json::object(&expected)?
            .iter()
            .filter(|(key, value)| actual.get(*key) != Some(*value))
            .map(|(key, _)| key.as_str())
            .collect::<Vec<_>>();
        Err(Error::new(format!(
            "Artifact has incompatible fields: {}",
            differences.join(", ")
        )))
    }
}
