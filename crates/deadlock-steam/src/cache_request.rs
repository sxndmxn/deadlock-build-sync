use std::collections::BTreeSet;

use deadlock_data::{Error, Result};
use deadlock_guides::BuildPresentation;
use serde_json::Value;

use crate::build_metadata::HeroBuildMetadata;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct BuildKey {
    pub hero_id: u64,
    pub path_id: String,
}

/// The source artifact of one installation.
#[derive(Clone, Debug)]
pub struct BuildSnapshot {
    pub snapshot_id: String,
    pub document: Value,
}

/// The source of one managed build: its snapshot and the fingerprint of its content.
#[derive(Clone, Debug)]
pub struct BuildIdentity {
    pub snapshot_id: String,
    pub build_fingerprint: String,
}

impl BuildIdentity {
    fn validate(&self) -> Result<()> {
        for value in [&self.snapshot_id, &self.build_fingerprint] {
            if value.len() != 64
                || !value
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            {
                return Err(Error::new(
                    "Build identity requires lowercase SHA-256 values",
                ));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct ManagedBuild {
    pub(super) key: BuildKey,
    pub(super) presentation: BuildPresentation,
    pub(super) identity: BuildIdentity,
}

impl ManagedBuild {
    /// # Errors
    /// Returns an error when the description does not name the build snapshot.
    pub fn new(presentation: BuildPresentation, identity: BuildIdentity) -> Result<Self> {
        identity.validate()?;
        let content = presentation.content();
        let metadata = HeroBuildMetadata {
            description: Some(content.description.clone()),
            ..HeroBuildMetadata::default()
        };
        let path_id = metadata
            .managed_path()
            .ok_or_else(|| Error::new("Build description has no valid managed build path"))?
            .to_owned();
        let line = format!("Snapshot: {}.", identity.snapshot_id);
        if !content
            .description
            .split('\n')
            .any(|candidate| candidate == line)
        {
            return Err(Error::new(
                "Build description does not match the build snapshot",
            ));
        }
        let key = BuildKey {
            hero_id: content.hero_id,
            path_id,
        };
        Ok(Self {
            key,
            presentation,
            identity,
        })
    }

    #[must_use]
    pub const fn key(&self) -> &BuildKey {
        &self.key
    }
}

#[derive(Debug)]
pub struct CacheUpdateRequest<'request> {
    pub builds: &'request [ManagedBuild],
    pub account_id: u32,
    pub timestamp: u64,
    pub snapshot: &'request BuildSnapshot,
    pub expected_hero_ids: &'request BTreeSet<u64>,
    pub allow_subset: bool,
}

pub fn validate_request(request: &CacheUpdateRequest<'_>) -> Result<BTreeSet<BuildKey>> {
    if request.builds.is_empty() || request.account_id == 0 || request.expected_hero_ids.is_empty()
    {
        return Err(Error::new(
            "Cache update requires builds, expected hero coverage, and a positive account ID",
        ));
    }
    let desired = request
        .builds
        .iter()
        .map(|build| build.key.clone())
        .collect::<BTreeSet<_>>();
    if desired.len() != request.builds.len() {
        return Err(Error::new(
            "Cache update contains duplicate hero and build path pairs",
        ));
    }
    let heroes = desired
        .iter()
        .map(|key| key.hero_id)
        .collect::<BTreeSet<_>>();
    if !heroes.is_subset(request.expected_hero_ids)
        || (!request.allow_subset && &heroes != request.expected_hero_ids)
    {
        return Err(Error::new(
            "Generated guides do not match the required hero coverage",
        ));
    }
    if request
        .builds
        .iter()
        .any(|build| build.identity.snapshot_id != request.snapshot.snapshot_id)
    {
        return Err(Error::new(
            "Build identity does not match the installation snapshot",
        ));
    }
    Ok(desired)
}
