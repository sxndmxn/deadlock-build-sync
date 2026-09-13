use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use serde_json::{Value, json};

use crate::hero_cohort::HeroCohort;
use crate::purchase_guide::PurchaseGuide;
use crate::variant_categories::{build_compact_categories, validate_group_categories};
use crate::variant_items::group_members;

pub type GuideGroupIndex = BTreeMap<(u64, String), String>;
pub const VARIANT_RULE: &str = "Choose MAIN CORE or ALT CORE followed by one complete VARIANT. Queue follows MAIN CORE only. Keep the selected path and its optional items together. Core changes require admitted substitution evidence.";

/// # Errors
/// Returns an error when groups omit or repeat admitted paths or contain invalid purchases.
pub fn group_guides(
    guides: Vec<PurchaseGuide>,
    groups: &GuideGroupIndex,
) -> Result<Vec<PurchaseGuide>> {
    let heroes = guides
        .iter()
        .map(|guide| guide.hero_id)
        .collect::<BTreeSet<_>>();
    let mut present = BTreeSet::new();
    let mut by_group = BTreeMap::<(u64, String, u64, Option<u64>), Vec<PurchaseGuide>>::new();
    let mut order = Vec::new();
    for mut guide in guides {
        if !guide.variant_guides.is_empty()
            || !present.insert((guide.hero_id, guide.path_id.clone()))
        {
            return Err(Error::new(
                "Display grouping requires distinct ungrouped paths",
            ));
        }
        crate::purchase_prefix::purchase_steps(&guide)?;
        let first = &guide.core_path_items()[0];
        let source = groups
            .get(&(guide.hero_id, guide.path_id.clone()))
            .unwrap_or(&guide.path_id)
            .clone();
        let key = (
            guide.hero_id,
            source.clone(),
            first.item_id,
            first.imbue_target_ability_id,
        );
        guide.source_group_id = source;
        if !by_group.contains_key(&key) {
            order.push(key.clone());
        }
        by_group.entry(key).or_default().push(guide);
    }
    let expected = groups
        .keys()
        .filter(|(hero, _)| heroes.contains(hero))
        .cloned()
        .collect();
    if !groups.is_empty() && present != expected {
        return Err(Error::new("Guide groups do not cover every supported path"));
    }
    let mut result = Vec::new();
    for key in order {
        let members = by_group
            .remove(&key)
            .ok_or_else(|| Error::new("Guide group has no members"))?;
        result.extend(combine_guides(members)?);
    }
    Ok(result)
}

fn combine_guides(mut members: Vec<PurchaseGuide>) -> Result<Vec<PurchaseGuide>> {
    members.sort_by_key(|member| member.selection_rank);
    let mut members = members.into_iter();
    let mut main = members
        .next()
        .ok_or_else(|| Error::new("Guide group has no default"))?;
    let mut standalone = Vec::new();
    for member in members {
        if member.core_path_items().len() < 2 {
            standalone.push(member);
        } else {
            main.variant_guides.push(member);
        }
    }
    if crate::purchase_prefix::shared_prefix_length(&main.variant_guides)? == 0 {
        standalone.append(&mut main.variant_guides);
    }
    let mut result = vec![main];
    result.extend(standalone);
    result.sort_by_key(|guide| guide.selection_rank);
    for guide in &mut result {
        guide.categories = build_compact_categories(guide)?;
        validate_group_categories(guide)?;
    }
    Ok(result)
}

/// # Errors
/// Returns an error when cohort or purchase guidance serialization fails.
pub fn build_variant_record(guide: &PurchaseGuide) -> Result<Value> {
    let result = json!({
        "path_id": guide.path_id, "policy_id": guide.policy_id,
        "selection_rank": guide.selection_rank,
        "core": guide.core_items.iter().map(|item| item.item_id).collect::<Vec<_>>(),
        "core_cost": guide.core_target_cost, "evidence": guide.evidence_summary,
        "cohort": guide.cohort.as_ref().map(HeroCohort::to_document).transpose()?.unwrap_or_else(|| json!({})),
        "purchase_guidance": guide.purchase_guidance,
        "item_pool": guide.tiers.iter().map(|(tier, items)| (tier.to_string(), items.iter().map(|item| item.item_id).collect::<Vec<_>>())).collect::<BTreeMap<_, _>>(),
        "ability_order": guide.ability_path.as_ref().map(|path| path.ability_ids.clone()).unwrap_or_default(),
    });
    Ok(result)
}

/// # Errors
/// Returns an error when a variant record cannot be serialized.
pub fn build_group_record(guide: &PurchaseGuide) -> Result<Value> {
    let variants = group_members(guide)
        .map(build_variant_record)
        .collect::<Result<Vec<_>>>()?;
    Ok(
        json!({"schema_version":2, "group_id":guide.path_id, "source_group_id":guide.source_group_id,
            "default_path_id":guide.path_id, "shared_prefix_length":crate::purchase_prefix::shared_prefix_length(&guide.variant_guides)?, "variants":variants}),
    )
}

#[must_use]
pub fn describe_variant_changes(default: &PurchaseGuide, variant: &PurchaseGuide) -> String {
    let original = default
        .core_items
        .iter()
        .map(|item| item.item_id)
        .collect::<BTreeSet<_>>();
    let selected = variant
        .core_items
        .iter()
        .map(|item| item.item_id)
        .collect::<BTreeSet<_>>();
    let added = variant
        .core_items
        .iter()
        .filter(|item| !original.contains(&item.item_id))
        .map(|item| item.name.as_str())
        .collect::<Vec<_>>()
        .join(", ");
    let removed = default
        .core_items
        .iter()
        .filter(|item| !selected.contains(&item.item_id))
        .map(|item| item.name.as_str())
        .collect::<Vec<_>>()
        .join(", ");
    let mut parts = Vec::new();
    if !added.is_empty() {
        parts.push(format!("Use {added}"));
    }
    if !removed.is_empty() {
        parts.push(format!("omit {removed}"));
    }
    if parts.is_empty() {
        "Default core".into()
    } else {
        parts.join("; ")
    }
}
