use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use serde_json::{Value, json};

use crate::build_metadata::{HeroBuildMetadata, parse_hero_build_metadata};
use crate::cache_read::{SteamCache, validate_sections};
use crate::cache_request::{BuildKey, CacheUpdateRequest, validate_request};
use crate::cache_scope::unmanaged_fingerprint;
use crate::kv3_encode::encode_kv3;
use crate::kv3_value::{Kv3Kind, Kv3Value};
use crate::protobuf_encode::{encode_hero_build, same_build_content, wrap_hero_build};

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

#[derive(Debug, Default)]
struct ManagedScan {
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
    let unpublished = document.root.field("Unpublished")?.array()?;
    let scan = scan_managed(unpublished, &desired, account_id)?;
    validate_local_identifiers(unpublished, &scan, account_id)?;
    let mut next_id = next_local_id(original, account_id)?;
    let mut build_ids = BTreeMap::new();
    let mut replacement = scan.retained;
    let mut created = 0;
    let mut updated = 0;
    for build in builds {
        let previous = scan.existing.get(&build.key);
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
        .find(|(name, _)| name == "Unpublished")
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
        manifest: backup_manifest(original, request, &build_ids)?,
        original_bytes: original.bytes().to_vec(),
        replacement,
        account_id,
        build_ids,
        created,
        updated,
        removed: scan.removed - (builds.len() - created),
    })
}

fn backup_manifest(
    original: &SteamCache,
    request: &CacheUpdateRequest<'_>,
    identifiers: &BTreeMap<BuildKey, u64>,
) -> Result<Value> {
    let builds = request
        .builds
        .iter()
        .map(|build| {
            json!({
                "hero_id":build.key.hero_id, "path_id":build.key.path_id,
                "build_id":identifiers.get(&build.key), "policy_id":build.identity.policy_id,
                "projection_fingerprint":build.identity.projection_fingerprint,
            })
        })
        .collect::<Vec<_>>();
    let heroes = request
        .builds
        .iter()
        .map(|build| build.key.hero_id)
        .collect();
    let out_of_scope = unmanaged_fingerprint(original.document(), request.account_id, &heroes)?;
    Ok(
        json!({"builds":builds, "snapshot":request.snapshot.to_document()?, "snapshot_id":request.snapshot.identifier(), "rank_range":request.snapshot.content().rank_range, "out_of_scope_sha256":out_of_scope}),
    )
}

fn target_metadata(
    value: &Kv3Value,
    desired: &BTreeSet<BuildKey>,
    account_id: u32,
) -> Option<HeroBuildMetadata> {
    let metadata = parse_hero_build_metadata(value.blob().ok()?).ok()?;
    let hero = metadata.hero_id?;
    (desired.iter().any(|key| key.hero_id == hero) && metadata.is_managed(hero, account_id))
        .then_some(metadata)
}

fn scan_managed(
    values: &[Kv3Value],
    desired: &BTreeSet<BuildKey>,
    account_id: u32,
) -> Result<ManagedScan> {
    let mut scan = ManagedScan::default();
    for value in values {
        let Some(metadata) = target_metadata(value, desired, account_id) else {
            scan.retained.push(value.clone());
            continue;
        };
        scan.removed += 1;
        let Some(key) = metadata_key(&metadata) else {
            continue;
        };
        if desired.contains(&key) {
            let identifier = metadata
                .build_id
                .filter(|identifier| *identifier > 0 && *identifier < 1000)
                .ok_or_else(|| Error::new("Managed build has an invalid local build ID"))?;
            if scan
                .existing
                .values()
                .any(|(existing_id, _)| *existing_id == identifier)
            {
                return Err(Error::new("Managed build paths share one local build ID"));
            }
            if scan
                .existing
                .insert(key, (identifier, value.clone()))
                .is_some()
            {
                return Err(Error::new(
                    "Steam cache contains duplicate managed build paths",
                ));
            }
        }
    }
    Ok(scan)
}

fn metadata_key(metadata: &HeroBuildMetadata) -> Option<BuildKey> {
    Some(BuildKey {
        hero_id: metadata.hero_id?,
        path_id: metadata.managed_path()?.to_owned(),
    })
}

fn validate_local_identifiers(
    values: &[Kv3Value],
    scan: &ManagedScan,
    account_id: u32,
) -> Result<()> {
    let mut counts = BTreeMap::<u64, usize>::new();
    for value in values {
        if let Some(metadata) = value
            .blob()
            .ok()
            .and_then(|bytes| parse_hero_build_metadata(bytes).ok())
            && metadata.author_account_id == Some(u64::from(account_id))
            && metadata
                .publish_timestamp
                .is_none_or(|timestamp| timestamp == 0)
            && let Some(identifier) = metadata.build_id
        {
            *counts.entry(identifier).or_default() += 1;
        }
    }
    if scan
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

fn next_local_id(cache: &SteamCache, account_id: u32) -> Result<u64> {
    let mut greatest = 1;
    for name in ["Favorites", "Unpublished", "SavedLastUsed"] {
        let section = cache.document().root.field(name)?;
        let Kv3Kind::Array(values) = &section.kind else {
            continue;
        };
        for value in values {
            let metadata = value
                .blob()
                .ok()
                .and_then(|bytes| parse_hero_build_metadata(bytes).ok());
            if let Some(metadata) = metadata
                && metadata.author_account_id == Some(u64::from(account_id))
                && metadata
                    .publish_timestamp
                    .is_none_or(|timestamp| timestamp == 0)
                && let Some(identifier) = metadata.build_id.filter(|identifier| *identifier < 1000)
            {
                greatest = greatest.max(identifier);
            }
        }
    }
    Ok(greatest + 1)
}

fn allocate_id(next: &mut u64) -> Result<u64> {
    if *next >= 1000 {
        return Err(Error::new("No safe local build ID remains below 1000"));
    }
    let identifier = *next;
    *next += 1;
    Ok(identifier)
}

fn validate_preserved_values(
    original: &SteamCache,
    replacement: &SteamCache,
    desired: &BTreeSet<BuildKey>,
    account_id: u32,
) -> Result<()> {
    let mut previous = original.document().clone();
    let mut current = replacement.document().clone();
    for document in [&mut previous, &mut current] {
        let Kv3Kind::Object(members) = &mut document.root.kind else {
            return Err(Error::new("Steam cache root must be an object"));
        };
        let (_, unpublished) = members
            .iter_mut()
            .find(|(name, _)| name == "Unpublished")
            .ok_or_else(|| Error::new("Steam cache has no Unpublished section"))?;
        let Kv3Kind::Array(values) = &mut unpublished.kind else {
            return Err(Error::new("Steam Unpublished section must be an array"));
        };
        values.retain(|value| target_metadata(value, desired, account_id).is_none());
    }
    if previous != current {
        return Err(Error::new("Cache replacement changes unrelated Steam data"));
    }
    Ok(())
}
