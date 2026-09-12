use std::collections::{BTreeMap, BTreeSet};

use serde_json::{Map, Value, json};

use crate::error::{Error, Result};
use crate::json::{array, integer, text};

pub type BuildKey = (u64, String);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactCoverage {
    requested: BTreeSet<u64>,
    exclusions: BTreeMap<u64, String>,
}

impl ArtifactCoverage {
    /// # Errors
    /// Returns an error when a hero identifier or exclusion reason is invalid.
    pub fn new(requested: BTreeSet<u64>, exclusions: BTreeMap<u64, String>) -> Result<Self> {
        if requested.contains(&0)
            || !exclusions.keys().all(|id| requested.contains(id))
            || exclusions.values().any(|reason| reason.trim().is_empty())
        {
            return Err(Error::new(
                "Artifact coverage has invalid hero identifiers or exclusion reasons",
            ));
        }
        Ok(Self {
            requested,
            exclusions,
        })
    }

    /// # Errors
    /// Returns an error when coverage fields have invalid types or repeated identifiers.
    pub fn from_document(document: &Value) -> Result<Self> {
        let mut requested = BTreeSet::new();
        for value in array(&document["requested_hero_ids"])? {
            let id = value
                .as_u64()
                .filter(|id| *id > 0)
                .ok_or_else(|| Error::new("Requested hero identifier must be positive"))?;
            if !requested.insert(id) {
                return Err(Error::new("Requested hero identifiers must be unique"));
            }
        }
        let mut exclusions = BTreeMap::new();
        for row in array(&document["exclusions"])? {
            let id = integer(row, "hero_id")?;
            let reason = text(row, "reason")?;
            if exclusions.insert(id, reason.into()).is_some() {
                return Err(Error::new("Artifact repeats an excluded hero"));
            }
        }
        Self::new(requested, exclusions)
    }

    #[must_use]
    pub const fn requested(&self) -> &BTreeSet<u64> {
        &self.requested
    }

    #[must_use]
    pub const fn exclusions(&self) -> &BTreeMap<u64, String> {
        &self.exclusions
    }

    #[must_use]
    pub fn document_fields(&self) -> Map<String, Value> {
        Map::from_iter([
            (
                "requested_hero_ids".into(),
                self.requested.iter().copied().collect::<Vec<_>>().into(),
            ),
            (
                "exclusions".into(),
                self.exclusions
                    .iter()
                    .map(|(id, reason)| json!({"hero_id":id,"reason":reason}))
                    .collect::<Vec<_>>()
                    .into(),
            ),
        ])
    }

    /// # Errors
    /// Returns an error when paths repeat, included heroes have exclusions, or coverage differs from the requested roster.
    pub fn validate_keys<'path>(
        &self,
        keys: impl IntoIterator<Item = (u64, &'path str)>,
    ) -> Result<()> {
        let mut seen = BTreeSet::new();
        let mut heroes = BTreeSet::new();
        for (id, path) in keys {
            if id == 0 || path.trim().is_empty() || !seen.insert((id, path)) {
                return Err(Error::new("Artifact has an invalid or repeated build path"));
            }
            if self.exclusions.contains_key(&id) {
                return Err(Error::new("Artifact includes and excludes the same hero"));
            }
            heroes.insert(id);
        }
        heroes.extend(self.exclusions.keys());
        if heroes != self.requested {
            return Err(Error::new("Artifact does not cover the requested heroes"));
        }
        Ok(())
    }
}

/// # Errors
/// Returns an error when the build has no positive hero identifier or nonempty path identifier.
pub fn parse_build_key(entry: &Value) -> Result<BuildKey> {
    let id = integer(entry, "hero_id")?;
    let path = text(entry, "path_id")?;
    if id == 0 || path.trim().is_empty() {
        return Err(Error::new(
            "Build requires a positive hero identifier and a nonempty path",
        ));
    }
    Ok((id, path.into()))
}
