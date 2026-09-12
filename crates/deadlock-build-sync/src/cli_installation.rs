use std::collections::BTreeSet;
use std::path::Path;

use deadlock_data::{
    ArtifactCoverage, Error, RankRange, Result, SnapshotManifest, state_directory, trace_operation,
};
use deadlock_guides::{GuideIdentity, PurchaseGuide, build_presentation, projection_fingerprint};
use deadlock_input::Patch;
use deadlock_steam::{
    CacheLocation, CacheUpdateRequest, InstallResult, LinuxProcesses, ManagedBuild,
    install_cache_update, prepare_cache_update, read_cache,
};
use serde_json::json;

use crate::cli_output::print_json;

#[derive(Debug)]
pub struct InstallationParameters<'source> {
    pub persona: &'source str,
    pub patch: &'source Patch,
    pub ranks: RankRange,
    pub manifest: &'source SnapshotManifest,
    pub expected_heroes: &'source BTreeSet<u64>,
    pub allow_subset: bool,
}

pub fn install_guides(
    location: &CacheLocation,
    guides: &[PurchaseGuide],
    parameters: &InstallationParameters<'_>,
) -> Result<InstallResult> {
    let mut builds = Vec::new();
    for guide in guides {
        let presentation = build_presentation(
            guide,
            parameters.persona,
            &parameters.patch.title,
            &parameters.patch.published_at,
            parameters.ranks,
        )?;
        builds.push(ManagedBuild::new(
            presentation,
            GuideIdentity {
                snapshot_id: guide.snapshot_id.clone(),
                policy_id: guide.policy_id.clone(),
                client_version: guide
                    .client_version
                    .ok_or_else(|| Error::new("Guide has no client version"))?,
                match_mode: guide.match_mode.parse()?,
                rank_identity: guide.rank_identity.clone(),
                projection_fingerprint: projection_fingerprint(guide)?,
            },
        )?);
    }
    let original = read_cache(&location.cache_path)?;
    let update = trace_operation("steam.prepare_update", Some("prepare_steam_update"), || {
        prepare_cache_update(
            &original,
            &CacheUpdateRequest {
                builds: &builds,
                account_id: location.account_id,
                timestamp: u64::try_from(chrono::Utc::now().timestamp())?,
                snapshot: parameters.manifest,
                expected_hero_ids: parameters.expected_heroes,
                allow_subset: parameters.allow_subset,
            },
        )
    })?;
    trace_operation("steam.install_update", Some("install_steam_update"), || {
        install_cache_update(location, &update, &state_directory()?, &LinuxProcesses)
    })
}

pub fn print_installation(
    result: &InstallResult,
    artifacts: Option<&Path>,
    manifest: &SnapshotManifest,
    coverage: &ArtifactCoverage,
) -> Result<()> {
    print_json(
        &json!({"cache_path":result.cache_path,"backup_path":result.backup_directory,"artifacts":artifacts,
        "created":result.created,"updated":result.updated,"removed":result.removed,"changed":result.changed,
        "snapshot_id":manifest.identifier(),"rank_range":manifest.content().rank_range,
        "builds":result.build_ids.iter().map(|(key, id)| json!({"hero_id":key.hero_id,"path_id":key.path_id,"build_id":id})).collect::<Vec<_>>(),
        "skipped_heroes":coverage.exclusions().iter().map(|(id, reason)| json!({"hero_id":id,"reason":reason})).collect::<Vec<_>>()}),
    )
}
