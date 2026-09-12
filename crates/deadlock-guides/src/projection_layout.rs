use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};

use crate::guide_category::{
    CORE_CATEGORY_DESCRIPTION, GuideCategory, OPTIONAL_CORE_CATEGORY_DESCRIPTION,
};
use crate::guide_item::{GuideItem, format_integer};
use crate::policy_model::BuildPolicy;
use crate::policy_node::{NodeKind, PolicyNode};
use crate::projection_items::{apply_sell_priorities, validate_optional_annotation};
use crate::purchase_guide::PurchaseGuide;

pub fn project_evidence_layout(
    policy: &BuildPolicy,
    layout: &PurchaseGuide,
    path: &[&PolicyNode],
) -> Result<PurchaseGuide> {
    let ids = layout
        .core_items
        .iter()
        .map(|item| item.item_id)
        .collect::<Vec<_>>();
    let policy_ids = path
        .iter()
        .filter(|node| node.kind == NodeKind::Purchase)
        .filter_map(|node| node.item_id)
        .collect::<Vec<_>>();
    if !(3..=9).contains(&ids.len()) || ids != policy_ids {
        return Err(Error::new(
            "Policy default path does not match the supported evidence core",
        ));
    }
    let mut guide = layout.clone();
    guide.core_purchase_items = layout.core_path_items().into();
    let core = guide
        .core_purchase_items
        .iter()
        .map(|item| item.item_id)
        .collect::<BTreeSet<_>>();
    let tiers = project_tiers(policy, &mut guide, &core)?;
    project_optional_core(policy, &mut guide.optional_core_items, &core, &tiers)?;
    apply_sell_priorities(&mut guide.core_items, &policy.content().nodes)?;
    apply_sell_priorities(&mut guide.core_purchase_items, &policy.content().nodes)?;
    guide.categories = vec![GuideCategory::new(
        "CORE ITEMS".into(),
        guide.core_purchase_items.clone(),
        CORE_CATEGORY_DESCRIPTION.into(),
        false,
        false,
    )?];
    if !guide.optional_core_items.is_empty() {
        guide.categories.push(GuideCategory::new(
            "OPTIONAL CORE".into(),
            guide.optional_core_items.clone(),
            OPTIONAL_CORE_CATEGORY_DESCRIPTION.into(),
            true,
            false,
        )?);
    }
    for tier in 1..=4 {
        let items = guide
            .tiers
            .get(&tier)
            .ok_or_else(|| Error::new("Evidence projection is missing a tier"))?;
        guide.categories.push(GuideCategory::new(
            format!("TIER {tier}"),
            items.clone(),
            String::new(),
            true,
            false,
        )?);
    }
    guide.summary = format!(
        "{}; supported {}-item backbone observed in {} player-matches ({:.2}%). OPTIONAL CORE and tier rows never enter the automatic Queue.",
        policy.content().strategic_role,
        layout.backbone_items.len(),
        format_integer(i128::from(layout.backbone_matches)),
        layout.backbone_share * 100.0
    );
    guide.ability_path = None;
    guide.purchase_guidance = None;
    guide.tactical_profile = None;
    guide.tier_summaries.clear();
    guide.variant_guides.clear();
    Ok(guide)
}

fn project_tiers(
    policy: &BuildPolicy,
    guide: &mut PurchaseGuide,
    core: &BTreeSet<u64>,
) -> Result<BTreeSet<u64>> {
    if (1..=4).any(|tier| guide.tiers.get(&tier).is_none_or(|items| items.len() > 10)) {
        return Err(Error::new(
            "Evidence projection requires all four tier pools with at most ten items each",
        ));
    }
    let tier_ids = guide
        .tiers
        .values()
        .flatten()
        .map(|item| item.item_id)
        .collect::<BTreeSet<_>>();
    if !core.is_disjoint(&tier_ids) {
        return Err(Error::new(
            "Evidence tier menus must not repeat core path items",
        ));
    }
    let mut conditional = BTreeMap::new();
    for node in policy
        .content()
        .nodes
        .iter()
        .filter(|node| node.kind == NodeKind::Purchase && node.optional)
    {
        let id = node
            .item_id
            .ok_or_else(|| Error::new("Optional purchase node has no item"))?;
        validate_optional_annotation(&node.annotation)?;
        if conditional.insert(id, node).is_some() || !tier_ids.contains(&id) {
            return Err(Error::new(
                "Conditional purchase repeats an item or references an item outside the tier menus",
            ));
        }
    }
    for item in guide.tiers.values_mut().flatten() {
        if let Some(node) = conditional.get(&item.item_id) {
            item.required_flex_slots =
                (node.required_flex_slots > 0).then_some(u32::from(node.required_flex_slots));
            item.sell_priority = node.sell_priority;
            item.imbue_target_ability_id = node
                .imbue_target_ability_id
                .or(item.imbue_target_ability_id);
            item.annotation_text.clear();
        }
    }
    Ok(tier_ids)
}

fn project_optional_core(
    policy: &BuildPolicy,
    items: &mut [GuideItem],
    core: &BTreeSet<u64>,
    tiers: &BTreeSet<u64>,
) -> Result<()> {
    let ids = items
        .iter()
        .map(|item| item.item_id)
        .collect::<BTreeSet<_>>();
    let cards = policy
        .content()
        .core_alternatives
        .iter()
        .map(|card| card.item_id)
        .collect();
    if ids != cards {
        return Err(Error::new(
            "Optional core evidence does not match the admitted policy cards",
        ));
    }
    if !ids.is_disjoint(core) || !ids.is_disjoint(tiers) {
        return Err(Error::new(
            "Optional core items must be separate from core and tiers",
        ));
    }
    for item in items {
        item.required_flex_slots = None;
        item.sell_priority = None;
        item.annotation_text.clear();
    }
    Ok(())
}
