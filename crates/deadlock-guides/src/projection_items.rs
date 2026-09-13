use std::collections::BTreeMap;

use deadlock_data::{Error, Result};

use crate::guide_item::{GuideItem, conditional_item_annotation};
use crate::policy_node::{NodeKind, PolicyNode};

/// # Errors
/// Returns an error when the optional annotation does not contain five canonical decision lines.
pub fn validate_optional_annotation(annotation: &str) -> Result<()> {
    let labels = ["VS", "WHY", "SWAP", "WHEN", "SKIP"];
    let lines = annotation.lines().collect::<Vec<_>>();
    if lines.len() != labels.len() {
        return Err(Error::new(
            "Optional annotation must contain five decision lines",
        ));
    }
    let mut values = Vec::new();
    for (label, line) in labels.into_iter().zip(lines) {
        values.push(
            line.strip_prefix(&format!("{label}: ")).ok_or_else(|| {
                Error::new("Optional annotation labels are missing or out of order")
            })?,
        );
    }
    let values: [&str; 5] = values
        .try_into()
        .map_err(|_| Error::new("Optional annotation has an invalid field count"))?;
    if conditional_item_annotation(values)? != annotation {
        return Err(Error::new("Optional annotation is not in canonical form"));
    }
    Ok(())
}

pub fn apply_sell_priorities(items: &mut [GuideItem], nodes: &[PolicyNode]) -> Result<()> {
    let mut priorities = BTreeMap::new();
    for node in nodes.iter().filter(|node| node.kind == NodeKind::Sell) {
        if let Some(id) = node.item_id {
            let priority = u32::try_from(priorities.len())? + 1;
            priorities.entry(id).or_insert(priority);
        }
    }
    for item in items {
        item.sell_priority = priorities
            .get(&item.item_id)
            .copied()
            .or(item.sell_priority);
        item.annotation_text.clear();
    }
    Ok(())
}
