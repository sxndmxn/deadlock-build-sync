use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use deadlock_data::{
    ArtifactCoverage, BuildKey, Error, Result, SnapshotManifest, array, object, parse_build_key,
    read_json, text,
};
use deadlock_input::FUNCTION_CLASSES;
use serde_json::{Map, Value};

use crate::context_fingerprints::{
    CONTEXT_SCHEMA_VERSION, calculate_context_sha256, calculate_kit_basis_sha256,
    calculate_narrative_basis_sha256, calculate_source_context_sha256,
};
use crate::context_mechanics::{validate_hero_item_mechanics, validate_mechanics_catalog};

#[derive(Clone, Debug)]
pub struct StrategyContext {
    document: Value,
    manifest: SnapshotManifest,
    coverage: ArtifactCoverage,
    heroes: BTreeMap<BuildKey, Value>,
    item_mechanics: Map<String, Value>,
}

impl StrategyContext {
    /// # Errors
    /// Returns an error when context schema, identities, mechanics, coverage, or fingerprints fail validation.
    pub fn from_document(document: Value) -> Result<Self> {
        if document["schema_version"].as_u64() != Some(u64::from(CONTEXT_SCHEMA_VERSION)) {
            return Err(Error::new("Unsupported strategy context schema"));
        }
        let manifest = SnapshotManifest::from_document(&document["snapshot_manifest"])?;
        let coverage = ArtifactCoverage::from_document(&document)?;
        let item_mechanics = object(&document["item_mechanics"])?.clone();
        validate_mechanics_catalog(&item_mechanics)?;
        let mut heroes = BTreeMap::new();
        let mut referenced = BTreeSet::new();
        for entry in array(&document["heroes"])? {
            let key = parse_build_key(entry)?;
            referenced.extend(validate_hero(entry, &manifest, &item_mechanics)?);
            if heroes.insert(key, entry.clone()).is_some() {
                return Err(Error::new("Strategy context repeats a build path"));
            }
        }
        coverage.validate_keys(heroes.keys().map(|(id, path)| (*id, path.as_str())))?;
        let referenced = referenced
            .into_iter()
            .map(|id| id.to_string())
            .collect::<BTreeSet<_>>();
        if referenced != item_mechanics.keys().cloned().collect() {
            return Err(Error::new(
                "Strategy context has unreferenced item mechanics",
            ));
        }
        if document["source_context_sha256"] != calculate_source_context_sha256(&document)? {
            return Err(Error::new("Strategy context document fingerprint differs"));
        }
        Ok(Self {
            document,
            manifest,
            coverage,
            heroes,
            item_mechanics,
        })
    }

    /// # Errors
    /// Returns an error when the context file cannot be read or fails validation.
    pub fn load(path: &Path) -> Result<Self> {
        Self::from_document(read_json(path)?)
    }

    #[must_use]
    pub const fn document(&self) -> &Value {
        &self.document
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
    pub const fn heroes(&self) -> &BTreeMap<BuildKey, Value> {
        &self.heroes
    }

    #[must_use]
    pub const fn item_mechanics(&self) -> &Map<String, Value> {
        &self.item_mechanics
    }
}

fn validate_hero(
    entry: &Value,
    manifest: &SnapshotManifest,
    mechanics: &Map<String, Value>,
) -> Result<Vec<u64>> {
    if entry["snapshot_id"] != manifest.identifier() {
        return Err(Error::new("Hero context uses a different snapshot"));
    }
    let referenced = validate_hero_item_mechanics(entry, mechanics)?;
    validate_build_identity(&entry["projection"]["build"], manifest)?;
    for (field, expected) in [
        ("kit_basis_sha256", calculate_kit_basis_sha256(entry)?),
        (
            "narrative_basis_sha256",
            calculate_narrative_basis_sha256(entry)?,
        ),
        ("context_sha256", calculate_context_sha256(entry)?),
    ] {
        if entry[field] != expected {
            return Err(Error::new(format!(
                "Hero context {field} differs; export the context again"
            )));
        }
    }
    Ok(referenced)
}

fn validate_build_identity(build: &Value, manifest: &SnapshotManifest) -> Result<()> {
    let ids: [u64; 3] = serde_json::from_value(build["tag_ids"].clone())?;
    let classes: [String; 3] = serde_json::from_value(build["tag_classes"].clone())?;
    let labels: [String; 3] = serde_json::from_value(build["tag_labels"].clone())?;
    if ids.contains(&0)
        || ids.into_iter().collect::<BTreeSet<_>>().len() != 3
        || classes[..2].iter().any(|name| name.trim().is_empty())
        || !FUNCTION_CLASSES.contains(&classes[2].as_str())
        || labels.iter().any(|label| label.trim().is_empty())
        || build["tag_catalog_sha256"] != manifest.content().build_tags_sha256
        || text(build, "archetype")?.trim().is_empty()
    {
        return Err(Error::new("Strategy context has invalid build tags"));
    }
    Ok(())
}
