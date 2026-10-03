use std::collections::BTreeSet;

use deadlock_data::Result;

use crate::guide_item::{GuideItem, MAX_ITEM_ANNOTATION_BYTES};
use crate::purchase_guide::PurchaseGuide;
use crate::purchase_instructions::{format_choice_instruction, split_guidance};

pub fn group_members(guide: &PurchaseGuide) -> impl Iterator<Item = &PurchaseGuide> {
    std::iter::once(guide).chain(&guide.variant_guides)
}

pub fn collect_tier_items(guide: &PurchaseGuide, tier: u8) -> Result<Vec<GuideItem>> {
    let mut result = Vec::<GuideItem>::new();
    let mut item_keys = BTreeSet::new();
    let mut instructions = BTreeSet::new();
    for (index, member) in group_members(guide).enumerate() {
        let scope = if index == 0 {
            "MAIN CORE".into()
        } else {
            format!("VARIANT {index}")
        };
        for item in member
            .optional_core_items
            .iter()
            .chain(member.tiers.values().flatten())
            .filter(|item| item.tier == u64::from(tier))
        {
            let key = (item.item_id, item.imbue_target_ability_id);
            if item_keys.insert(key) {
                result.push(annotate_scope(item, &scope));
            }
            for card in instruction_items(member, item, &scope)? {
                if instructions.insert((key, card.annotation_text.clone())) {
                    result.push(card);
                }
            }
        }
    }
    Ok(result)
}

fn annotate_scope(item: &GuideItem, scope: &str) -> GuideItem {
    let mut item = item.clone();
    let annotation = format!("Window: {scope}.\n{}", item.annotation());
    if annotation.len() <= MAX_ITEM_ANNOTATION_BYTES {
        item.annotation_text = annotation;
    }
    item
}

fn instruction_items(
    guide: &PurchaseGuide,
    item: &GuideItem,
    scope: &str,
) -> Result<Vec<GuideItem>> {
    let mut instructions = Vec::new();
    if let Some(guidance) = &guide.purchase_guidance {
        for card in guidance.choices.iter().filter(|card| {
            card.item_id == item.item_id
                && guidance
                    .automatic_branches
                    .iter()
                    .any(|branch| branch.item_id == card.item_id)
        }) {
            instructions.push(format_choice_instruction(guidance, card)?);
        }
    }
    for alternative in &guide.core_alternatives {
        let row = alternative.content();
        if row.item_id == item.item_id {
            instructions.push(format!(
                "{} {}. {} {}",
                row.when, row.swap, row.why, row.skip
            ));
        }
    }
    Ok(instructions
        .iter()
        .flat_map(|instruction| split_guidance(&format!("{scope}. {instruction}")))
        .map(|annotation| {
            let mut result = item.clone();
            result.annotation_text = annotation;
            result
        })
        .collect())
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
