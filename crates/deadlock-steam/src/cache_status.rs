use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use deadlock_guides::BuildPresentation;

use crate::build_metadata::parse_hero_build_metadata;
use crate::cache_read::SteamCache;
use crate::cache_request::BuildKey;
use crate::protobuf_encode::matches_presentation;

/// Result of comparing installed managed builds with the expected guides.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ManagedBuildComparison {
    /// The managed builds of the expected heroes have the expected identities and contents.
    pub is_current: bool,
    /// Heroes outside the expected guides that keep managed builds from an earlier install.
    pub retained_heroes: usize,
}

/// Compares managed guide contents for the heroes in `expected`.
///
/// Installation keeps the managed builds of other heroes, so they only add to `retained_heroes`.
/// Titles and Steam identity timestamps do not affect this comparison.
///
/// # Errors
/// Returns an error when build data is malformed or managed identities are repeated.
pub fn compare_managed_builds(
    cache: &SteamCache,
    account_id: u32,
    expected: &BTreeMap<BuildKey, BuildPresentation>,
) -> Result<ManagedBuildComparison> {
    let expected_heroes = expected
        .keys()
        .map(|key| key.hero_id)
        .collect::<BTreeSet<_>>();
    let (in_scope, retained): (BTreeMap<_, _>, BTreeMap<_, _>) = managed_builds(cache, account_id)?
        .into_iter()
        .partition(|(key, _)| expected_heroes.contains(&key.hero_id));
    let retained_heroes = retained
        .keys()
        .map(|key| key.hero_id)
        .collect::<BTreeSet<_>>()
        .len();
    let mut is_current = in_scope.keys().eq(expected.keys());
    if is_current {
        for (key, bytes) in in_scope {
            if !matches_presentation(bytes, &expected[&key])? {
                is_current = false;
                break;
            }
        }
    }
    Ok(ManagedBuildComparison {
        is_current,
        retained_heroes,
    })
}

fn managed_builds(cache: &SteamCache, account_id: u32) -> Result<BTreeMap<BuildKey, &[u8]>> {
    let mut builds = BTreeMap::new();
    for value in cache.document().root.field("Unpublished")?.array()? {
        let Ok(bytes) = value.blob() else {
            continue;
        };
        let metadata = parse_hero_build_metadata(bytes)?;
        let Some(hero_id) = metadata.hero_id else {
            continue;
        };
        let Some(path_id) = metadata.managed_path() else {
            continue;
        };
        if !metadata.is_managed(hero_id, account_id) {
            continue;
        }
        let key = BuildKey {
            hero_id,
            path_id: path_id.into(),
        };
        if builds.insert(key, bytes).is_some() {
            return Err(Error::new(
                "Steam cache contains duplicate managed build identities",
            ));
        }
    }
    Ok(builds)
}
