use std::path::Path;

use deadlock_data::{EpochSet, Error, RankRange, Result};
use deadlock_guides::{BuildEvidenceCatalog, BuildGenerator, NarrativeCatalog};
use deadlock_input::{ApiOptions, ApiResponseCache, DeadlockApi};

use crate::cli_arguments::{
    GenerationArguments, Generator, NarrativeSelection, RankExpansion, SnapshotArguments,
};
use crate::cli_paths::absolute_path;
use crate::generation::{GenerationRequest, generate_guides};
use crate::generation_types::GeneratedGuides;

pub fn require_current_evidence(source: &Path, base_url: &str) -> Result<BuildEvidenceCatalog> {
    let evidence = BuildEvidenceCatalog::read(source)?;
    let mut api = DeadlockApi::new(ApiOptions {
        base_url: base_url.into(),
        ..ApiOptions::default()
    })?;
    let version = api.resolve_client_version()?;
    let patch = api.current_patch()?;
    if evidence.metadata().client_version != version
        || evidence.metadata().patch.get("identity") != Some(&patch.identity()?.into())
    {
        return Err(Error::new(
            "Build evidence is stale. Run deadlock-build-sync refresh-evidence",
        ));
    }
    Ok(evidence)
}

pub fn require_generator(evidence: &BuildEvidenceCatalog, generator: Generator) -> Result<()> {
    let expected = match generator {
        Generator::Current => BuildGenerator::Current,
        Generator::Beam => BuildGenerator::Beam,
    };
    if evidence.metadata().generator != expected {
        return Err(Error::new(
            "Build evidence uses a different generator. Run refresh-evidence with the selected generator",
        ));
    }
    Ok(())
}

pub fn generate_requested(
    base_url: &str,
    args: &GenerationArguments,
    evidence: &BuildEvidenceCatalog,
    evidence_path: &Path,
    account_id: u32,
    narratives: Option<&NarrativeCatalog>,
) -> Result<GeneratedGuides> {
    let ranks = RankRange {
        minimum: args.ranks.min_rank,
        maximum: args.ranks.max_rank,
    }
    .validate()?;
    if args.ranks.rank_expansion == RankExpansion::Off
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
    let snapshot = &args.snapshot;
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
            hero_query: args.selection.hero.clone(),
            all_heroes: args.selection.all || args.selection.hero.is_none(),
        },
        narratives,
    )
}

fn selected_epochs(args: &SnapshotArguments) -> Result<Option<EpochSet>> {
    match (
        &args.mechanics_epoch,
        &args.matchmaking_epoch,
        &args.map_objectives_epoch,
        &args.telemetry_epoch,
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

pub fn load_narratives(args: &NarrativeSelection) -> Result<Option<NarrativeCatalog>> {
    if args.without_narratives {
        return Ok(None);
    }
    let path = absolute_path(
        args.narratives
            .as_deref()
            .unwrap_or_else(|| Path::new("generated/narratives.json")),
    )?;
    Ok(Some(NarrativeCatalog::load(&path)?))
}

pub fn require_selection(args: &GenerationArguments) -> Result<()> {
    if args.selection.hero.is_none() && !args.selection.all {
        return Err(Error::new("Supply --hero NAME or --all"));
    }
    Ok(())
}
