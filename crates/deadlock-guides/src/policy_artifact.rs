use std::collections::BTreeMap;
use std::path::Path;

use deadlock_data::{
    ArtifactCoverage, BuildKey, Error, Result, SnapshotManifest, array, read_json,
};
use serde_json::Value;

use crate::policy_model::BuildPolicy;

pub const POLICY_ARTIFACT_SCHEMA_VERSION: u8 = 4;

#[derive(Clone, Debug)]
pub struct PolicyArtifact {
    manifest: SnapshotManifest,
    coverage: ArtifactCoverage,
    policies: BTreeMap<BuildKey, BuildPolicy>,
}

impl PolicyArtifact {
    /// # Errors
    /// Returns an error when policies have stale snapshot identities or incomplete roster coverage.
    pub fn new(
        policies: Vec<BuildPolicy>,
        manifest: SnapshotManifest,
        coverage: ArtifactCoverage,
    ) -> Result<Self> {
        coverage.validate_keys(
            policies
                .iter()
                .map(|policy| (policy.content().hero_id, policy.content().path_id.as_str())),
        )?;
        let mut indexed = BTreeMap::new();
        for policy in policies {
            let content = policy.content();
            if content.snapshot_id != manifest.identifier() {
                return Err(Error::new(
                    "Policy artifact contains another snapshot identity",
                ));
            }
            indexed.insert((content.hero_id, content.path_id.clone()), policy);
        }
        Ok(Self {
            manifest,
            coverage,
            policies: indexed,
        })
    }

    /// # Errors
    /// Returns an error when the sidecar schema, manifest, policies, or coverage fails validation.
    pub fn from_document(value: &Value) -> Result<Self> {
        if value["schema_version"].as_u64() != Some(u64::from(POLICY_ARTIFACT_SCHEMA_VERSION)) {
            return Err(Error::new("Unsupported policy artifact schema"));
        }
        let manifest = SnapshotManifest::from_document(&value["snapshot_manifest"])?;
        let coverage = ArtifactCoverage::from_document(value)?;
        let policies = array(&value["policies"])?
            .iter()
            .map(BuildPolicy::from_document)
            .collect::<Result<Vec<_>>>()?;
        Self::new(policies, manifest, coverage)
    }

    /// # Errors
    /// Returns an error when the sidecar cannot be read or fails validation.
    pub fn load(path: &Path) -> Result<Self> {
        Self::from_document(&read_json(path)?)
    }

    #[must_use]
    pub const fn manifest(&self) -> &SnapshotManifest {
        &self.manifest
    }

    #[must_use]
    pub const fn coverage(&self) -> &ArtifactCoverage {
        &self.coverage
    }

    #[must_use]
    pub const fn policies(&self) -> &BTreeMap<BuildKey, BuildPolicy> {
        &self.policies
    }

    /// # Errors
    /// Returns an error when policy or manifest serialization fails.
    pub fn to_document(&self) -> Result<Value> {
        let mut document = self.coverage.document_fields();
        document.insert(
            "schema_version".into(),
            POLICY_ARTIFACT_SCHEMA_VERSION.into(),
        );
        document.insert("snapshot_manifest".into(), self.manifest.to_document()?);
        document.insert(
            "policies".into(),
            self.policies
                .values()
                .map(|policy| policy.to_document(true))
                .collect::<Result<Vec<_>>>()?
                .into(),
        );
        Ok(document.into())
    }
}
