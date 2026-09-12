use std::collections::BTreeMap;

use deadlock_data::{Error, Result};
use serde_json::Value;

use crate::guide_item::{GuideItem, conditional_item_annotation};
use crate::policy_guard::PolicyBranch;
use crate::policy_model::BuildPolicy;
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

pub fn build_guide_item(
    node: &PolicyNode,
    assets: &BTreeMap<u64, &Value>,
    policy: &BuildPolicy,
    optional: bool,
) -> Result<GuideItem> {
    let id = node
        .item_id
        .ok_or_else(|| Error::new("Purchase node has no item"))?;
    let asset = assets
        .get(&id)
        .ok_or_else(|| Error::new("Purchase node references a missing asset"))?;
    let claim = policy
        .content()
        .evidence
        .iter()
        .find(|claim| Some(claim.claim_id.as_str()) == node.evidence_ref.as_deref())
        .ok_or_else(|| Error::new("Purchase node has no current evidence"))?;
    if optional {
        validate_optional_annotation(node.annotation.trim())?;
    }
    let tier = asset
        .get("item_tier")
        .filter(|value| !value.is_null())
        .map_or(Ok(0), |value| {
            value
                .as_u64()
                .ok_or_else(|| Error::new("Item tier must be a nonnegative integer"))
        })?;
    Ok(GuideItem {
        item_id: id,
        name: asset["name"]
            .as_str()
            .filter(|name| !name.is_empty())
            .map_or_else(|| format!("Item {id}"), str::to_owned),
        tier,
        purchase_event_observations: claim.support,
        observed_outcome_rate: claim.estimate.unwrap_or(0.0),
        observed_outcome_lower_bound: claim.interval.map_or(0.0, |interval| interval[0]),
        required_flex_slots: (node.required_flex_slots > 0)
            .then_some(u32::from(node.required_flex_slots)),
        sell_priority: node.sell_priority,
        imbue_target_ability_id: node.imbue_target_ability_id,
        ..GuideItem::default()
    })
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

pub fn format_branch_label(branch: &PolicyBranch) -> String {
    let Some(first) = branch.guards().first() else {
        return "DEFAULT".into();
    };
    let values = branch
        .guards()
        .iter()
        .filter(|guard| !guard.value.is_null())
        .map(|guard| {
            guard
                .value
                .as_str()
                .map_or_else(|| guard.value.to_string(), str::to_owned)
                .replace('_', " ")
                .to_uppercase()
        })
        .collect::<Vec<_>>();
    let label = if values.is_empty() {
        first.field.to_uppercase()
    } else {
        values.join(" + ")
    };
    format!("IF {label}").chars().take(48).collect()
}
