use std::fmt::Write as _;

use deadlock_data::{Error, Result};

use crate::automatic_branch::{AutomaticBranch, AutomaticCondition, BranchTrigger};
use crate::guide_category::MAX_CATEGORY_DESCRIPTION_BYTES;
use crate::guide_item::format_integer;
use crate::purchase_guidance_types::{PurchaseChoice, PurchaseGuidance};

#[must_use]
pub fn split_guidance(mut text: &str) -> Vec<String> {
    let mut result = Vec::new();
    while !text.is_empty() {
        let mut end = text.floor_char_boundary(MAX_CATEGORY_DESCRIPTION_BYTES.min(text.len()));
        if end < text.len()
            && let Some(boundary) = text[..end].rfind(' ').filter(|boundary| *boundary > 0)
        {
            end = boundary + 1;
        }
        let (part, remaining) = text.split_at(end);
        result.push(part.into());
        text = remaining;
    }
    result
}

pub fn item_names(guidance: &PurchaseGuidance, ids: &[u64], separator: &str) -> Result<String> {
    ids.iter()
        .map(|id| {
            guidance.names.get(id).map(String::as_str).ok_or_else(|| {
                Error::new(format!("Purchase instruction has no name for item {id}"))
            })
        })
        .collect::<Result<Vec<_>>>()
        .map(|names| names.join(separator))
}

/// # Errors
/// Returns an error when a purchase route references an item without a name.
pub fn format_choice_instruction(
    guidance: &PurchaseGuidance,
    card: &PurchaseChoice,
) -> Result<String> {
    let route = item_names(guidance, &card.route, " -> ")?;
    let Some(position) = card.after_step else {
        return Ok(format!(
            "{}. Timing unknown. Route: {route}. Catalog cost: {} souls. Select a checkpoint before purchase.",
            card.purpose.trigger,
            format_integer(i128::from(card.catalog_cost))
        ));
    };
    let resume = guidance
        .default_path
        .actions
        .get(position)
        .map_or("core complete", |step| step.name.as_str());
    let cost = card.extra_path_cost.map_or_else(
        || "Cost unavailable.".into(),
        |cost| format!("Extra cost: {} souls.", format_integer(cost)),
    );
    let mut instruction = format!(
        "{}. After core step {position}. Route: {route}. {cost} Resume: {resume}.",
        card.purpose.trigger
    );
    if !card.rebought_components.is_empty() {
        write!(
            instruction,
            " Rebuy: {}.",
            item_names(guidance, &card.rebought_components, ", ")?
        )?;
    }
    if let Some(reason) = &card.blocked_reason {
        write!(instruction, " Blocked: {reason}.")?;
    }
    for branch in guidance
        .automatic_branches
        .iter()
        .filter(|branch| branch.item_id == card.item_id)
    {
        instruction.push_str(&format_branch_instruction(guidance, branch)?);
    }
    Ok(instruction)
}

pub fn format_branch_instruction(
    guidance: &PurchaseGuidance,
    branch: &AutomaticBranch,
) -> Result<String> {
    let value = match &branch.value {
        BranchTrigger::Name(name) => name.clone(),
        BranchTrigger::Identifier(id) => id.to_string(),
    };
    let condition = match branch.condition {
        AutomaticCondition::RelativeWealth => format!(
            "wealth is {value} (personal net worth / lobby mean; behind <0.90, ahead >1.10)"
        ),
        AutomaticCondition::EnemyHero => format!("enemy hero {value} is present"),
        AutomaticCondition::EnemyItem => {
            let name = match branch.value {
                BranchTrigger::Identifier(id) => guidance.names.get(&id),
                BranchTrigger::Name(_) => None,
            };
            format!("enemy owns {}", name.unwrap_or(&value))
        }
    };
    let mut instruction = format!(
        " IF {condition}, choose this item after step {}.",
        branch.after_step
    );
    if !branch.substituted_core.is_empty() {
        write!(
            instruction,
            " Replace {}; use its separately validated core path.",
            item_names(guidance, &[branch.comparator_item_id], "")?
        )?;
    }
    Ok(instruction)
}

pub fn format_conditional_route(
    guidance: &PurchaseGuidance,
    branch: &AutomaticBranch,
    card: &PurchaseChoice,
) -> Result<String> {
    let plan = branch
        .default_plan
        .as_ref()
        .ok_or_else(|| Error::new("Automatic branch has no canonical purchase plan"))?;
    let route = item_names(guidance, &card.route, " -> ")?;
    let resume_at = branch.after_step + usize::from(!branch.substituted_core.is_empty());
    let resume = guidance
        .default_path
        .actions
        .get(resume_at)
        .map_or("core complete", |step| step.name.as_str());
    let extra = i128::from(plan.remaining_cost) - i128::from(guidance.default_path.remaining_cost);
    Ok(format!(
        "{} Route: {route}. Extra cost: {} souls. Resume: {resume}.",
        format_branch_instruction(guidance, branch)?,
        format_integer(extra)
    ))
}
