use std::collections::BTreeSet;

use deadlock_data::{Error, Result, SnapshotManifest, integer, object, real, text};
use deadlock_input::ItemGraph;
use serde_json::{Value, json};

use crate::ability_definition::parse_ability_definitions;
use crate::ability_reconstruction::reconstruct_ability_path;
use crate::beam_display::attach_beam_ability_names;
use crate::build_selection::select_hero_build;
use crate::guide_category::GuideCategory;
use crate::hero_evidence::HeroBuildEvidence;
use crate::policy_model::BuildPolicy;
use crate::policy_projection::{ProjectionIdentity, project_policy_to_guide};
use crate::policy_state::ValidationContext;
use crate::purchase_categories::build_purchase_categories;
use crate::purchase_guidance::build_purchase_guidance;
use crate::purchase_guide::PurchaseGuide;

/// # Errors
/// Returns an error when source identity, policy legality, canonical categories, or purchase guidance differs from the reviewed context.
pub fn reconstruct_guide(
    hero: &Value,
    policy: &BuildPolicy,
    evidence: &HeroBuildEvidence,
    manifest: &SnapshotManifest,
    assets: &[Value],
) -> Result<PurchaseGuide> {
    let identity = hero_identity(hero, policy, manifest)?;
    let kit = &hero["hero_mechanics"];
    object(kit)?;
    let ability = reconstruct_ability_path(hero, policy)?;
    let selected = select_hero_build(evidence, assets)?;
    let layout = PurchaseGuide::from_selected(
        &json!({"id":policy.content().hero_id,"name":identity.hero_name,"class_name":identity.hero_class_name}),
        &selected,
        Some(ability.clone()),
    )?;
    let validation = ValidationContext {
        item_graph: ItemGraph::from_assets(assets)?,
        ability_definitions: parse_ability_definitions(kit)?,
        level_info: kit["level_info"].clone(),
        learned_abilities: BTreeSet::new(),
    };
    let mut guide = project_policy_to_guide(policy, &validation, assets, &identity, Some(&layout))?;
    guide.ability_path = Some(ability);
    copy_build_identity(&mut guide, &hero["projection"]["build"])?;
    guide.analysis_start_timestamp =
        u64::try_from(manifest.content().epochs.analysis_start_timestamp())?;
    guide.as_of_timestamp = u64::try_from(manifest.content().as_of_timestamp)?;
    attach_beam_ability_names(&mut guide, kit);
    let mut guidance = build_purchase_guidance(&selected, assets)?;
    guidance.evidence = guide.evidence_summary.clone();
    guide.purchase_guidance = Some(guidance);
    guide.categories = build_purchase_categories(&guide)?;
    validate_canonical_projection(hero, &guide)?;
    Ok(guide)
}

fn hero_identity(
    hero: &Value,
    policy: &BuildPolicy,
    manifest: &SnapshotManifest,
) -> Result<ProjectionIdentity> {
    let content = policy.content();
    let name = text(hero, "hero")?.trim();
    let class = text(&hero["hero_mechanics"], "class_name")?.trim();
    if hero["hero_id"].as_u64() != Some(content.hero_id)
        || hero["path_id"] != content.path_id
        || hero["policy_id"] != policy.policy_id()
        || hero["snapshot_id"] != content.snapshot_id
        || name.is_empty()
        || class.is_empty()
    {
        return Err(Error::new("Hero context differs from its policy identity"));
    }
    Ok(ProjectionIdentity {
        hero_name: name.into(),
        hero_class_name: class.into(),
        client_version: manifest.content().client_version,
        match_mode: manifest.content().match_mode.as_str().into(),
        rank_identity: manifest
            .content()
            .rank_range
            .get("label")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .into(),
    })
}

fn copy_build_identity(guide: &mut PurchaseGuide, build: &Value) -> Result<()> {
    guide.build_tag_ids = serde_json::from_value(build["tag_ids"].clone())?;
    guide.build_tag_classes = serde_json::from_value(build["tag_classes"].clone())?;
    guide.build_tag_labels = serde_json::from_value(build["tag_labels"].clone())?;
    guide.build_tag_catalog_sha256 = text(build, "tag_catalog_sha256")?.into();
    guide.build_archetype = text(build, "archetype")?.trim().into();
    Ok(())
}

fn validate_canonical_projection(hero: &Value, guide: &PurchaseGuide) -> Result<()> {
    let projection = &hero["projection"];
    if projection["guide_version"].as_u64() != Some(3)
        || projection["categories"]
            != serde_json::to_value(
                guide
                    .rendered_categories()?
                    .iter()
                    .map(GuideCategory::record)
                    .collect::<Vec<_>>(),
            )?
        || hero["purchase_guidance"] != serde_json::to_value(&guide.purchase_guidance)?
    {
        return Err(Error::new(
            "Artifact categories or guidance differ from the canonical guide; refresh evidence and build again",
        ));
    }
    let core = &hero["core"];
    let matches = integer(core, "joint_player_matches")?;
    let share = real(core, "joint_share")?;
    let cost = integer(core, "core_target_cost")?;
    let median: Option<u64> = serde_json::from_value(core["median_final_net_worth"].clone())?;
    if matches == 0
        || !(0.0..=1.0).contains(&share)
        || share == 0.0
        || median == Some(0)
        || cost == 0
        || cost != guide.core_target_cost
    {
        return Err(Error::new(
            "Artifact core evidence or cost differs from its canonical guide",
        ));
    }
    Ok(())
}
