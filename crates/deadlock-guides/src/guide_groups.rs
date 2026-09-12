use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use serde_json::{Value, json};

use crate::beam_display::generator_metadata;
use crate::hero_cohort::HeroCohort;
use crate::purchase_guide::PurchaseGuide;
use crate::variant_categories::{build_compact_categories, validate_group_categories};
use crate::variant_items::group_members;

pub type GuideGroupIndex = BTreeMap<(u64, String), String>;
pub const VARIANT_RULE: &str = "Choose CORE ITEMS or one complete variant before purchase. Queue follows CORE ITEMS only. Use the selected variant's order and item pool. Core changes during a match still require admitted substitution evidence.";

/// # Errors
/// Returns an error when the group omits an admitted path, lacks its default, or has invalid category coverage.
pub fn group_guides(
    guides: Vec<PurchaseGuide>,
    groups: &GuideGroupIndex,
) -> Result<Vec<PurchaseGuide>> {
    let heroes = guides
        .iter()
        .map(|guide| guide.hero_id)
        .collect::<BTreeSet<_>>();
    let present = guides
        .iter()
        .flat_map(|guide| {
            group_members(guide).map(|member| (guide.hero_id, member.path_id.clone()))
        })
        .collect::<BTreeSet<_>>();
    let expected = groups
        .keys()
        .filter(|(hero, _)| heroes.contains(hero))
        .cloned()
        .collect();
    if !groups.is_empty() && present != expected {
        return Err(Error::new(
            "Guide groups do not cover every supported variant",
        ));
    }
    let mut order = Vec::new();
    let mut by_group = BTreeMap::<(u64, String), Vec<PurchaseGuide>>::new();
    for guide in guides {
        let identity = (guide.hero_id, guide.path_id.clone());
        let key = (
            guide.hero_id,
            groups.get(&identity).unwrap_or(&guide.path_id).clone(),
        );
        if !by_group.contains_key(&key) {
            order.push(key.clone());
        }
        by_group.entry(key).or_default().push(guide);
    }
    order
        .into_iter()
        .map(|key| {
            let members = by_group
                .remove(&key)
                .ok_or_else(|| Error::new("Guide group has no members"))?;
            combine_guides(members, &key.1)
        })
        .collect()
}

fn combine_guides(mut members: Vec<PurchaseGuide>, group_id: &str) -> Result<PurchaseGuide> {
    let index = members
        .iter()
        .position(|member| member.path_id == group_id)
        .ok_or_else(|| Error::new("Guide group has no supported default"))?;
    let mut default = members.remove(index);
    if !members.is_empty() {
        let mut counts = BTreeMap::<u64, usize>::new();
        let mut names = BTreeMap::new();
        for item in std::iter::once(&default)
            .chain(&members)
            .flat_map(|member| &member.core_items)
        {
            *counts.entry(item.item_id).or_default() += 1;
            names.insert(item.item_id, item.name.clone());
        }
        let mut ids = counts.keys().copied().collect::<Vec<_>>();
        ids.sort_by_key(|id| (std::cmp::Reverse(counts[id]), *id));
        let label = ids
            .iter()
            .take(2)
            .map(|id| names[id].as_str())
            .collect::<Vec<_>>()
            .join(" / ");
        members.sort_by(|left, right| left.path_id.cmp(&right.path_id));
        default.variant_guides = members;
        default.path_label.clone_from(&label);
        default.build_archetype = label;
    }
    default.categories = build_compact_categories(&default)?;
    validate_group_categories(&default)?;
    Ok(default)
}

/// # Errors
/// Returns an error when cohort or purchase guidance serialization fails.
pub fn build_variant_record(guide: &PurchaseGuide) -> Result<Value> {
    let mut result = json!({
        "path_id": guide.path_id, "policy_id": guide.policy_id,
        "core": guide.core_items.iter().map(|item| item.item_id).collect::<Vec<_>>(),
        "core_cost": guide.core_target_cost, "evidence": guide.evidence_summary,
        "cohort": guide.cohort.as_ref().map(HeroCohort::to_document).transpose()?.unwrap_or_else(|| json!({})),
        "purchase_guidance": guide.purchase_guidance,
        "item_pool": guide.tiers.iter().map(|(tier, items)| (tier.to_string(), items.iter().map(|item| item.item_id).collect::<Vec<_>>())).collect::<BTreeMap<_, _>>(),
        "ability_order": guide.ability_path.as_ref().map(|path| path.ability_ids.clone()).unwrap_or_default(),
    });
    if let Some(generator) = generator_metadata(guide) {
        result["generator"] = generator.clone();
    }
    Ok(result)
}

/// # Errors
/// Returns an error when a variant record cannot be serialized.
pub fn build_group_record(guide: &PurchaseGuide) -> Result<Value> {
    let variants = group_members(guide)
        .map(build_variant_record)
        .collect::<Result<Vec<_>>>()?;
    Ok(
        json!({"schema_version":1, "group_id":guide.path_id, "default_path_id":guide.path_id, "variants":variants}),
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
