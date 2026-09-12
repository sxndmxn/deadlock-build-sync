use deadlock_data::{Error, Result, count_ratio};
use deadlock_input::ItemGraph;
use serde_json::{Value, json};

use crate::core_alternative::CoreAlternativeEvidence;
use crate::hero_evidence::HeroBuildEvidence;
use crate::item_evidence::ItemEvidence;
use crate::selected_build::SelectedHeroBuild;
use crate::selection_paths::{
    ItemEvidenceIndex, expand_component_path, validate_component_path, validate_selected_path,
    validate_situational_paths, validate_substitution_paths,
};
use crate::selection_tiers::select_tiers;

/// # Errors
/// Returns an error when current assets, purchase paths, replacements, or tier membership disagree with admitted evidence.
pub fn select_hero_build(
    evidence: &HeroBuildEvidence,
    assets: &[Value],
) -> Result<SelectedHeroBuild> {
    let graph = ItemGraph::from_assets(assets)?;
    let items = evidence
        .items
        .iter()
        .map(|item| (item.content().item_id, item))
        .collect::<ItemEvidenceIndex<'_>>();
    validate_item_assets(evidence, &graph)?;
    let policy = evidence.core_policy.content();
    let scheduled = expand_component_path(&graph, &policy.default_item_ids, &items)?;
    validate_component_path(&graph, &items, &scheduled, &policy.default_item_ids)?;
    validate_situational_paths(&graph, evidence, &items)?;
    validate_selected_path(&graph, evidence, &items)?;
    let tiers = select_tiers(&graph, evidence, &items)?;
    validate_substitution_paths(
        &graph,
        &evidence.automatic_branches,
        &policy.default_item_ids,
    )?;
    let mut alternatives = policy
        .alternatives
        .iter()
        .map(CoreAlternativeEvidence::content)
        .collect::<Vec<_>>();
    alternatives.sort_by_key(|row| (row.stage, row.item_id));
    let optional = alternatives
        .iter()
        .map(|row| row.item_id)
        .collect::<Vec<_>>();
    let core_target_cost = policy.default_item_ids.iter().try_fold(0_u64, |cost, id| {
        cost.checked_add(graph.require(*id)?.cost)
            .ok_or_else(|| Error::new("Core cost exceeds 64 bits"))
    })?;
    Ok(SelectedHeroBuild {
        hero_id: evidence.hero_id,
        path_id: evidence.path_id.clone(),
        path_label: evidence.path_label.clone(),
        signature_item_ids: evidence.signature_item_ids.clone(),
        core: select_items(&items, &policy.default_item_ids)?,
        core_purchase_path: select_items(&items, &evidence.sequence_policy.content().default_path)?,
        tiers,
        backbone: select_items(&items, &policy.backbone_item_ids)?,
        optional_core: select_items(&items, &optional)?,
        core_alternatives: policy.alternatives.clone(),
        backbone_matches: policy.backbone_matches,
        backbone_share: count_ratio(
            policy.backbone_matches,
            evidence.selection_eligible_player_matches,
        )?,
        core_joint_matches: policy.default_matches,
        core_joint_share: count_ratio(
            policy.default_matches,
            evidence.selection_eligible_player_matches,
        )?,
        median_final_net_worth: evidence.median_final_net_worth,
        core_target_cost,
        evidence_summary: summarize_evidence(evidence),
        purchase_timing: evidence.purchase_timing.clone(),
        automatic_branches: evidence.automatic_branches.clone(),
        cohort: evidence.cohort.clone(),
    })
}

fn validate_item_assets(evidence: &HeroBuildEvidence, graph: &ItemGraph) -> Result<()> {
    for item in &evidence.items {
        let item = item.content();
        let asset = graph.require(item.item_id)?;
        if asset.name != item.item
            || u64::from(asset.tier) != item.tier
            || asset.cost != item.cost
            || asset.slot != item.slot
            || asset.active != item.active
        {
            return Err(Error::new(format!(
                "Hero {} item {} conflicts with current assets",
                evidence.hero_id, item.item_id
            )));
        }
    }
    Ok(())
}

fn select_items(items: &ItemEvidenceIndex<'_>, ids: &[u64]) -> Result<Vec<ItemEvidence>> {
    ids.iter()
        .map(|id| {
            items
                .get(id)
                .map(|item| (*item).clone())
                .ok_or_else(|| Error::new(format!("Selected item {id} has no evidence")))
        })
        .collect()
}

fn summarize_evidence(evidence: &HeroBuildEvidence) -> Value {
    let discovery = &evidence.discovery;
    let mut summary = json!({
        "status": discovery.get("evidence_status").cloned().unwrap_or_else(|| "observed".into()),
        "limitations": discovery.get("evidence_limitations").cloned().unwrap_or_else(|| json!([])),
        "discovery_owners": discovery["discovery_support"],
        "selection_owners": discovery["selection"]["owners"],
        "validation_owners": discovery["validation"]["owners"],
        "timing_status": discovery["frozen_guide"].get("timing_status").cloned().unwrap_or_else(|| "uncertain".into()),
    });
    if let Some(generator) = &evidence.generator {
        summary["generator"] = generator.document().clone();
    }
    summary
}
