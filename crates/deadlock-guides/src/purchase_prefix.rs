use deadlock_data::{Error, Result};

use crate::guide_item::{GuideItem, format_integer};
use crate::purchase_guide::PurchaseGuide;
use crate::purchase_plan_types::PurchaseStep;

pub fn purchase_steps(guide: &PurchaseGuide) -> Result<&[PurchaseStep]> {
    let actions = &guide
        .purchase_guidance
        .as_ref()
        .ok_or_else(|| Error::new("Display grouping requires purchase guidance"))?
        .default_path
        .actions;
    if actions.is_empty()
        || !actions
            .iter()
            .map(|step| step.item_id)
            .eq(guide.core_path_items().iter().map(|item| item.item_id))
    {
        return Err(Error::new(
            "Display purchases differ from the admitted path",
        ));
    }
    Ok(actions)
}

pub fn shared_prefix_length(alternatives: &[PurchaseGuide]) -> Result<usize> {
    let Some(first) = alternatives.first() else {
        return Ok(0);
    };
    let reference = purchase_steps(first)?;
    let mut length = reference.len().saturating_sub(1);
    for alternative in &alternatives[1..] {
        let steps = purchase_steps(alternative)?;
        let shared = reference
            .iter()
            .zip(steps)
            .zip(
                first
                    .core_path_items()
                    .iter()
                    .zip(alternative.core_path_items()),
            )
            .take_while(|((left, right), (left_item, right_item))| {
                left == right
                    && left_item.imbue_target_ability_id == right_item.imbue_target_ability_id
            })
            .count();
        length = length.min(shared).min(steps.len().saturating_sub(1));
    }
    Ok(length)
}

pub fn purchase_items(guide: &PurchaseGuide, scope: &str) -> Result<Vec<GuideItem>> {
    Ok(guide
        .core_path_items()
        .iter()
        .zip(purchase_steps(guide)?)
        .enumerate()
        .map(|(index, (item, step))| {
            let mut result = item.clone();
            let imbue = item
                .imbue_target_ability
                .as_ref()
                .map_or_else(String::new, |target| format!("\nIMBUE: {target}"));
            result.annotation_text = format!(
                "{scope}Step {}: +{} souls; total {}.\n{}{imbue}",
                index + 1,
                format_integer(i128::from(step.incremental_cost)),
                format_integer(i128::from(step.cumulative_cost)),
                item.annotation()
            );
            result
        })
        .collect())
}
