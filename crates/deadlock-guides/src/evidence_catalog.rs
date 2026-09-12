use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use deadlock_data::{
    EpochSet, Error, MatchMode, RankCatalog, RankRange, Result, array, fingerprint, object,
    read_json_bytes,
};
use serde_json::Value;

use crate::evidence_catalog_groups::{primary_build, validate_hero_groups};
use crate::evidence_catalog_header::{BuildEvidenceMetadata, parse_header};
use crate::hero_evidence::{HeroBuildEvidence, HeroEvidence};

#[derive(Clone, Debug)]
pub struct BuildEvidenceCatalog {
    metadata: BuildEvidenceMetadata,
    heroes: BTreeMap<u64, HeroEvidence>,
    assets: Vec<Value>,
    raw_bytes: Vec<u8>,
}

#[derive(Clone, Debug)]
pub struct BuildEvidenceIdentity<'data> {
    pub patch_identity: &'data str,
    pub client_version: u64,
    pub as_of_timestamp: i64,
    pub match_mode: MatchMode,
    pub rank_range: RankRange,
    pub rank_catalog: &'data RankCatalog,
    pub heroes: &'data [Value],
    pub assets: &'data [Value],
    pub epochs: &'data EpochSet,
}

impl BuildEvidenceCatalog {
    /// # Errors
    /// Returns an error when an evidence artifact is unreadable, malformed, or fails admission checks.
    pub fn read(path: &Path) -> Result<Self> {
        let (bytes, document) = read_json_bytes(path)?;
        Self::parse(bytes, &document).map_err(|error| error.context(path.display()))
    }

    /// # Errors
    /// Returns an error when an evidence artifact exceeds 512 MiB or fails its schema, fingerprint, or admission checks.
    pub fn from_bytes(bytes: Vec<u8>) -> Result<Self> {
        if bytes.len() > 512 * 1024 * 1024 {
            return Err(Error::new("Build evidence exceeds the artifact size limit"));
        }
        let document = serde_json::from_slice(&bytes)?;
        Self::parse(bytes, &document)
    }

    fn parse(raw_bytes: Vec<u8>, document: &Value) -> Result<Self> {
        let metadata = parse_header(document)?;
        let mut heroes = BTreeMap::new();
        for row in array(&document["heroes"])? {
            let hero = HeroEvidence::from_document(row)?;
            validate_hero_groups(&hero, &metadata)?;
            if heroes.insert(hero.hero_id, hero).is_some() {
                return Err(Error::new("Build evidence contains duplicate heroes"));
            }
        }
        if heroes.keys().copied().collect::<BTreeSet<_>>() != metadata.requested_hero_ids {
            return Err(Error::new(
                "Build evidence does not exactly cover its requested heroes",
            ));
        }
        let assets = array(&document["mechanics_assets"])?;
        if assets.is_empty() || fingerprint(&document["mechanics_assets"])? != metadata.items_sha256
        {
            return Err(Error::new(
                "Build evidence has no compatible mechanics assets; run refresh-evidence",
            ));
        }
        for asset in assets {
            object(asset)?;
        }
        Ok(Self {
            metadata,
            heroes,
            assets: assets.to_vec(),
            raw_bytes,
        })
    }

    #[must_use]
    pub const fn metadata(&self) -> &BuildEvidenceMetadata {
        &self.metadata
    }

    #[must_use]
    pub const fn heroes(&self) -> &BTreeMap<u64, HeroEvidence> {
        &self.heroes
    }

    #[must_use]
    pub fn assets(&self) -> &[Value] {
        &self.assets
    }

    #[must_use]
    pub fn raw_bytes(&self) -> &[u8] {
        &self.raw_bytes
    }

    /// # Errors
    /// Returns an error when the requested subset is empty, contains unknown heroes, or fails artifact admission.
    pub fn select_hero_subset(&self, requested: &BTreeSet<u64>) -> Result<Self> {
        if requested.is_empty() || !requested.is_subset(&self.metadata.requested_hero_ids) {
            return Err(Error::new(
                "Requested heroes are absent from the build evidence",
            ));
        }
        if requested == &self.metadata.requested_hero_ids {
            return Ok(self.clone());
        }
        let mut document: Value = serde_json::from_slice(&self.raw_bytes)?;
        let heroes = array(&document["heroes"])?
            .iter()
            .filter(|hero| {
                hero["hero_id"]
                    .as_u64()
                    .is_some_and(|hero| requested.contains(&hero))
            })
            .cloned()
            .collect::<Vec<_>>();
        document["heroes"] = heroes.into();
        document["requested_hero_ids"] = serde_json::to_value(requested)?;
        document["source_artifact_id"] = self.metadata.artifact_id.clone().into();
        document
            .as_object_mut()
            .ok_or_else(|| Error::new("Build evidence must be an object"))?
            .remove("artifact_id");
        document["artifact_id"] = fingerprint(&document)?.into();
        Self::from_bytes(serde_json::to_vec_pretty(&document)?)
    }

    /// # Errors
    /// Returns an error when a frozen selection rank is invalid.
    pub fn primary_build(&self, hero_id: u64) -> Result<Option<&HeroBuildEvidence>> {
        primary_build(
            self.heroes
                .get(&hero_id)
                .into_iter()
                .flat_map(|hero| &hero.builds),
        )
    }

    /// # Errors
    /// Returns an error when evidence differs from the current pinned inputs or cohort.
    pub fn assert_compatible(&self, expected: &BuildEvidenceIdentity<'_>) -> Result<()> {
        expected.rank_range.validate()?;
        let metadata = &self.metadata;
        let cohort = &metadata.cohort;
        let checks = [
            (
                "patch",
                metadata.patch.get("identity").and_then(Value::as_str)
                    == Some(expected.patch_identity),
            ),
            (
                "client_version",
                metadata.client_version == expected.client_version,
            ),
            (
                "as_of_timestamp",
                metadata.as_of_timestamp == expected.as_of_timestamp,
            ),
            (
                "match_mode",
                cohort
                    .get("match_mode")
                    .and_then(Value::as_str)
                    .is_some_and(|mode| mode.eq_ignore_ascii_case(expected.match_mode.as_str())),
            ),
            (
                "game_mode",
                cohort
                    .get("game_mode")
                    .and_then(Value::as_str)
                    .is_some_and(|mode| mode.eq_ignore_ascii_case("normal")),
            ),
            (
                "minimum_badge",
                cohort.get("minimum_badge").and_then(Value::as_u64)
                    == Some(u64::from(expected.rank_range.minimum.badge())),
            ),
            (
                "maximum_badge",
                cohort.get("maximum_badge").and_then(Value::as_u64)
                    == Some(u64::from(expected.rank_range.maximum.badge())),
            ),
            (
                "rank_labels",
                metadata.rank_labels_sha256 == expected.rank_catalog.fingerprint(),
            ),
            (
                "heroes",
                metadata.heroes_sha256 == fingerprint(&Value::Array(expected.heroes.to_vec()))?,
            ),
            (
                "items",
                metadata.items_sha256 == fingerprint(&Value::Array(expected.assets.to_vec()))?,
            ),
            ("epochs", metadata.epochs == *expected.epochs),
        ];
        let mut differences = checks
            .iter()
            .filter_map(|(label, compatible)| (!compatible).then_some(*label))
            .collect::<Vec<_>>();
        differences.sort_unstable();
        if !differences.is_empty() {
            return Err(Error::new(format!(
                "Build evidence is incompatible in: {}",
                differences.join(", ")
            )));
        }
        Ok(())
    }
}
