use std::collections::{BTreeMap, BTreeSet};

use crate::guide_item::{GuideItem, MAX_ITEM_ANNOTATION_BYTES};
use crate::purchase_guide::PurchaseGuide;

pub fn collect_variant_items(members: Vec<(&GuideItem, String)>) -> Vec<GuideItem> {
    let mut order = Vec::new();
    let mut grouped = BTreeMap::<u64, Vec<(&GuideItem, String)>>::new();
    for (item, scope) in members {
        if !grouped.contains_key(&item.item_id) {
            order.push(item.item_id);
        }
        grouped.entry(item.item_id).or_default().push((item, scope));
    }
    order
        .into_iter()
        .filter_map(|id| grouped.remove(&id))
        .filter_map(|rows| merge_item_scopes(&rows))
        .collect()
}

fn merge_item_scopes(rows: &[(&GuideItem, String)]) -> Option<GuideItem> {
    let (first, first_scope) = rows.first()?;
    let mut seen = BTreeSet::new();
    let scopes = rows
        .iter()
        .map(|(_, scope)| scope.as_str())
        .filter(|scope| seen.insert(*scope))
        .collect::<Vec<_>>()
        .join(", ");
    let targets = rows
        .iter()
        .map(|(item, _)| item.imbue_target_ability_id)
        .collect::<BTreeSet<_>>();
    let mut text = if targets.len() > 1 {
        format!("{scopes}. Imbue varies; use the selected variant's target.")
    } else {
        format!("{scopes}. Stats: {first_scope}.\n{}", first.annotation())
    };
    if text.len() > MAX_ITEM_ANNOTATION_BYTES {
        text = "Multiple variants; check the selected variant's full guide for scope, timing, and imbue target.".into();
    }
    let mut item = (*first).clone();
    item.annotation_text = text;
    if targets.len() > 1 {
        item.imbue_target_ability_id = None;
    }
    Some(item)
}

pub fn group_members(guide: &PurchaseGuide) -> impl Iterator<Item = &PurchaseGuide> {
    std::iter::once(guide).chain(&guide.variant_guides)
}

pub fn collect_conditional_items(guide: &PurchaseGuide) -> Vec<GuideItem> {
    let core = guide
        .core_path_items()
        .iter()
        .map(|item| item.item_id)
        .collect::<BTreeSet<_>>();
    let mut members = Vec::new();
    for (index, member) in group_members(guide).enumerate() {
        let scope = if index == 0 {
            "Conditional Default".into()
        } else {
            format!("Conditional V{index}")
        };
        members.extend(
            member
                .optional_core_items
                .iter()
                .filter(|item| !core.contains(&item.item_id))
                .map(|item| (item, scope.clone())),
        );
    }
    let optional = members
        .iter()
        .map(|(item, _)| item.item_id)
        .collect::<BTreeSet<_>>();
    for (index, member) in group_members(guide).enumerate() {
        let scope = if index == 0 {
            "Pool Default".into()
        } else {
            format!("Pool V{index}")
        };
        members.extend(
            member
                .tiers
                .values()
                .flatten()
                .filter(|item| optional.contains(&item.item_id))
                .map(|item| (item, scope.clone())),
        );
    }
    collect_variant_items(members)
}

pub fn collect_tier_items(
    guide: &PurchaseGuide,
    tier: u8,
    covered: &BTreeSet<u64>,
) -> Vec<GuideItem> {
    let mut members = Vec::new();
    for (index, member) in group_members(guide).enumerate() {
        let scope = if index == 0 {
            "Default".into()
        } else {
            format!("V{index}")
        };
        members.extend(
            member
                .tiers
                .get(&tier)
                .into_iter()
                .flatten()
                .filter(|item| !covered.contains(&item.item_id))
                .map(|item| (item, scope.clone())),
        );
    }
    for (index, member) in guide.variant_guides.iter().enumerate() {
        let mut excluded = covered.clone();
        excluded.extend(member.core_items.iter().map(|item| item.item_id));
        members.extend(
            member
                .core_purchase_items
                .iter()
                .filter(|item| item.tier == u64::from(tier) && !excluded.contains(&item.item_id))
                .map(|item| (item, format!("Component V{}", index + 1))),
        );
    }
    collect_variant_items(members)
}

pub fn collect_group_item_ids(guide: &PurchaseGuide) -> BTreeSet<u64> {
    group_members(guide)
        .flat_map(|member| {
            member
                .core_path_items()
                .iter()
                .chain(&member.optional_core_items)
                .chain(member.tiers.values().flatten())
        })
        .map(|item| item.item_id)
        .collect()
}
