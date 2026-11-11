use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use deadlock_guides::BuildPresentation;

use crate::cache_read::{SteamCache, UNPUBLISHED};
use crate::cache_request::BuildKey;
use crate::cache_scan::ManagedScan;
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
/// A managed build of an expected hero without a build path is stale. Titles and Steam
/// identity timestamps do not affect this comparison.
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
    let scan = ManagedScan::scan(cache, account_id)?;
    let values = cache.document().root.field(UNPUBLISHED)?.array()?;
    let mut in_scope = BTreeMap::new();
    let mut retained = BTreeSet::new();
    let mut stale = false;
    for (index, entry) in scan.managed() {
        if !expected_heroes.contains(&entry.hero_id) {
            retained.insert(entry.hero_id);
            continue;
        }
        match entry.key() {
            Some(key) => {
                if in_scope.insert(key, index).is_some() {
                    return Err(Error::new(
                        "Steam cache contains duplicate managed build identities",
                    ));
                }
            }
            None => stale = true,
        }
    }
    let mut is_current = !stale && in_scope.keys().eq(expected.keys());
    if is_current {
        for (key, index) in in_scope {
            if !matches_presentation(values[index].blob()?, &expected[&key])? {
                is_current = false;
                break;
            }
        }
    }
    Ok(ManagedBuildComparison {
        is_current,
        retained_heroes: retained.len(),
    })
}
