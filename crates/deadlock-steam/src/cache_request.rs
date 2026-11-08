use std::collections::BTreeSet;

use deadlock_data::{Error, Result, validate_sha256};
use deadlock_guides::{BuildPresentation, ManagedTrailer};
use serde_json::Value;

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
        validate_sha256(&identity.snapshot_id, "snapshot")?;
        validate_sha256(&identity.build_fingerprint, "build")?;
        let content = presentation.content();
        let trailer = ManagedTrailer::parse(&content.description)
            .ok_or_else(|| Error::new("Build description has no valid managed build path"))?;
        if trailer.snapshot_id != identity.snapshot_id {
            return Err(Error::new(
                "Build description does not match the build snapshot",
            ));
        }
        Ok(Self {
            key: BuildKey {
                hero_id: content.hero_id,
                path_id: trailer.path_id,
            },
            presentation,
            identity,
        })
    }
}

#[derive(Debug)]
pub struct CacheUpdateRequest<'request> {
    pub builds: &'request [ManagedBuild],
    pub account_id: u32,
    pub timestamp: u64,
    pub snapshot: &'request BuildSnapshot,
    pub expected_hero_ids: &'request BTreeSet<u64>,
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
    if &heroes != request.expected_hero_ids {
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
