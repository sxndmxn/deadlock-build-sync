use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, fingerprint};

use crate::ability_timeline::validate_ability_timeline;
use crate::policy_model::BuildPolicy;
use crate::policy_node::{NodeKind, PolicyNode};
use crate::policy_state::{PolicyPathState, ValidationContext, ability_action, apply_policy_node};

/// # Errors
/// Returns an error when references, choices, mechanics, termination, or reachability fail on any policy path.
pub fn validate_policy(policy: &BuildPolicy, context: &ValidationContext) -> Result<()> {
    let document = policy.content();
    let nodes = document
        .nodes
        .iter()
        .map(|node| (node.node_id.as_str(), node))
        .collect::<BTreeMap<_, _>>();
    let claims = document
        .evidence
        .iter()
        .map(|claim| claim.claim_id.as_str())
        .collect::<BTreeSet<_>>();
    for node in &document.nodes {
        validate_references(node, &nodes, &claims, true)?;
    }
    for node in &document.ability_plan {
        validate_references(node, &nodes, &claims, false)?;
    }
    if !document.ability_plan.is_empty() {
        let actions = document
            .ability_plan
            .iter()
            .map(ability_action)
            .collect::<Result<Vec<_>>>()?;
        validate_ability_timeline(&context.ability_definitions, &context.level_info, &actions)?;
    }
    validate_paths(&document.entry, &nodes, context)
}

fn validate_references(
    node: &PolicyNode,
    nodes: &BTreeMap<&str, &PolicyNode>,
    claims: &BTreeSet<&str>,
    successors: bool,
) -> Result<()> {
    if matches!(node.kind, NodeKind::Choice | NodeKind::ObjectiveGate) {
        validate_choice(node)?;
    }
    if node
        .evidence_ref
        .as_ref()
        .is_some_and(|id| !claims.contains(id.as_str()))
    {
        return Err(Error::new(format!(
            "Node {} references missing evidence",
            node.node_id
        )));
    }
    if matches!(
        node.kind,
        NodeKind::Purchase | NodeKind::Sell | NodeKind::Ability
    ) && node.evidence_ref.is_none()
    {
        return Err(Error::new(format!(
            "Action node {} has no evidence",
            node.node_id
        )));
    }
    if successors {
        for next in node
            .successors()
            .into_iter()
            .chain(node.recalculation_next.as_deref())
        {
            if !nodes.contains_key(next) {
                return Err(Error::new(format!(
                    "Node {} has missing successor {next}",
                    node.node_id
                )));
            }
        }
    }
    Ok(())
}

fn validate_choice(node: &PolicyNode) -> Result<()> {
    if node
        .branches
        .iter()
        .filter(|branch| branch.is_default())
        .count()
        != 1
    {
        return Err(Error::new("Policy choice must have exactly one default"));
    }
    let guarded = node
        .branches
        .iter()
        .filter(|branch| !branch.is_default())
        .collect::<Vec<_>>();
    let mut signatures = BTreeSet::new();
    let mut overlap = false;
    let mut priorities = BTreeSet::new();
    for branch in &guarded {
        overlap |= !signatures.insert(fingerprint(&serde_json::to_value(branch.guards())?)?);
        if let Some(priority) = branch.priority
            && !priorities.insert(priority)
        {
            return Err(Error::new("Policy choice has duplicate priorities"));
        }
    }
    if overlap && guarded.iter().any(|branch| branch.priority.is_none()) {
        return Err(Error::new(
            "Policy choice has overlapping guards without precedence",
        ));
    }
    Ok(())
}

#[derive(Debug)]
struct PathVisit<'policy> {
    node_id: &'policy str,
    state: PolicyPathState,
    active: BTreeSet<&'policy str>,
}

fn validate_paths<'policy>(
    entry: &'policy str,
    nodes: &BTreeMap<&'policy str, &'policy PolicyNode>,
    context: &ValidationContext,
) -> Result<()> {
    let mut pending = vec![PathVisit {
        node_id: entry,
        state: PolicyPathState::default(),
        active: BTreeSet::new(),
    }];
    let mut reached = BTreeSet::new();
    let mut visits = 0_usize;
    while let Some(mut visit) = pending.pop() {
        visits += 1;
        if visits > 1_000_000 || visit.active.len() > 4096 {
            return Err(Error::new("Policy exceeds its path validation limit"));
        }
        if !visit.active.insert(visit.node_id) {
            return Err(Error::new(format!(
                "Policy has a reachable cycle at {}",
                visit.node_id
            )));
        }
        reached.insert(visit.node_id);
        let node = nodes
            .get(visit.node_id)
            .ok_or_else(|| Error::new("Policy path references an unknown node"))?;
        let state = apply_policy_node(node, &visit.state, context)
            .map_err(|error| error.context(&node.node_id))?;
        if node.kind == NodeKind::End {
            continue;
        }
        let successors = node.successors();
        if successors.is_empty() {
            return Err(Error::new(format!(
                "Reachable node {} does not terminate",
                node.node_id
            )));
        }
        for node_id in successors.into_iter().rev() {
            pending.push(PathVisit {
                node_id,
                state: state.clone(),
                active: visit.active.clone(),
            });
        }
    }
    let unreachable = nodes
        .keys()
        .copied()
        .filter(|id| !reached.contains(id))
        .collect::<Vec<_>>();
    if !unreachable.is_empty() {
        return Err(Error::new(format!(
            "Policy contains unreachable nodes: {}",
            unreachable.join(", ")
        )));
    }
    Ok(())
}
