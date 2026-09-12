use std::collections::BTreeSet;

use deadlock_data::{Error, Result, SnapshotManifest};
use deadlock_guides::{BuildPresentation, GuideIdentity};

use crate::build_metadata::HeroBuildMetadata;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct BuildKey {
    pub hero_id: u64,
    pub path_id: String,
}

#[derive(Clone, Debug)]
pub struct ManagedBuild {
    pub(super) key: BuildKey,
    pub(super) presentation: BuildPresentation,
    pub(super) identity: GuideIdentity,
}

impl ManagedBuild {
    /// # Errors
    /// Returns an error when the description and validated guide identities do not match.
    pub fn new(presentation: BuildPresentation, identity: GuideIdentity) -> Result<Self> {
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
        for line in [
            format!("Snapshot: {}.", identity.snapshot_id),
            format!("Policy: {}.", identity.policy_id),
        ] {
            if !content
                .description
                .split('\n')
                .any(|candidate| candidate == line)
            {
                return Err(Error::new(
                    "Build description does not match the guide snapshot or policy identity",
                ));
            }
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
    pub snapshot: &'request SnapshotManifest,
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
    let snapshot = request.snapshot.content();
    let rank_identity = request.snapshot.rank_identity()?;
    for build in request.builds {
        let identity = &build.identity;
        if identity.snapshot_id != request.snapshot.identifier()
            || identity.client_version != snapshot.client_version
            || identity.match_mode != snapshot.match_mode
            || identity.rank_identity != rank_identity
        {
            return Err(Error::new(
                "Guide identity does not match the installation snapshot",
            ));
        }
    }
    Ok(desired)
}
