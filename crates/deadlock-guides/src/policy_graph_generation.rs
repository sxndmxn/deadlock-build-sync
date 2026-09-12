use std::collections::BTreeMap;

use deadlock_data::{Error, Result};

use crate::ability_timeline::AbilityTimelineStep;
use crate::policy_guard::{BranchCondition, DefaultCondition, PolicyBranch};
use crate::policy_node::{NodeKind, PolicyNode};
use crate::policy_situational::SituationalPolicyEntry;
use crate::purchase_guide::PurchaseGuide;

pub fn purchase_graph(
    guide: &PurchaseGuide,
    claim: &str,
    situational: &[SituationalPolicyEntry],
) -> Result<(String, Vec<PolicyNode>)> {
    let positions = guide
        .core_items
        .iter()
        .enumerate()
        .map(|(index, item)| (item.item_id, index + 1))
        .collect::<BTreeMap<_, _>>();
    let mut grouped = BTreeMap::<usize, Vec<&SituationalPolicyEntry>>::new();
    for entry in situational {
        let position = positions
            .get(&entry.comparator_id)
            .ok_or_else(|| Error::new("Situational comparator is absent from the core path"))?;
        grouped.entry(*position).or_default().push(entry);
    }
    let entry_id = |position: usize| {
        if position > guide.core_items.len() {
            "end".into()
        } else if grouped.contains_key(&position) {
            format!("situational-choice-{position}")
        } else {
            format!("core-{position}")
        }
    };
    let mut nodes = Vec::new();
    for (index, item) in guide.core_items.iter().enumerate() {
        let position = index + 1;
        let successor = entry_id(position + 1);
        let core_id = format!("core-{position}");
        if let Some(entries) = grouped.get(&position) {
            let mut branches = entries
                .iter()
                .map(|entry| entry.branch.clone())
                .collect::<Vec<_>>();
            branches.push(PolicyBranch {
                next_id: core_id.clone(),
                when: BranchCondition::Default(DefaultCondition::Default),
                priority: None,
            });
            nodes.push(PolicyNode {
                node_id: entry_id(position),
                kind: NodeKind::Choice,
                branches,
                ..PolicyNode::default()
            });
        }
        nodes.push(PolicyNode {
            node_id: core_id,
            kind: NodeKind::Purchase,
            next_id: Some(successor.clone()),
            evidence_ref: Some(claim.into()),
            item_id: Some(item.item_id),
            ..PolicyNode::default()
        });
        for entry in grouped.get(&position).into_iter().flatten() {
            let mut purchase = entry.purchase.clone();
            purchase.next_id = Some(successor.clone());
            nodes.push(purchase);
        }
    }
    nodes.push(PolicyNode {
        node_id: "end".into(),
        ..PolicyNode::default()
    });
    Ok((entry_id(1), nodes))
}

pub fn ability_nodes(
    guide: &PurchaseGuide,
    timeline: &[AbilityTimelineStep],
) -> Result<Vec<PolicyNode>> {
    let path = guide
        .ability_path
        .as_ref()
        .ok_or_else(|| Error::new("Guide has no ability prefix policy"))?;
    if path.ability_ids.len() != timeline.len()
        || path
            .ability_ids
            .iter()
            .zip(timeline)
            .any(|(id, step)| *id != step.ability_id)
    {
        return Err(Error::new(
            "Ability timeline differs from the selected path",
        ));
    }
    Ok(timeline
        .iter()
        .enumerate()
        .map(|(index, step)| PolicyNode {
            node_id: format!("ability-{}", index + 1),
            kind: NodeKind::Ability,
            evidence_ref: Some(format!("ability/{}/mechanics", step.ability_id)),
            ability_id: Some(step.ability_id),
            level: Some(step.level),
            ..PolicyNode::default()
        })
        .collect())
}
