use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use serde_json::{Value, json};

use crate::build_metadata::parse_hero_build_metadata;
use crate::cache_read::{
    FAVORITES, LAST_USED_BUILDS, SAVED_LAST_USED, SteamCache, UNPUBLISHED, validate_sections,
};
use crate::cache_request::{BuildKey, CacheUpdateRequest, validate_request};
use crate::cache_scan::ManagedScan;
use crate::kv3_encode::encode_kv3;
use crate::kv3_value::{Kv3Kind, Kv3Value};
use crate::protobuf_encode::{encode_hero_build, same_build_content, wrap_hero_build};

/// Local build identifiers stay below this value. Steam gives published builds larger ones.
const LOCAL_ID_LIMIT: u64 = 1000;

#[derive(Debug)]
pub struct CacheUpdate {
    pub(super) original_fingerprint: String,
    pub(super) manifest: Value,
    pub(super) original_bytes: Vec<u8>,
    pub(super) replacement: SteamCache,
    pub(super) account_id: u32,
    pub(super) build_ids: BTreeMap<BuildKey, u64>,
    pub(super) created: usize,
    pub(super) updated: usize,
    pub(super) removed: usize,
}

impl CacheUpdate {
    #[must_use]
    pub const fn replacement(&self) -> &SteamCache {
        &self.replacement
    }

    #[must_use]
    pub const fn build_ids(&self) -> &BTreeMap<BuildKey, u64> {
        &self.build_ids
    }

    #[must_use]
    pub const fn created(&self) -> usize {
        self.created
    }

    #[must_use]
    pub const fn updated(&self) -> usize {
        self.updated
    }

    #[must_use]
    pub const fn removed(&self) -> usize {
        self.removed
    }
}

/// The managed builds of the target heroes, and every other value of the section.
#[derive(Debug, Default)]
struct TargetBuilds {
    retained: Vec<Kv3Value>,
    existing: BTreeMap<BuildKey, (u64, Kv3Value)>,
    removed: usize,
}

/// Prepares a cache replacement without writing Steam data.
///
/// # Errors
/// Returns an error for ambiguous build identities, exhausted local IDs, or changed unrelated values.
pub fn prepare_cache_update(
    original: &SteamCache,
    request: &CacheUpdateRequest<'_>,
) -> Result<CacheUpdate> {
    let desired = validate_request(request)?;
    let builds = request.builds;
    let account_id = request.account_id;
    let timestamp = request.timestamp;
    let mut document = original.document().clone();
    let unpublished = document.root.field(UNPUBLISHED)?.array()?;
    let scan = ManagedScan::scan(original, account_id)?;
    if scan.unreadable() > 0 {
        eprintln!(
            "Warning: {} private builds in the Steam cache cannot be parsed. They stay in place",
            scan.unreadable()
        );
    }
    let targets = select_target_builds(unpublished, &scan, &desired)?;
    validate_local_identifiers(unpublished, &targets, account_id)?;
    let mut next_id = next_local_id(original, account_id)?;
    let mut build_ids = BTreeMap::new();
    let mut replacement = targets.retained;
    let mut created = 0;
    let mut updated = 0;
    for build in builds {
        let previous = targets.existing.get(&build.key);
        let identifier = if let Some((identifier, _)) = previous {
            *identifier
        } else {
            let identifier = allocate_id(&mut next_id)?;
            created += 1;
            identifier
        };
        let blob = wrap_hero_build(encode_hero_build(
            &build.presentation,
            identifier,
            account_id,
            timestamp,
        )?)?;
        let value = if let Some((_, previous)) = previous {
            if same_build_content(previous.blob()?, &blob)? {
                previous.clone()
            } else {
                updated += 1;
                Kv3Value::new(Kv3Kind::Blob(blob))
            }
        } else {
            Kv3Value::new(Kv3Kind::Blob(blob))
        };
        replacement.push(value);
        build_ids.insert(build.key.clone(), identifier);
    }
    let Kv3Kind::Object(members) = &mut document.root.kind else {
        return Err(Error::new("Steam cache root must be an object"));
    };
    let section = members
        .iter_mut()
        .find(|(name, _)| name == UNPUBLISHED)
        .ok_or_else(|| Error::new("Steam cache has no Unpublished section"))?;
    section.1.kind = Kv3Kind::Array(replacement);
    validate_sections(&document)?;
    let encoded = if &document == original.document() {
        original.bytes().to_vec()
    } else {
        encode_kv3(&document)?
    };
    let replacement = SteamCache::from_bytes(encoded)?;
    if replacement.document() != &document {
        return Err(Error::new(
            "Steam cache values changed during serialization",
        ));
    }
    validate_preserved_values(original, &replacement, &desired, account_id)?;
    Ok(CacheUpdate {
        original_fingerprint: original.fingerprint(),
        manifest: backup_manifest(request, &build_ids),
        original_bytes: original.bytes().to_vec(),
        replacement,
        account_id,
        build_ids,
        created,
        updated,
        removed: targets.removed - (builds.len() - created),
    })
}

fn backup_manifest(
    request: &CacheUpdateRequest<'_>,
    identifiers: &BTreeMap<BuildKey, u64>,
) -> Value {
    let builds = request
        .builds
        .iter()
        .map(|build| {
            json!({
                "hero_id":build.key.hero_id, "path_id":build.key.path_id,
                "build_id":identifiers.get(&build.key),
                "build_fingerprint":build.identity.build_fingerprint,
            })
        })
        .collect::<Vec<_>>();
    json!({"builds":builds, "snapshot":request.snapshot.document, "snapshot_id":request.snapshot.snapshot_id})
}

/// Separates the managed builds of the desired heroes from the values that stay.
///
/// A managed build of a desired hero without a build path, such as a legacy build, is removed.
fn select_target_builds(
    values: &[Kv3Value],
    scan: &ManagedScan,
    desired: &BTreeSet<BuildKey>,
) -> Result<TargetBuilds> {
    let heroes = desired.iter().map(|key| key.hero_id).collect::<Vec<_>>();
    let positions = scan.positions()?;
    let mut targets = TargetBuilds::default();
    for (index, value) in values.iter().enumerate() {
        if !scan.is_managed_hero(index, &heroes) {
            targets.retained.push(value.clone());
            continue;
        }
        targets.removed += 1;
        let Some((key, entry)) = scan
            .managed()
            .find(|(position, _)| *position == index)
            .and_then(|(_, entry)| Some((entry.key()?, entry)))
        else {
            continue;
        };
        if !desired.contains(&key) || positions.get(&key) != Some(&index) {
            continue;
        }
        let identifier = entry
            .build_id
            .filter(|identifier| *identifier > 0 && *identifier < LOCAL_ID_LIMIT)
            .ok_or_else(|| Error::new("Managed build has an invalid local build ID"))?;
        if targets
            .existing
            .values()
            .any(|(existing_id, _)| *existing_id == identifier)
        {
            return Err(Error::new("Managed build paths share one local build ID"));
        }
        targets.existing.insert(key, (identifier, value.clone()));
    }
    Ok(targets)
}

/// A managed build must not share its local ID with another private build of the account.
fn validate_local_identifiers(
    values: &[Kv3Value],
    targets: &TargetBuilds,
    account_id: u32,
) -> Result<()> {
    let mut counts = BTreeMap::<u64, usize>::new();
    for identifier in values
        .iter()
        .filter_map(|value| private_build_id(value, account_id))
    {
        *counts.entry(identifier).or_default() += 1;
    }
    if targets
        .existing
        .values()
        .any(|(identifier, _)| counts.get(identifier).is_some_and(|count| *count > 1))
    {
        return Err(Error::new(
            "A managed build shares its local build ID with another private build",
        ));
    }
    Ok(())
}

/// Returns the local build ID of a private build value of the account.
fn private_build_id(value: &Kv3Value, account_id: u32) -> Option<u64> {
    parse_hero_build_metadata(value.blob().ok()?)
        .ok()?
        .private_build_id(account_id)
}

/// Returns the next free local build ID, above every private build and the selected build.
fn next_local_id(cache: &SteamCache, account_id: u32) -> Result<u64> {
    let mut greatest = 1;
    for name in [FAVORITES, UNPUBLISHED, SAVED_LAST_USED] {
        let section = cache.document().root.field(name)?;
        let Kv3Kind::Array(values) = &section.kind else {
            continue;
        };
        for identifier in values
            .iter()
            .filter_map(|value| private_build_id(value, account_id))
        {
            greatest = greatest.max(identifier);
        }
    }
    if let Kv3Kind::Unsigned(selected) = cache.document().root.field(LAST_USED_BUILDS)?.kind
        && selected < LOCAL_ID_LIMIT
    {
        greatest = greatest.max(selected);
    }
    Ok(greatest + 1)
}

fn allocate_id(next: &mut u64) -> Result<u64> {
    if *next >= LOCAL_ID_LIMIT {
        return Err(Error::new("No safe local build ID remains below 1000"));
    }
    let identifier = *next;
    *next += 1;
    Ok(identifier)
}

/// The replacement must keep every value that is not a managed build of a desired hero.
fn validate_preserved_values(
    original: &SteamCache,
    replacement: &SteamCache,
    desired: &BTreeSet<BuildKey>,
    account_id: u32,
) -> Result<()> {
    let heroes = desired.iter().map(|key| key.hero_id).collect::<Vec<_>>();
    let mut previous = original.document().clone();
    let mut current = replacement.document().clone();
    for (cache, document) in [(original, &mut previous), (replacement, &mut current)] {
        let scan = ManagedScan::scan(cache, account_id)?;
        let Kv3Kind::Object(members) = &mut document.root.kind else {
            return Err(Error::new("Steam cache root must be an object"));
        };
        let (_, unpublished) = members
            .iter_mut()
            .find(|(name, _)| name == UNPUBLISHED)
            .ok_or_else(|| Error::new("Steam cache has no Unpublished section"))?;
        let Kv3Kind::Array(values) = &mut unpublished.kind else {
            return Err(Error::new("Steam Unpublished section must be an array"));
        };
        let mut index = 0;
        values.retain(|_| {
            let keep = !scan.is_managed_hero(index, &heroes);
            index += 1;
            keep
        });
    }
    if previous != current {
        return Err(Error::new("Cache replacement changes unrelated Steam data"));
    }
    Ok(())
}
