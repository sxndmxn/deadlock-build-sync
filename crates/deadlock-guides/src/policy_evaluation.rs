use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::inventory::InventoryState;
use crate::policy_model::{Abstention, AbstentionReason, BuildPolicy};
use crate::policy_node::{NodeKind, PolicyNode};

#[derive(Clone, Debug, Default)]
pub struct EvaluationState {
    pub observable: Map<String, Value>,
    pub inventory: InventoryState,
    pub learned_abilities: BTreeSet<u64>,
    pub clock_s: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PolicyDecision {
    pub node_id: Option<String>,
    pub kind: Option<NodeKind>,
    pub abstention: Option<Abstention>,
}

impl PolicyDecision {
    const fn end() -> Self {
        Self {
            node_id: None,
            kind: Some(NodeKind::End),
            abstention: None,
        }
    }

    fn abstain(node: &PolicyNode, detail: String) -> Self {
        Self {
            node_id: None,
            kind: None,
            abstention: Some(Abstention {
                reason: AbstentionReason::OutOfDistribution,
                detail,
                node_id: Some(node.node_id.clone()),
            }),
        }
    }
}

enum EvaluationStep<'policy> {
    Next(&'policy str),
    Decision(PolicyDecision),
}

/// # Errors
/// Returns an error when the policy contains an unresolved successor or lacks a default branch.
pub fn next_policy_decision(
    policy: &BuildPolicy,
    state: &EvaluationState,
) -> Result<PolicyDecision> {
    let content = policy.content();
    let nodes = content
        .nodes
        .iter()
        .map(|node| (node.node_id.as_str(), node))
        .collect::<BTreeMap<_, _>>();
    let mut current = content.entry.as_str();
    let mut visited = BTreeSet::new();
    while visited.insert(current) {
        let node = nodes
            .get(current)
            .ok_or_else(|| Error::new("Policy decision references an unknown node"))?;
        match evaluate_node(node, state, &nodes)? {
            EvaluationStep::Next(next) => current = next,
            EvaluationStep::Decision(decision) => return Ok(decision),
        }
    }
    Ok(PolicyDecision::end())
}

fn evaluate_node<'policy>(
    node: &'policy PolicyNode,
    state: &EvaluationState,
    nodes: &BTreeMap<&str, &'policy PolicyNode>,
) -> Result<EvaluationStep<'policy>> {
    if matches!(node.kind, NodeKind::Choice | NodeKind::ObjectiveGate) {
        return choice_step(node, state, nodes);
    }
    if fulfilled(node, state) {
        return Ok(node.next_id.as_deref().map_or_else(
            || EvaluationStep::Decision(PolicyDecision::end()),
            EvaluationStep::Next,
        ));
    }
    if node
        .latest_time_s
        .is_some_and(|latest| state.clock_s > latest)
    {
        return Ok(node.recalculation_next.as_deref().map_or_else(
            || {
                EvaluationStep::Decision(PolicyDecision::abstain(
                    node,
                    format!(
                        "Missed timing for {}; no safe recalculation branch",
                        node.node_id
                    ),
                ))
            },
            EvaluationStep::Next,
        ));
    }
    Ok(EvaluationStep::Decision(PolicyDecision {
        node_id: Some(node.node_id.clone()),
        kind: Some(node.kind),
        abstention: None,
    }))
}

fn choice_step<'policy>(
    node: &'policy PolicyNode,
    state: &EvaluationState,
    nodes: &BTreeMap<&str, &'policy PolicyNode>,
) -> Result<EvaluationStep<'policy>> {
    let mut owned = Vec::new();
    for branch in node.branches.iter().filter(|branch| !branch.is_default()) {
        let target = nodes
            .get(branch.next_id.as_str())
            .ok_or_else(|| Error::new("Policy choice references an unknown node"))?;
        if target.kind == NodeKind::Purchase && target.optional && fulfilled(target, state) {
            owned.push(*target);
        }
    }
    if owned.len() > 1 {
        return Ok(EvaluationStep::Decision(PolicyDecision::abstain(
            node,
            "Multiple policy alternatives are already owned".into(),
        )));
    }
    if let Some(target) = owned.first() {
        return Ok(target.next_id.as_deref().map_or_else(
            || EvaluationStep::Decision(PolicyDecision::end()),
            EvaluationStep::Next,
        ));
    }
    let matching = node
        .branches
        .iter()
        .filter(|branch| branch.matches(&state.observable))
        .collect::<Vec<_>>();
    if matching.len() > 1 && matching.iter().any(|branch| branch.priority.is_none()) {
        return Ok(EvaluationStep::Decision(PolicyDecision::abstain(
            node,
            "Multiple policy guards matched without runtime precedence".into(),
        )));
    }
    let selected = matching
        .into_iter()
        .min_by_key(|branch| branch.priority.unwrap_or(0))
        .or_else(|| node.branches.iter().find(|branch| branch.is_default()))
        .ok_or_else(|| Error::new("Policy choice has no default branch"))?;
    Ok(EvaluationStep::Next(&selected.next_id))
}

fn fulfilled(node: &PolicyNode, state: &EvaluationState) -> bool {
    match node.kind {
        NodeKind::Purchase => node
            .item_id
            .is_some_and(|id| state.inventory.owned().contains(&id)),
        NodeKind::Ability => node
            .ability_id
            .is_some_and(|id| state.learned_abilities.contains(&id)),
        _ => false,
    }
}
