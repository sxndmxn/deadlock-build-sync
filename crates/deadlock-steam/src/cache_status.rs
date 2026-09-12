use std::collections::BTreeMap;

use deadlock_data::{Error, Result};

use crate::build_metadata::parse_hero_build_metadata;
use crate::cache_read::SteamCache;
use crate::cache_request::BuildKey;

/// # Errors
/// Returns an error when private build metadata is malformed or managed build identities are repeated.
pub fn managed_build_descriptions(
    cache: &SteamCache,
    account_id: u32,
) -> Result<BTreeMap<BuildKey, String>> {
    let mut descriptions = BTreeMap::new();
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
        if descriptions
            .insert(key, metadata.description.unwrap_or_default())
            .is_some()
        {
            return Err(Error::new(
                "Steam cache contains duplicate managed build identities",
            ));
        }
    }
    Ok(descriptions)
}
