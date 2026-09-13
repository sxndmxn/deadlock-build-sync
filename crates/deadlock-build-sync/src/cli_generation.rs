use std::path::Path;

use deadlock_data::{EpochSet, Error, RankRange, Result};
use deadlock_guides::{BuildEvidenceCatalog, NarrativeCatalog};
use deadlock_input::{ApiOptions, ApiResponseCache, DeadlockApi};
use serde_json::{Map, Value};

use crate::cli_arguments::{
    GenerationArguments, NarrativeSelection, RankExpansion, SnapshotArguments,
};
use crate::cli_paths::absolute_path;
use crate::generation::{GenerationRequest, generate_guides};
use crate::generation_types::GeneratedGuides;

pub fn require_current_evidence(source: &Path, base_url: &str) -> Result<BuildEvidenceCatalog> {
    let evidence = BuildEvidenceCatalog::read(source)?;
    require_current_build_identity(
        evidence.metadata().client_version,
        &evidence.metadata().patch,
        base_url,
    )?;
    Ok(evidence)
}

pub fn require_current_build_identity(
    client_version: u64,
    patch: &Map<String, Value>,
    base_url: &str,
) -> Result<()> {
    let mut api = DeadlockApi::new(ApiOptions {
        base_url: base_url.into(),
        ..ApiOptions::default()
    })?;
    let version = api.resolve_client_version()?;
    let current_patch = api.current_patch()?;
    if client_version != version || patch.get("identity") != Some(&current_patch.identity()?.into())
    {
        return Err(Error::new(
            "Build evidence is stale. Run deadlock-build-sync refresh-evidence",
        ));
    }
    Ok(())
}

pub fn generate_requested(
    base_url: &str,
    arguments: &GenerationArguments,
    evidence: &BuildEvidenceCatalog,
    evidence_path: &Path,
    account_id: u32,
    narratives: Option<&NarrativeCatalog>,
) -> Result<GeneratedGuides> {
    let ranks = RankRange {
        minimum: arguments.ranks.min_rank,
        maximum: arguments.ranks.max_rank,
    }
    .validate()?;
    if arguments.ranks.rank_expansion == RankExpansion::Off
        && evidence
            .heroes()
            .values()
            .flat_map(|hero| &hero.builds)
            .any(|build| build.cohort.content().minimum_badge < ranks.minimum)
    {
        return Err(Error::new(
            "Build evidence contains expanded hero cohorts. Refresh with --rank-expansion off",
        ));
    }
    let snapshot = &arguments.snapshot;
    let mut api = DeadlockApi::new(ApiOptions {
        base_url: base_url.into(),
        rank_range: ranks,
        match_mode: snapshot.match_mode,
        client_version: Some(
            snapshot
                .client_version
                .unwrap_or_else(|| evidence.metadata().client_version),
        ),
        as_of_timestamp: snapshot
            .as_of_timestamp
            .unwrap_or_else(|| evidence.metadata().as_of_timestamp),
        epochs: Some(
            selected_epochs(snapshot)?.unwrap_or_else(|| evidence.metadata().epochs.clone()),
        ),
        response_cache: Some(ApiResponseCache::reuse_for_evidence(evidence_path)),
        ..ApiOptions::default()
    })?;
    generate_guides(
        &mut api,
        evidence,
        &GenerationRequest {
            account_id,
            hero_query: arguments.selection.hero.clone(),
            all_heroes: arguments.selection.all || arguments.selection.hero.is_none(),
        },
        narratives,
    )
}

fn selected_epochs(arguments: &SnapshotArguments) -> Result<Option<EpochSet>> {
    match (
        &arguments.mechanics_epoch,
        &arguments.matchmaking_epoch,
        &arguments.map_objectives_epoch,
        &arguments.telemetry_epoch,
    ) {
        (None, None, None, None) => Ok(None),
        (Some(mechanics), Some(matchmaking), Some(map_objectives), Some(telemetry)) => {
            Ok(Some(EpochSet {
                mechanics: mechanics.clone(),
                matchmaking: matchmaking.clone(),
                map_objectives: map_objectives.clone(),
                telemetry: telemetry.clone(),
            }))
        }
        _ => Err(Error::new("Supply all four epoch boundaries together")),
    }
}

pub fn load_narratives(arguments: &NarrativeSelection) -> Result<Option<NarrativeCatalog>> {
    if arguments.without_narratives {
        return Ok(None);
    }
    let path = absolute_path(
        arguments
            .narratives
            .as_deref()
            .unwrap_or_else(|| Path::new("generated/narratives.json")),
    )?;
    Ok(Some(NarrativeCatalog::load(&path)?))
}

pub fn require_selection(arguments: &GenerationArguments) -> Result<()> {
    if arguments.selection.hero.is_none() && !arguments.selection.all {
        return Err(Error::new("Supply --hero NAME or --all"));
    }
    Ok(())
}
