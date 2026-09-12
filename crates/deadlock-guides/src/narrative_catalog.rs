use std::collections::BTreeMap;
use std::path::Path;

use deadlock_data::{
    ArtifactCoverage, BuildKey, Error, Result, array, integer, read_json, text, validate_sha256,
};
use deadlock_input::Patch;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::purchase_guide::PurchaseGuide;

pub const NARRATIVE_SCHEMA_VERSION: u8 = 9;
pub const NARRATIVE_GENERATOR_VERSION: u8 = 1;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NarrativeEntry {
    pub hero_id: u64,
    pub path_id: String,
    #[serde(default)]
    pub hero: String,
    pub snapshot_id: String,
    pub policy_id: String,
    pub context_sha256: String,
    pub narrative_basis_sha256: String,
    pub generator_version: u8,
    pub build_description: String,
}

impl NarrativeEntry {
    /// # Errors
    /// Returns an error when the entry identity, generator version, or description is invalid.
    pub fn validate(&self) -> Result<()> {
        if self.hero_id == 0
            || self.path_id.trim().is_empty()
            || self.generator_version != NARRATIVE_GENERATOR_VERSION
        {
            return Err(Error::new(
                "Narrative entry has invalid identity or generator fields",
            ));
        }
        for (value, label) in [
            (&self.snapshot_id, "Snapshot"),
            (&self.policy_id, "Policy"),
            (&self.context_sha256, "Context"),
            (&self.narrative_basis_sha256, "Narrative basis"),
        ] {
            validate_sha256(value, label)?;
        }
        if self.build_description.trim().is_empty() {
            return Err(Error::new("Narrative entry has no build description"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct NarrativeCatalog {
    document: Value,
    snapshot_id: String,
    patch_identity: String,
    client_version: u64,
    match_mode: String,
    game_mode: String,
    source_context_sha256: String,
    coverage: ArtifactCoverage,
    heroes: BTreeMap<BuildKey, NarrativeEntry>,
}

impl NarrativeCatalog {
    /// # Errors
    /// Returns an error when the schema, source identities, roster coverage, or narrative entries fail validation.
    pub fn from_document(document: Value) -> Result<Self> {
        if document["schema_version"].as_u64() != Some(u64::from(NARRATIVE_SCHEMA_VERSION))
            || document["generator_version"].as_u64()
                != Some(u64::from(NARRATIVE_GENERATOR_VERSION))
        {
            return Err(Error::new(
                "Unsupported narrative schema or description generator",
            ));
        }
        let snapshot_id = text(&document, "snapshot_id")?.to_owned();
        let source_context_sha256 = text(&document, "source_context_sha256")?.to_owned();
        let patch_identity = text(&document["patch"], "identity")?.to_owned();
        for (value, label) in [
            (&snapshot_id, "Snapshot"),
            (&source_context_sha256, "Source context"),
            (&patch_identity, "Patch"),
        ] {
            validate_sha256(value, label)?;
        }
        let cohort = &document["cohort"];
        let client_version = integer(cohort, "client_version")?;
        let match_mode = text(cohort, "match_mode")?.to_owned();
        let game_mode = text(cohort, "game_mode")?.to_owned();
        if client_version == 0
            || !["ranked", "unranked"].contains(&match_mode.as_str())
            || game_mode != "normal"
        {
            return Err(Error::new("Narrative catalog has an invalid cohort"));
        }
        let coverage = ArtifactCoverage::from_document(&document)?;
        let mut heroes = BTreeMap::new();
        for entry in array(&document["heroes"])? {
            let entry: NarrativeEntry = serde_json::from_value(entry.clone())?;
            entry.validate()?;
            if entry.snapshot_id != snapshot_id
                || heroes
                    .insert((entry.hero_id, entry.path_id.clone()), entry)
                    .is_some()
            {
                return Err(Error::new(
                    "Narrative catalog contains a stale or repeated build path",
                ));
            }
        }
        coverage.validate_keys(heroes.keys().map(|(id, path)| (*id, path.as_str())))?;
        Ok(Self {
            document,
            snapshot_id,
            patch_identity,
            client_version,
            match_mode,
            game_mode,
            source_context_sha256,
            coverage,
            heroes,
        })
    }

    /// # Errors
    /// Returns an error when the narrative file cannot be read or fails validation.
    pub fn load(path: &Path) -> Result<Self> {
        Self::from_document(read_json(path)?)
    }

    #[must_use]
    pub const fn document(&self) -> &Value {
        &self.document
    }
    #[must_use]
    pub fn snapshot_id(&self) -> &str {
        &self.snapshot_id
    }
    #[must_use]
    pub fn patch_identity(&self) -> &str {
        &self.patch_identity
    }
    #[must_use]
    pub const fn client_version(&self) -> u64 {
        self.client_version
    }
    #[must_use]
    pub fn match_mode(&self) -> &str {
        &self.match_mode
    }
    #[must_use]
    pub fn game_mode(&self) -> &str {
        &self.game_mode
    }
    #[must_use]
    pub fn source_context_sha256(&self) -> &str {
        &self.source_context_sha256
    }
    #[must_use]
    pub const fn coverage(&self) -> &ArtifactCoverage {
        &self.coverage
    }
    #[must_use]
    pub const fn heroes(&self) -> &BTreeMap<BuildKey, NarrativeEntry> {
        &self.heroes
    }

    /// # Errors
    /// Returns an error when the reviewed description uses a different source, policy, or context identity.
    pub fn apply(&self, guide: &mut PurchaseGuide, context: &Value, patch: &Patch) -> Result<()> {
        if self.patch_identity != patch.identity()?
            || self.snapshot_id != guide.snapshot_id
            || Some(self.client_version) != guide.client_version
            || self.match_mode != guide.match_mode
        {
            return Err(Error::new(
                "Narrative artifact differs from the guide snapshot, patch, or cohort",
            ));
        }
        let entry = self
            .heroes
            .get(&(guide.hero_id, guide.path_id.clone()))
            .ok_or_else(|| {
                Error::new(format!(
                    "Narrative artifact has no build {}/{}",
                    guide.hero_id, guide.path_id
                ))
            })?;
        if entry.policy_id != guide.policy_id
            || context["context_sha256"] != entry.context_sha256
            || context["narrative_basis_sha256"] != entry.narrative_basis_sha256
        {
            return Err(Error::new(
                "Narrative entry differs from the policy or context fingerprint",
            ));
        }
        guide.summary = entry.build_description.trim().into();
        guide.tactical_profile = None;
        Ok(())
    }
}
