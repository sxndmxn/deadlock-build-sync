use std::collections::BTreeMap;

use deadlock_data::{Error, Result};
use deadlock_guides::BuildPresentation;

use crate::build_metadata::parse_hero_build_metadata;
use crate::cache_read::SteamCache;
use crate::cache_request::BuildKey;
use crate::protobuf_encode::matches_presentation;

/// Compares managed guide contents. Titles and Steam identity timestamps do not affect this comparison.
///
/// # Errors
/// Returns an error when build data is malformed or managed identities are repeated.
pub fn managed_builds_match(
    cache: &SteamCache,
    account_id: u32,
    expected: &BTreeMap<BuildKey, BuildPresentation>,
) -> Result<bool> {
    let installed = managed_builds(cache, account_id)?;
    if !installed.keys().eq(expected.keys()) {
        return Ok(false);
    }
    for (key, bytes) in installed {
        if !matches_presentation(bytes, &expected[&key])? {
            return Ok(false);
        }
    }
    Ok(true)
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
