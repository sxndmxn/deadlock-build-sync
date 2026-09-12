use deadlock_data::{Error, Result, SnapshotManifest};
use deadlock_guides::{
    BuildPolicy, HeroContextInputs, PolicyInputs, ProjectionIdentity, PurchaseGuide,
    attach_beam_ability_names, build_hero_strategy_context, build_purchase_categories,
    build_purchase_guidance, generate_policy, project_policy_to_guide, select_build_tags,
};
use deadlock_input::BuildTagCatalog;
use serde_json::Value;

use crate::generation_types::HeroInputs;

pub fn project_hero(
    inputs: &HeroInputs,
    assets: &[Value],
    manifest: &SnapshotManifest,
    tags: &BuildTagCatalog,
) -> Result<(PurchaseGuide, BuildPolicy, Value)> {
    let policy_inputs = PolicyInputs {
        guide: &inputs.guide,
        kit: &inputs.kit,
        timeline: &inputs.timeline,
        duration: &inputs.duration,
        situational: Some(&inputs.situational),
    };
    let (policy, validation) = generate_policy(&policy_inputs, assets, manifest)?;
    let identity = ProjectionIdentity {
        hero_name: inputs.guide.hero_name.clone(),
        hero_class_name: inputs.guide.hero_class_name.clone(),
        client_version: manifest.content().client_version,
        match_mode: manifest.content().match_mode.as_str().into(),
        rank_identity: manifest.rank_identity()?,
    };
    let mut projected =
        project_policy_to_guide(&policy, &validation, assets, &identity, Some(&inputs.guide))?;
    projected
        .ability_path
        .clone_from(&inputs.guide.ability_path);
    attach_beam_ability_names(&mut projected, &inputs.kit);
    let mut guidance = build_purchase_guidance(&inputs.selected, assets)?;
    guidance.evidence = projected.evidence_summary.clone();
    projected.purchase_guidance = Some(guidance);
    projected.categories = build_purchase_categories(&projected)?;
    attach_tags(&mut projected, assets, tags)?;
    attach_run_identity(&mut projected, manifest)?;
    let mut analytic = inputs.guide.clone();
    analytic.snapshot_id = manifest.identifier().into();
    analytic.policy_id = policy.policy_id().into();
    analytic.client_version = Some(identity.client_version);
    analytic.match_mode = identity.match_mode;
    analytic.rank_identity.clone_from(&projected.rank_identity);
    attach_run_identity(&mut analytic, manifest)?;
    let context = build_hero_strategy_context(
        &HeroContextInputs {
            guide: &analytic,
            kit: &inputs.kit,
            timeline: &inputs.timeline,
            duration: &inputs.duration,
            distribution: Some(&inputs.distribution),
            policy: Some(&policy),
            projection: Some(&projected),
            matchups: Some(&inputs.matchups),
        },
        assets,
    )?;
    Ok((projected, policy, context))
}

fn attach_run_identity(guide: &mut PurchaseGuide, manifest: &SnapshotManifest) -> Result<()> {
    guide.analysis_start_timestamp =
        u64::try_from(manifest.content().epochs.analysis_start_timestamp())?;
    guide.as_of_timestamp = u64::try_from(manifest.content().as_of_timestamp)?;
    Ok(())
}

fn attach_tags(guide: &mut PurchaseGuide, assets: &[Value], tags: &BuildTagCatalog) -> Result<()> {
    let ability = guide
        .ability_path
        .as_ref()
        .ok_or_else(|| Error::new("Guide has no complete ability path"))?;
    let selected = select_build_tags(&ability.ability_ids, &guide.core_items, assets, tags)?;
    guide.build_tag_ids = selected.tag_ids.into();
    guide.build_tag_classes = selected.class_names.into();
    guide.build_tag_labels = selected.labels.into();
    guide.build_tag_catalog_sha256 = tags.sha256().into();
    guide.build_archetype = selected.archetype;
    Ok(())
}
