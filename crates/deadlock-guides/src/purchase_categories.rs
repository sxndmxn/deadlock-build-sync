use std::collections::BTreeMap;

use deadlock_data::{Error, Result};

use crate::guide_category::GuideCategory;
use crate::guide_item::{GuideItem, format_integer};
use crate::purchase_guidance_types::{PurchaseChoice, PurchaseGuidance};
use crate::purchase_guide::PurchaseGuide;
use crate::purchase_instructions::{
    format_choice_instruction, format_conditional_route, split_guidance,
};

/// # Errors
/// Returns an error when the category queue, item references, or automatic plans disagree with the canonical guide.
pub fn build_purchase_categories(guide: &PurchaseGuide) -> Result<Vec<GuideCategory>> {
    let guidance = guide
        .purchase_guidance
        .as_ref()
        .ok_or_else(|| Error::new("Purchase categories require a canonical guide"))?;
    let items = guide
        .tiers
        .values()
        .flatten()
        .map(|item| (item.item_id, item))
        .collect::<BTreeMap<_, _>>();
    let core = guide.core_path_items();
    if core.len() != guidance.default_path.actions.len() {
        return Err(Error::new(
            "Purchase category count differs from its canonical path",
        ));
    }
    let mut result = Vec::new();
    for checkpoint in 0..=core.len() {
        if checkpoint > 0 {
            let step = &guidance.default_path.actions[checkpoint - 1];
            let description = format!(
                "AUTO QUEUE | Buy step {checkpoint}. Cost: {} souls. Total: {} souls.",
                format_integer(i128::from(step.incremental_cost)),
                format_integer(i128::from(step.cumulative_cost))
            );
            result.push(GuideCategory::new(
                format!("CORE {checkpoint}"),
                vec![core[checkpoint - 1].clone()],
                description,
                false,
                false,
            )?);
        }
        for card in guidance
            .choices
            .iter()
            .filter(|card| card.after_step == Some(checkpoint))
        {
            result.extend(choice_categories(
                guidance,
                card,
                require_item(&items, card.item_id)?,
            )?);
        }
        result.extend(conditional_categories(guidance, checkpoint, &items)?);
    }
    for card in guidance
        .choices
        .iter()
        .filter(|card| card.after_step.is_none())
    {
        result.extend(choice_categories(
            guidance,
            card,
            require_item(&items, card.item_id)?,
        )?);
    }
    result.extend(core_alternative_categories(guide)?);
    result.extend(item_pool_categories(guide)?);
    let queued = result
        .iter()
        .filter(|category| !category.optional)
        .flat_map(|category| &category.items)
        .map(|item| item.item_id);
    if !queued.eq(guidance
        .default_path
        .actions
        .iter()
        .map(|step| step.item_id))
    {
        return Err(Error::new(
            "Steam Queue differs from the canonical component path",
        ));
    }
    Ok(result)
}

fn require_item<'items>(
    items: &BTreeMap<u64, &'items GuideItem>,
    id: u64,
) -> Result<&'items GuideItem> {
    items
        .get(&id)
        .copied()
        .ok_or_else(|| Error::new(format!("Purchase category references unknown item {id}")))
}

fn choice_categories(
    guidance: &PurchaseGuidance,
    card: &PurchaseChoice,
    item: &GuideItem,
) -> Result<Vec<GuideCategory>> {
    let decision = guidance
        .decisions
        .iter()
        .find(|decision| decision.options.contains(&card.item_id));
    let kind = decision.map_or_else(
        || {
            if card.route.len() > 1 {
                "UPGRADE"
            } else {
                "OPTIONAL"
            }
        },
        |decision| decision.kind.as_str(),
    );
    split_guidance(&format_choice_instruction(guidance, card)?)
        .into_iter()
        .enumerate()
        .map(|(index, part)| {
            let suffix = if index == 0 {
                String::new()
            } else {
                format!(" ({})", index + 1)
            };
            GuideCategory::new(
                format!("{kind} | {}{suffix}", card.name),
                vec![item.clone()],
                part,
                true,
                false,
            )
        })
        .collect()
}

fn conditional_categories(
    guidance: &PurchaseGuidance,
    checkpoint: usize,
    items: &BTreeMap<u64, &GuideItem>,
) -> Result<Vec<GuideCategory>> {
    let cards = guidance
        .choices
        .iter()
        .map(|card| (card.item_id, card))
        .collect::<BTreeMap<_, _>>();
    let mut result = Vec::new();
    for branch in guidance
        .automatic_branches
        .iter()
        .filter(|branch| branch.after_step == checkpoint)
    {
        let card = cards
            .get(&branch.item_id)
            .ok_or_else(|| Error::new("Automatic branch has no purchase choice"))?;
        let item = require_item(items, card.item_id)?;
        for part in split_guidance(&format_conditional_route(guidance, branch, card)?) {
            result.push(GuideCategory::new(
                "OPTIONAL | CONDITIONAL".into(),
                vec![item.clone()],
                part,
                true,
                false,
            )?);
        }
    }
    Ok(result)
}

fn core_alternative_categories(guide: &PurchaseGuide) -> Result<Vec<GuideCategory>> {
    let items = guide
        .optional_core_items
        .iter()
        .map(|item| (item.item_id, item))
        .collect::<BTreeMap<_, _>>();
    let mut result = Vec::new();
    for alternative in &guide.core_alternatives {
        let row = alternative.content();
        let item = require_item(&items, row.item_id)?;
        let instruction = format!("{} {}. {} {}", row.when, row.swap, row.why, row.skip);
        for part in split_guidance(&instruction) {
            result.push(GuideCategory::new(
                "OPTIONAL CORE".into(),
                vec![item.clone()],
                part,
                true,
                false,
            )?);
        }
    }
    Ok(result)
}

fn item_pool_categories(guide: &PurchaseGuide) -> Result<Vec<GuideCategory>> {
    (1..=4)
        .map(|tier| {
            let items = guide.tiers.get(&tier).cloned().unwrap_or_default();
            let description = if items.is_empty() {
                "No supported options are available."
            } else {
                "Optional items. These tiers are not a purchase order."
            };
            GuideCategory::new(
                format!("ITEM POOL | TIER {tier}"),
                items,
                description.into(),
                true,
                false,
            )
        })
        .collect()
}
