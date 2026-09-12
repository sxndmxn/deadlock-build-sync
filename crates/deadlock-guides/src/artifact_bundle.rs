use std::collections::BTreeSet;
use std::path::Path;

use deadlock_data::{ArtifactCoverage, Error, RankRange, Result, SnapshotManifest};
use deadlock_input::Patch;
use serde_json::Value;

use crate::bundle_evidence::validate_bundle_evidence;
use crate::context_validation::StrategyContext;
use crate::evidence_catalog::BuildEvidenceCatalog;
use crate::guide_groups::group_guides;
use crate::guide_reconstruction::reconstruct_guide;
use crate::narrative_catalog::NarrativeCatalog;
use crate::policy_artifact::PolicyArtifact;
use crate::purchase_guide::PurchaseGuide;

#[derive(Clone, Debug)]
pub struct ArtifactGuideBundle {
    pub guides: Vec<PurchaseGuide>,
    pub manifest: SnapshotManifest,
    pub patch: Patch,
    pub rank_range: RankRange,
    pub coverage: ArtifactCoverage,
}

/// # Errors
/// Returns an error when reviewed artifacts do not share exact identities, coverage, evidence, and canonical guide content.
pub fn load_artifact_guide_bundle(
    context_path: &Path,
    policy_path: &Path,
    narrative_path: &Path,
    evidence_path: &Path,
) -> Result<ArtifactGuideBundle> {
    let context = StrategyContext::load(context_path)?;
    let policies = PolicyArtifact::load(policy_path)?;
    let narratives = NarrativeCatalog::load(narrative_path)?;
    let evidence = BuildEvidenceCatalog::read(evidence_path)?;
    reconstruct_artifact_bundle(&context, &policies, &narratives, &evidence)
}

/// # Errors
/// Returns an error when an admitted artifact differs from the other source identities or the canonical guide projection.
pub fn reconstruct_artifact_bundle(
    context: &StrategyContext,
    policies: &PolicyArtifact,
    narratives: &NarrativeCatalog,
    evidence: &BuildEvidenceCatalog,
) -> Result<ArtifactGuideBundle> {
    validate_manifest(context, policies, narratives)?;
    let patch = validate_cohort(context, narratives)?;
    validate_bundle_evidence(evidence, context)?;
    let admitted = evidence
        .heroes()
        .values()
        .flat_map(|hero| &hero.builds)
        .map(|build| (build.hero_id, build.path_id.clone()))
        .collect::<BTreeSet<_>>();
    let context_keys = context.heroes().keys().cloned().collect::<BTreeSet<_>>();
    if admitted != context_keys || context_keys != policies.policies().keys().cloned().collect() {
        return Err(Error::new(
            "Artifact bundle does not contain every admitted build identity",
        ));
    }
    let mut guides = Vec::new();
    for (key, hero) in context.heroes() {
        let build = evidence
            .heroes()
            .get(&key.0)
            .into_iter()
            .flat_map(|hero| &hero.builds)
            .find(|build| build.path_id == key.1)
            .ok_or_else(|| Error::new("Build evidence has no matching path"))?;
        let policy = policies
            .policies()
            .get(key)
            .ok_or_else(|| Error::new("Artifact policy is absent"))?;
        let mut guide =
            reconstruct_guide(hero, policy, build, context.manifest(), evidence.assets())?;
        narratives.apply(&mut guide, hero, &patch)?;
        guides.push(guide);
    }
    let groups = evidence
        .heroes()
        .values()
        .flat_map(|hero| &hero.builds)
        .map(|build| {
            (
                (build.hero_id, build.path_id.clone()),
                build.guide_group_id.clone(),
            )
        })
        .collect();
    let ranks = RankRange::from_document(&context.manifest().content().rank_range.clone().into())?;
    Ok(ArtifactGuideBundle {
        guides: group_guides(guides, &groups)?,
        manifest: context.manifest().clone(),
        patch,
        rank_range: ranks,
        coverage: context.coverage().clone(),
    })
}

fn validate_manifest(
    context: &StrategyContext,
    policies: &PolicyArtifact,
    narratives: &NarrativeCatalog,
) -> Result<()> {
    if context.manifest().to_document()? != policies.manifest().to_document()?
        || narratives.snapshot_id() != context.manifest().identifier()
        || context.document()["source_context_sha256"] != narratives.source_context_sha256()
    {
        return Err(Error::new(
            "Artifact manifests or source context fingerprints differ",
        ));
    }
    if context.coverage() != policies.coverage() || context.coverage() != narratives.coverage() {
        return Err(Error::new("Artifact bundle coverage differs across files"));
    }
    Ok(())
}

fn validate_cohort(context: &StrategyContext, narratives: &NarrativeCatalog) -> Result<Patch> {
    let manifest = context.manifest().content();
    let patch = Patch::from_document(&context.document()["patch"])?;
    if context.document()["patch"] != Value::Object(manifest.patch.clone())
        || narratives.patch_identity() != patch.identity()?
        || narratives.game_mode() != "normal"
        || narratives.client_version() != manifest.client_version
        || narratives.match_mode() != manifest.match_mode.as_str()
    {
        return Err(Error::new(
            "Artifact patch or cohort differs from its snapshot",
        ));
    }
    if manifest
        .rank_range
        .get("labels_sha256")
        .and_then(Value::as_str)
        != Some(manifest.rank_labels_sha256.as_str())
        || manifest
            .rank_range
            .get("label")
            .and_then(Value::as_str)
            .is_none_or(|label| label.trim().is_empty())
    {
        return Err(Error::new("Artifact rank labels differ from its snapshot"));
    }
    Ok(patch)
}
